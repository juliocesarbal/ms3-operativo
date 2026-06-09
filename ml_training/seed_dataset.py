"""Llena las tablas de datos para ML con informacion sintetica REALISTA y la persiste
en PostgreSQL (GCP). Esta es la fuente de entrenamiento de los modelos del MS3.

Genera:
  - sucursal         : ~10 nodos logisticos (ciudades reales de Bolivia, GPS reales).
  - zona_metrica     : ~30 zonas de reparto (dataset del K-Means / CU-13).
  - envio_historico  : ~5000 envios pasados con label de riesgo (dataset del RF / CU-12).

Las distancias son de CARRETERA (OSRM, ruteo real gratis), precalculadas en
ruta_cache; si OSRM no responde se cae a haversine*1.4 (sinuosidad).
El riesgo de cada envio se deriva de un score latente realista (distancia, peso,
hora pico, fin de semana, tipo de servicio y congestion de la zona destino).

Uso:
  python -m ml_training.seed_dataset          # llena si esta vacio
  python -m ml_training.seed_dataset --reset  # borra y vuelve a generar
"""
from __future__ import annotations

import sys
from datetime import timedelta

import numpy as np
from sqlalchemy import text

from app.core.database import Base, SessionLocal, engine
from app.models.dataset import (
    EnvioHistorico,
    IncidenteZona,
    RutaCache,
    ZonaDiaMetrica,
    ZonaMetrica,
)
from app.models.encomienda import utcnow
from app.models.sucursal import Sucursal
from ml_training._geo import (
    ARQ_CARRETERA,
    ARQ_URBANA,
    CIUDADES_CON_ZONAS,
    CORREDORES,
    HORAS_BASE_SERVICIO,
    HORAS_PICO,
    SUCURSALES,
    TIPOS_SERVICIO,
    ZONA_CODIGOS,
    ZONA_OFFSET,
    haversine_km,
)
from ml_training._routing import FACTOR_CARRETERA, matriz_km, osrm_route_points

N_ENVIOS = 5000
SEED = 42


def _seed_sucursales(db) -> dict[str, Sucursal]:
    objs = {}
    for nombre, depto, ciudad, direccion, lat, lng in SUCURSALES:
        s = Sucursal(
            nombre=nombre, departamento=depto, ciudad=ciudad, direccion=direccion,
            gps_lat=lat, gps_lng=lng, activa=True,
        )
        db.add(s)
        objs[nombre] = s
    db.flush()  # asigna ids
    print(f"  sucursales: {len(objs)}")
    return objs


# Crea una ZonaMetrica desde un arquetipo (con ruido) — desglosa incidencias por tipo.
def _mk_zona(rng, *, nombre, codigo, tipo_zona, tramo, sucursal_id, lat, lng, arq) -> ZonaMetrica:
    env = float(max(0, rng.normal(arq["num_envios"], arq["num_envios"] * 0.18)))
    t = float(max(1, rng.normal(arq["tiempo"], arq["tiempo"] * 0.13)))
    inc = float(max(0, rng.normal(arq["inc"], max(arq["inc"] * 0.3, 1))))
    vel = float(max(5, rng.normal(arq["vel"], arq["vel"] * 0.1)))
    mt, mb, mc, ms, ma = arq["mix"]  # trafico, bloqueo, clima, social, accidente
    return ZonaMetrica(
        nombre=nombre, codigo=codigo, tipo_zona=tipo_zona, tramo=tramo, sucursal_id=sucursal_id,
        gps_lat=lat, gps_lng=lng,
        num_envios=round(env, 1), tiempo_entrega_prom=round(t, 1),
        num_incidencias=round(inc, 1), velocidad_prom=round(vel, 1),
        inc_trafico=round(inc * mt, 1), inc_bloqueo=round(inc * mb, 1), inc_clima=round(inc * mc, 1),
        inc_social=round(inc * ms, 1), inc_accidente=round(inc * ma, 1),
        grupo=None,  # lo asigna K-Means (train_zonas)
    )


