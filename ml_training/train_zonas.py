"""CU-13: entrena K-Means para agrupar zonas POR DÍA y persiste el grupo descubierto.

Fuente: tabla `zona_dia_metrica` (zona x día de la semana). Capturar el día permite
descubrir patrones temporales (ej: una zona normalmente tranquila que los lunes se
satura por eventos sociales => ese (zona, lunes) cae en RETRASOS_FRECUENTES).
Si no hay datos zona-día, cae a `zona_metrica` (por zona) y luego a sintético.

El modelo KMeans es real; se valida k con silhouette + inercia (codo) para k=2..6.
Correr: python -m ml_training.train_zonas
"""
from collections import Counter

import numpy as np
import pandas as pd
import joblib
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from app.ml_models.features import ZONA_CLUSTER_FEATURES, ZONAS_MODEL_PATH

K = 3  # alta demanda / retrasos frecuentes / baja demanda


def cargar_desde_db():
    """Lee el dataset de clustering. Devuelve (df, fuente). df trae 'id' (+'zona_id' si zona-día)."""
    try:
        from app.core.database import SessionLocal
        from app.models.dataset import ZonaDiaMetrica, ZonaMetrica
    except Exception as e:  # pragma: no cover
        print(f"  (sin acceso a BD: {e})")
        return None, None

    db = SessionLocal()
    try:
        cols_zd = [ZonaDiaMetrica.id, ZonaDiaMetrica.zona_metrica_id] + [
            getattr(ZonaDiaMetrica, c) for c in ZONA_CLUSTER_FEATURES
        ]
        zd = db.query(*cols_zd).all()
        if zd:
            return pd.DataFrame(zd, columns=["id", "zona_id"] + ZONA_CLUSTER_FEATURES), "zona_dia"

        cols_z = [ZonaMetrica.id] + [getattr(ZonaMetrica, c) for c in ZONA_CLUSTER_FEATURES]
        z = db.query(*cols_z).all()
        if z:
            return pd.DataFrame(z, columns=["id"] + ZONA_CLUSTER_FEATURES), "zona_metrica"
        return None, None
    finally:
        db.close()


# Respaldo en memoria si las tablas están vacías (produce las features de clustering).
def generar_datos(n=420, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    m = n // 3

    def blk(env, t, inc, trf, blq, vel):
        return pd.DataFrame({
            "num_envios": rng.normal(env, env * 0.2, m).clip(0),
            "tiempo_entrega_prom": rng.normal(t, t * 0.15, m).clip(1),
            "num_incidencias": rng.normal(inc, max(inc * 0.3, 1), m).clip(0),
            "inc_trafico": rng.normal(trf, max(trf * 0.3, 1), m).clip(0),
            "inc_bloqueo": rng.normal(blq, max(blq * 0.3, 1), m).clip(0),
            "velocidad_prom": rng.normal(vel, vel * 0.1, m).clip(5),
        })

    df = pd.concat(
        [
            blk(500, 24, 6, 3.0, 0.3, 24),   # alta demanda urbana
            blk(160, 70, 44, 9.0, 20.0, 32), # carretera propensa a bloqueos
            blk(45, 26, 3, 1.3, 0.2, 55),    # baja demanda
        ],
        ignore_index=True,
    )
    df.insert(0, "id", range(1, len(df) + 1))
    return df


def etiquetar_clusters(km, scaler) -> dict:
    cent = scaler.inverse_transform(km.cluster_centers_)
    i_env = ZONA_CLUSTER_FEATURES.index("num_envios")
    i_inc = ZONA_CLUSTER_FEATURES.index("num_incidencias")
    orden_env = cent[:, i_env].argsort()
    baja = int(orden_env[0])
    resto = [i for i in range(K) if i != baja]
    retrasos = int(max(resto, key=lambda i: cent[i, i_inc]))
    alta = int(next(i for i in resto if i != retrasos))
    return {alta: "ALTA_DEMANDA", retrasos: "RETRASOS_FRECUENTES", baja: "BAJA_DEMANDA"}


def diagnostico_k(Xs):
    print("=== Diagnostico de k (silhouette / inercia) ===")
    for k in range(2, 7):
        km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(Xs)
        marca = "  <- elegido" if k == K else ""
        print(f"  k={k}  silhouette={silhouette_score(Xs, km.labels_):.3f}  inercia={km.inertia_:.1f}{marca}")


def persistir(df, fuente, grupos_fila):
    from app.core.database import SessionLocal
    from app.models.dataset import ZonaDiaMetrica, ZonaMetrica

    db = SessionLocal()
    try:
        if fuente == "zona_dia":
            for rid, grupo in zip(df["id"].tolist(), grupos_fila):
                db.query(ZonaDiaMetrica).filter(ZonaDiaMetrica.id == int(rid)).update({"grupo": grupo})
            # Grupo dominante por zona (moda de sus 7 días) -> vista por zona.
            por_zona: dict[int, list[str]] = {}
            for zid, grupo in zip(df["zona_id"].tolist(), grupos_fila):
                por_zona.setdefault(int(zid), []).append(grupo)
            for zid, gs in por_zona.items():
                db.query(ZonaMetrica).filter(ZonaMetrica.id == zid).update({"grupo": Counter(gs).most_common(1)[0][0]})
            print(f"  persistido: {len(grupos_fila)} filas zona-día + {len(por_zona)} zonas (moda)")
        elif fuente == "zona_metrica":
            for rid, grupo in zip(df["id"].tolist(), grupos_fila):
                db.query(ZonaMetrica).filter(ZonaMetrica.id == int(rid)).update({"grupo": grupo})
            print(f"  persistido: {len(grupos_fila)} zonas")
        db.commit()
    finally:
        db.close()


def main():
    df, fuente = cargar_desde_db()
    if fuente:
        print(f"Datos desde PostgreSQL ({fuente}): {len(df)} filas")
    else:
        print("Tablas vacías/sin BD -> usando generador sintético de respaldo")
        df, fuente = generar_datos(), "synth"

    scaler = StandardScaler()
    Xs = scaler.fit_transform(df[ZONA_CLUSTER_FEATURES].values)

    diagnostico_k(Xs)
    km = KMeans(n_clusters=K, n_init=10, random_state=42).fit(Xs)
    print(f"\nsilhouette_score (k={K}) = {silhouette_score(Xs, km.labels_):.3f}")
    labels = etiquetar_clusters(km, scaler)
    print("clusters ->", labels)

    grupos_fila = [labels[int(c)] for c in km.labels_]
    print("distribucion ->", dict(Counter(grupos_fila)))
    if fuente in ("zona_dia", "zona_metrica"):
        persistir(df, fuente, grupos_fila)

    joblib.dump(
        {"kmeans": km, "scaler": scaler, "labels": labels, "features": ZONA_CLUSTER_FEATURES},
        ZONAS_MODEL_PATH,
    )
    print(f"Modelo guardado en {ZONAS_MODEL_PATH}")


if __name__ == "__main__":
    main()
