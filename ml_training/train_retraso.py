"""CU-12: entrena el modelo de riesgo de retraso (RandomForest) y lo persiste.

Fuente de datos: la tabla `envio_historico` de PostgreSQL (sembrada con
ml_training.seed_dataset). Si la tabla esta vacia, cae a un generador sintetico
en memoria como respaldo. El modelo sklearn es real (split, metricas, pipeline,
class_weight balanceado, importancia de features). Features: peso, distancia,
hora, dia_semana, tipo_servicio -> riesgo (BAJO|MEDIO|ALTO). Sin zona de entrega
(envío sucursal->sucursal).

Correr: python -m ml_training.train_retraso
"""
import numpy as np
import pandas as pd
import joblib
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.ml_models.features import (
    RETRASO_CATEGORICAL,
    RETRASO_MODEL_PATH,
    RETRASO_NUMERIC,
    TIPOS_SERVICIO,
)

HORAS_PICO = [7, 8, 18, 19, 20]


def cargar_desde_db() -> pd.DataFrame | None:
    """Lee el historico real de envios desde PostgreSQL. None si esta vacio."""
    try:
        from app.core.database import SessionLocal
        from app.models.dataset import EnvioHistorico
    except Exception as e:  # pragma: no cover
        print(f"  (sin acceso a BD: {e})")
        return None

    db = SessionLocal()
    try:
        cols = RETRASO_NUMERIC + RETRASO_CATEGORICAL + ["riesgo"]
        rows = db.query(
            EnvioHistorico.peso,
            EnvioHistorico.distancia,
            EnvioHistorico.hora,
            EnvioHistorico.dia_semana,
            EnvioHistorico.tipo_servicio,
            EnvioHistorico.riesgo,
        ).all()
    finally:
        db.close()

    if not rows:
        return None
    return pd.DataFrame(rows, columns=cols)


# Respaldo: genera datos en memoria si la tabla envio_historico esta vacia.
def generar_datos(n=6000, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    peso = rng.gamma(2.0, 3.0, n).clip(0.1, 60)
    distancia = rng.gamma(2.0, 15.0, n).clip(1, 300)
    hora = rng.integers(0, 24, n)
    dia = rng.integers(0, 7, n)
    tipo = rng.choice(TIPOS_SERVICIO, n, p=[0.30, 0.40, 0.10, 0.20])

    # Riesgo latente: distancia/peso suben riesgo; express baja; carga pesada sube;
    # horas pico y fin de semana suben. (Sin zona: envío sucursal->sucursal.)
    score = (
        0.015 * distancia
        + 0.020 * peso
        + np.where(np.isin(hora, HORAS_PICO), 1.2, 0.0)
        + np.where(dia >= 5, 0.8, 0.0)
        + np.where(tipo == "CARGA_PESADA", 1.5, 0.0)
        + np.where(tipo == "EXPRESS", -1.0, 0.0)
        + rng.normal(0, 0.8, n)
    )
    q50, q80 = np.quantile(score, [0.50, 0.80])
    riesgo = np.where(score < q50, "BAJO", np.where(score < q80, "MEDIO", "ALTO"))

    return pd.DataFrame(
        {
            "peso": peso,
            "distancia": distancia,
            "hora": hora,
            "dia_semana": dia,
            "tipo_servicio": tipo,
            "riesgo": riesgo,
        }
    )


def _importancias(pipe) -> dict[str, float]:
    """Importancia de cada feature (interpretabilidad, util para BI/defensa)."""
    pre = pipe.named_steps["pre"]
    nombres = list(pre.get_feature_names_out())
    imp = pipe.named_steps["clf"].feature_importances_
    pares = sorted(zip(nombres, imp), key=lambda x: x[1], reverse=True)
    return {n: round(float(v), 4) for n, v in pares}


def main():
    df = cargar_desde_db()
    if df is not None:
        print(f"Datos desde PostgreSQL (envio_historico): {len(df)} filas")
    else:
        print("Tabla vacia/sin BD -> usando generador sintetico de respaldo")
        df = generar_datos()

    X = df[RETRASO_NUMERIC + RETRASO_CATEGORICAL]
    y = df["riesgo"]

    pre = ColumnTransformer(
        [
            ("num", StandardScaler(), RETRASO_NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore"), RETRASO_CATEGORICAL),
        ]
    )
    pipe = Pipeline(
        [
            ("pre", pre),
            # max_depth + min_samples_leaf: limitan tamano del modelo sin perder senal.
            # class_weight balanceado: las clases son 50/30/20 (BAJO/MEDIO/ALTO).
            (
                "clf",
                RandomForestClassifier(
                    n_estimators=200,
                    max_depth=14,
                    min_samples_leaf=15,
                    class_weight="balanced",
                    random_state=42,
                    n_jobs=-1,
                ),
            ),
        ]
    )

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    pipe.fit(X_tr, y_tr)

    print("=== Reporte (test) ===")
    print(classification_report(y_te, pipe.predict(X_te)))

    importancias = _importancias(pipe)
    print("=== Importancia de features ===")
    for nombre, val in importancias.items():
        print(f"  {nombre:28s} {val}")

    joblib.dump(
        {"pipeline": pipe, "clases": list(pipe.classes_), "importancias": importancias},
        RETRASO_MODEL_PATH,
    )
    print(f"Modelo guardado en {RETRASO_MODEL_PATH}")


if __name__ == "__main__":
    main()