def _seed_zonas(db, sucursales: dict[str, Sucursal], rng) -> list[ZonaMetrica]:
    zonas: list[ZonaMetrica] = []

    # --- URBANAS: 5 sectores por ciudad grande (arquetipos alta/media/baja) ---
    arq_keys = list(ARQ_URBANA.keys())
    for ci, nombre_suc in enumerate(CIUDADES_CON_ZONAS):
        suc = sucursales[nombre_suc]
        for si, codigo in enumerate(ZONA_CODIGOS):
            arq = ARQ_URBANA[arq_keys[(ci + si) % len(arq_keys)]]
            dlat, dlng = ZONA_OFFSET[codigo]
            zonas.append(_mk_zona(
                rng, nombre=f"{suc.ciudad} - {codigo.capitalize()}", codigo=codigo,
                tipo_zona="URBANA", tramo=None, sucursal_id=suc.id,
                lat=suc.gps_lat + dlat + rng.normal(0, 0.004),
                lng=suc.gps_lng + dlng + rng.normal(0, 0.004), arq=arq,
            ))

    # --- CARRETERA: 3 puntos sobre cada corredor interurbano (ruta real OSRM) ---
    for nombre_a, nombre_b in CORREDORES:
        a_suc, b_suc = sucursales[nombre_a], sucursales[nombre_b]
        tramo = f"{a_suc.ciudad} ↔ {b_suc.ciudad}"
        pts = osrm_route_points((a_suc.gps_lat, a_suc.gps_lng), (b_suc.gps_lat, b_suc.gps_lng), n=3)
        for ti, (lat, lng) in enumerate(pts):
            # El tramo del medio es el más propenso a bloqueos.
            arq = ARQ_CARRETERA["BLOQUEO"] if ti == 1 else ARQ_CARRETERA["FLUIDA"]
            zonas.append(_mk_zona(
                rng, nombre=f"Ruta {a_suc.ciudad[:4]}–{b_suc.ciudad[:4]} · tramo {ti + 1}",
                codigo="TRAMO", tipo_zona="CARRETERA", tramo=tramo, sucursal_id=None,
                lat=lat, lng=lng, arq=arq,
            ))

    db.add_all(zonas)
    db.flush()
    urb = sum(1 for z in zonas if z.tipo_zona == "URBANA")
    print(f"  zonas (zona_metrica): {len(zonas)} ({urb} urbanas + {len(zonas) - urb} carretera)")
    return zonas


# Métricas por (zona x día). Cada zona tiene un "día pico" donde sube el caos
# (ej: eventos sociales los lunes) => ese (zona,día) cae en RETRASOS_FRECUENTES.
def _seed_zona_dia(db, zonas: list[ZonaMetrica], rng) -> int:
    filas = []
    for idx, z in enumerate(zonas):
        # 3 de cada 4 zonas tienen un día pico; el resto es estable toda la semana.
        dia_pico = [0, 4, 5, None][idx % 4]  # Lun / Vie / Sáb / sin pico
        for dia in range(7):
            envios_dia = max(0, (z.num_envios / 7) * FACTOR_DIA[dia] * float(1 + rng.normal(0, 0.08)))
            tiempo_dia = max(1, z.tiempo_entrega_prom * float(1 + rng.normal(0, 0.06)))
            esc = float(1 + rng.normal(0, 0.25))
            it, ib, ic, iso, ia = (z.inc_trafico / 7 * esc, z.inc_bloqueo / 7 * esc,
                                   z.inc_clima / 7 * esc, z.inc_social / 7 * esc, z.inc_accidente / 7 * esc)
            vel = z.velocidad_prom * float(1 + rng.normal(0, 0.05))
            if dia == dia_pico:
                # pico: suben bloqueos/social/tráfico/accidentes, sube tiempo, baja velocidad.
                ib *= 4; iso *= 4; it *= 2; ia *= 2
                tiempo_dia *= 1.5; vel *= 0.6
            inc_dia = it + ib + ic + iso + ia
            filas.append(
                {
                    "zona_metrica_id": z.id, "dia_semana": dia,
                    "gps_lat": z.gps_lat, "gps_lng": z.gps_lng,
                    "num_envios": round(envios_dia, 1), "tiempo_entrega_prom": round(tiempo_dia, 1),
                    "num_incidencias": round(max(0, inc_dia), 1), "velocidad_prom": round(max(5, vel), 1),
                    "inc_trafico": round(max(0, it), 1), "inc_bloqueo": round(max(0, ib), 1),
                    "inc_clima": round(max(0, ic), 1), "inc_social": round(max(0, iso), 1),
                    "inc_accidente": round(max(0, ia), 1), "grupo": None,
                }
            )
    db.bulk_insert_mappings(ZonaDiaMetrica, filas)
    print(f"  zona_dia_metrica: {len(filas)} (zonas x 7 días)")
    return len(filas)


# Incidentes de muestra reportados por asesores, concentrados en los días pico
# de cada zona (coherentes con zona_dia_metrica) + algunos aleatorios.
def _tipo_incidente(z: ZonaMetrica, rng) -> str:
    """Tipo de incidente ponderado por el desglose de la zona (carretera->bloqueo, urbana->tráfico/social)."""
    w = np.array([z.inc_trafico, z.inc_bloqueo, z.inc_clima, z.inc_social, z.inc_accidente], dtype=float)
    if w.sum() <= 0:
        return "TRAFICO"
    return str(rng.choice(["TRAFICO", "BLOQUEO", "CLIMA", "SOCIAL", "ACCIDENTE"], p=w / w.sum()))


def _seed_incidentes(db, zonas: list[ZonaMetrica], rng) -> int:
    filas = []
    for idx, z in enumerate(zonas):
        dia_pico = [0, 4, 5, None][idx % 4]
        if dia_pico is None:
            continue
        # Las zonas de carretera generan más reportes (bloqueos = lo que más retrasa).
        n_rep = int(rng.integers(3, 6)) if z.tipo_zona == "CARRETERA" else int(rng.integers(2, 4))
        for _ in range(n_rep):
            tipo = _tipo_incidente(z, rng)
            filas.append(
                {
                    "tracking_ref": "TRK-" + str(rng.integers(10000, 99999)),
                    "tipo": tipo,
                    "descripcion": OBS_INC[tipo],
                    "gps_lat": z.gps_lat + float(rng.normal(0, 0.004)),
                    "gps_lng": z.gps_lng + float(rng.normal(0, 0.004)),
                    "dia_semana": dia_pico,
                    "hora": int(rng.integers(7, 20)),
                    "zona_metrica_id": z.id,
                    "asesor_id": str(int(rng.integers(2, 6))),
                    "fecha": utcnow() - timedelta(days=int(rng.integers(0, 60))),
                }
            )
    # Algunos incidentes aleatorios adicionales (cualquier día).
    for _ in range(20):
        z = zonas[int(rng.integers(0, len(zonas)))]
        tipo = _tipo_incidente(z, rng)
        filas.append(
            {
                "tracking_ref": "TRK-" + str(rng.integers(10000, 99999)),
                "tipo": tipo,
                "descripcion": OBS_INC[tipo],
                "gps_lat": z.gps_lat + float(rng.normal(0, 0.005)),
                "gps_lng": z.gps_lng + float(rng.normal(0, 0.005)),
                "dia_semana": int(rng.integers(0, 7)),
                "hora": int(rng.integers(7, 20)),
                "zona_metrica_id": z.id,
                "asesor_id": str(int(rng.integers(2, 6))),
                "fecha": utcnow() - timedelta(days=int(rng.integers(0, 60))),
            }
        )
    db.bulk_insert_mappings(IncidenteZona, filas)
    print(f"  incidente_zona: {len(filas)} reportes de asesores")
    return len(filas)


# Distancias de CARRETERA (OSRM) suc->suc -> ruta_cache (para inferencia runtime).
# Devuelve el lookup {(origen_id, destino_id): km}.
def _seed_rutas(db, sucursales: dict[str, Sucursal]) -> dict[tuple[int, int], float]:
    sucs = list(sucursales.values())
    suc_pts = [(s.gps_lat, s.gps_lng) for s in sucs]
    m_ss, osrm_ss = matriz_km(suc_pts, suc_pts)
    filas, ruta = [], {}
    for i, o in enumerate(sucs):
        for j, d in enumerate(sucs):
            if i == j:
                continue
            ruta[(o.id, d.id)] = m_ss[i][j]
            filas.append({
                "sucursal_origen_id": o.id, "sucursal_destino_id": d.id,
                "distancia_km": m_ss[i][j], "fuente": "OSRM" if osrm_ss else "HAVERSINE",
            })
    db.bulk_insert_mappings(RutaCache, filas)
    print(f"  ruta_cache: {len(filas)} pares suc-suc (OSRM={osrm_ss})")
    return ruta


# Envío = sucursal origen -> sucursal destino (ciudad a ciudad). NO hay zona de
# entrega. La congestión sale de las zonas de CARRETERA cercanas al trazo del envío.
def _seed_envios(
    db,
    sucursales: dict[str, Sucursal],
    zonas: list[ZonaMetrica],
    rng,
    ruta_ss: dict[tuple[int, int], float],
) -> int:
    sucs = list(sucursales.values())
    n = N_ENVIOS
    carretera = [z for z in zonas if z.tipo_zona == "CARRETERA"]

    # Destino ponderado por el volumen urbano de su ciudad (ciudades grandes reciben más).
    vol: dict[int, float] = {}
    for z in zonas:
        if z.tipo_zona == "URBANA" and z.sucursal_id:
            vol[z.sucursal_id] = vol.get(z.sucursal_id, 0.0) + z.num_envios
    base = np.array([vol.get(s.id, 50.0) for s in sucs], dtype=float)
    p_dest = base / base.sum()

    di = rng.choice(len(sucs), size=n, p=p_dest)
    oi = rng.integers(0, len(sucs), size=n)
    peso = rng.gamma(2.0, 3.0, n).clip(0.1, 60)
    tipo = rng.choice(TIPOS_SERVICIO, n, p=[0.30, 0.40, 0.10, 0.20])
    w_cli = 1.0 / np.arange(1, len(CLIENTES) + 1)
    w_cli /= w_cli.sum()
    cli = rng.choice(len(CLIENTES), n, p=w_cli)
    dias_atras = rng.integers(0, 365, n)
    minutos = rng.integers(0, 24 * 60, n)

    # Congestión del corredor: incidencias de las zonas de carretera cercanas al trazo
    # recto origen->destino. Se cachea por par de sucursales (100 pares como máximo).
    cong_cache: dict[tuple[int, int], float] = {}

    def congestion(o: Sucursal, d: Sucursal) -> float:
        key = (o.id, d.id)
        if key in cong_cache:
            return cong_cache[key]
        seg = [(o.gps_lat + (d.gps_lat - o.gps_lat) * k / 10, o.gps_lng + (d.gps_lng - o.gps_lng) * k / 10) for k in range(11)]
        tot = 0.0
        for z in carretera:
            if min(haversine_km(z.gps_lat, z.gps_lng, p[0], p[1]) for p in seg) <= 30:
                tot += z.inc_bloqueo + z.inc_trafico
        val = tot / 50.0
        cong_cache[key] = val
        return val

    filas = []
    score = np.empty(n)
    for i in range(n):
        o = sucs[oi[i]]
        d = sucs[di[i]]
        if o.id == d.id:
            d = sucs[(di[i] + 1) % len(sucs)]  # forzar inter-ciudad

        dist = ruta_ss.get(
            (o.id, d.id),
            haversine_km(o.gps_lat, o.gps_lng, d.gps_lat, d.gps_lng) * FACTOR_CARRETERA,
        )
        dist = float(max(1.0, dist))

        fecha_reg = utcnow() - timedelta(days=int(dias_atras[i]), minutes=int(minutos[i]))
        hora = fecha_reg.hour
        dia = fecha_reg.weekday()
        cong = congestion(o, d)

        s = (
            0.004 * dist
            + 0.020 * peso[i]
            + (1.2 if hora in HORAS_PICO else 0.0)
            + (0.8 if dia >= 5 else 0.0)
            + (1.5 if tipo[i] == "CARGA_PESADA" else 0.0)
            + (-1.0 if tipo[i] == "EXPRESS" else 0.0)
            + 0.6 * cong
            + rng.normal(0, 0.7)
        )
        score[i] = s

        h_est = HORAS_BASE_SERVICIO[tipo[i]] + dist / 40.0
        filas.append(
            {
                "_score": s,
                "tracking_ref": "HIST-" + str(i + 1).zfill(5),
                "cliente_nombre": CLIENTES[cli[i]],
                "sucursal_origen_id": o.id,
                "sucursal_destino_id": d.id,
                "zona_metrica_id": None,
                "peso": float(peso[i]),
                "distancia": round(dist, 2),
                "hora": int(hora),
                "dia_semana": int(dia),
                "tipo_servicio": str(tipo[i]),
                "zona": d.ciudad,  # ciudad destino (trazabilidad; ya no es feature)
                "fecha_registro": fecha_reg,
                "horas_estimadas": round(h_est, 1),
            }
        )

    # Label por cuantiles globales: 50% BAJO, 30% MEDIO, 20% ALTO.
    q50, q80 = np.quantile(score, [0.50, 0.80])
    for f in filas:
        s = f.pop("_score")
        riesgo = "BAJO" if s < q50 else ("MEDIO" if s < q80 else "ALTO")
        # Transito coherente con el riesgo (ALTO tiende a pasarse del estimado).
        factor = {"BAJO": 0.85, "MEDIO": 1.05, "ALTO": 1.45}[riesgo]
        h_trans = f["horas_estimadas"] * factor * float(1 + rng.normal(0, 0.08))
        f["horas_transito"] = round(h_trans, 1)
        f["fecha_entrega"] = f["fecha_registro"] + timedelta(hours=h_trans)
        f["entregado_a_tiempo"] = h_trans <= f["horas_estimadas"] * 1.10
        f["riesgo"] = riesgo

    db.bulk_insert_mappings(EnvioHistorico, filas)
    dist_riesgo = {r: sum(1 for f in filas if f["riesgo"] == r) for r in ["BAJO", "MEDIO", "ALTO"]}
    print(f"  envios (envio_historico): {len(filas)}  ->  {dist_riesgo}")
    return len(filas)


# Agrega las columnas FK a tablas que ya existian (create_all no las altera).
# Postgres: ADD COLUMN IF NOT EXISTS es idempotente. En SQLite se ignora el error.
_ALTERS = [
    "ALTER TABLE encomienda ADD COLUMN IF NOT EXISTS sucursal_origen_id INTEGER REFERENCES sucursal(id)",
    "ALTER TABLE encomienda ADD COLUMN IF NOT EXISTS sucursal_destino_id INTEGER REFERENCES sucursal(id)",
    "ALTER TABLE encomienda ADD COLUMN IF NOT EXISTS distancia DOUBLE PRECISION",
    "ALTER TABLE envio_historico ADD COLUMN IF NOT EXISTS cliente_nombre VARCHAR",
    "ALTER TABLE ruta ADD COLUMN IF NOT EXISTS sucursal_id INTEGER REFERENCES sucursal(id)",
    # Zonas enriquecidas (carretera + desglose de incidencias):
    "ALTER TABLE zona_metrica ADD COLUMN IF NOT EXISTS tipo_zona VARCHAR DEFAULT 'URBANA'",
    "ALTER TABLE zona_metrica ADD COLUMN IF NOT EXISTS tramo VARCHAR",
    "ALTER TABLE zona_metrica ADD COLUMN IF NOT EXISTS velocidad_prom DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE zona_metrica ADD COLUMN IF NOT EXISTS inc_trafico DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE zona_metrica ADD COLUMN IF NOT EXISTS inc_bloqueo DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE zona_metrica ADD COLUMN IF NOT EXISTS inc_clima DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE zona_metrica ADD COLUMN IF NOT EXISTS inc_social DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE zona_metrica ADD COLUMN IF NOT EXISTS inc_accidente DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE zona_dia_metrica ADD COLUMN IF NOT EXISTS velocidad_prom DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE zona_dia_metrica ADD COLUMN IF NOT EXISTS inc_trafico DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE zona_dia_metrica ADD COLUMN IF NOT EXISTS inc_bloqueo DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE zona_dia_metrica ADD COLUMN IF NOT EXISTS inc_clima DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE zona_dia_metrica ADD COLUMN IF NOT EXISTS inc_social DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE zona_dia_metrica ADD COLUMN IF NOT EXISTS inc_accidente DOUBLE PRECISION DEFAULT 0",
]

# Clientes sintéticos (empresas + personas). Frecuencia desigual: los primeros
# envían mucho más (para que "mayores clientes" tenga sentido en el BI).
CLIENTES = [
    "Farmacorp S.A.", "Tigo Bolivia", "Banco Mercantil", "Saguapac", "Hipermaxi",
    "Distribuidora Andina", "Importadora del Sur", "Tecnotienda SRL", "La Casa del Repuesto",
    "Comercial Boliviana", "Textiles Oriente", "Agroinsumos Santa Cruz", "Logística Express",
    "Multicenter", "Toyosa S.A.", "Droguería Inti", "Librería Universitaria",
    "Juan Pérez", "María Gutiérrez", "Carlos Rojas", "Ana Vargas", "Luis Mamani",
    "Sofía Suárez", "Pedro Justiniano", "Lucía Camacho", "Jorge Áñez", "Elena Roca",
    "Marco Antelo", "Daniela Ortiz", "Raúl Zambrana",
]

# Factor de volumen por día (Lun..Dom): entre semana más envíos, finde menos.
FACTOR_DIA = [1.15, 1.10, 1.05, 1.10, 1.20, 0.70, 0.55]
# Tipos de incidente que reportan los asesores en campo.
TIPOS_INC = ["BLOQUEO", "TRAFICO", "SOCIAL", "ACCIDENTE", "CLIMA"]
OBS_INC = {
    "BLOQUEO": "Bloqueo de vía, paso cerrado",
    "TRAFICO": "Tráfico pesado, avance lento",
    "SOCIAL": "Evento social/feria en la zona",
    "ACCIDENTE": "Accidente de tránsito en ruta",
    "CLIMA": "Lluvia fuerte, calles anegadas",
}


def _migrar():
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        for sql in _ALTERS:
            try:
                conn.execute(text(sql))
            except Exception as e:  # pragma: no cover
                print(f"  (alter omitido: {e})")
    print("  migracion de columnas FK OK (encomienda/ruta -> sucursal)")


def _reset(db):
    db.query(RutaCache).delete()
    db.query(IncidenteZona).delete()
    db.query(EnvioHistorico).delete()
    db.query(ZonaDiaMetrica).delete()
    db.query(ZonaMetrica).delete()
    db.query(Sucursal).delete()
    db.commit()
    print("  (reset) tablas de dataset vaciadas")


def main():
    reset = "--reset" in sys.argv
    Base.metadata.create_all(bind=engine)
    _migrar()
    db = SessionLocal()
    try:
        if reset:
            _reset(db)

        if db.query(Sucursal).count() > 0:
            print("Ya hay datos sembrados. Usa --reset para regenerar.")
            return

        print("Sembrando datos sinteticos...")
        rng = np.random.default_rng(SEED)
        sucursales = _seed_sucursales(db)
        ruta_ss = _seed_rutas(db, sucursales)
        zonas = _seed_zonas(db, sucursales, rng)
        _seed_zona_dia(db, zonas, rng)
        _seed_incidentes(db, zonas, rng)
        _seed_envios(db, sucursales, zonas, rng, ruta_ss)
        db.commit()
        print("OK. Datos listos para entrenar (train_retraso / train_zonas).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
