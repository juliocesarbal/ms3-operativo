"""Análisis de una ruta: cruza la geometría recomendada (OSRM) con las zonas de
riesgo (K-Means), los incidentes reportados y el modelo de retraso (RandomForest).

Idea: OSRM da el camino + ETA base; NUESTROS modelos agregan el delta que OSRM
no conoce (zonas con eventos sociales los lunes, incidentes de campo, patrones
históricos zona×día). Ese delta es el "retraso extra estimado".
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ml_models import inference
from app.models.dataset import EnvioHistorico, IncidenteZona, Prediccion, ZonaMetrica
from app.models.sucursal import Sucursal
from app.schemas.ruta import (
    IncidenteEnRuta,
    RutaAnalisisIn,
    RutaAnalisisOut,
    SucursalRef,
    ZonaEnRuta,
)
from app.services import geo

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
VELOCIDAD_KMH = 45.0  # para estimar duración si OSRM no la dio


def _min_dist_km(lat: float, lng: float, geometry: list[list[float]]) -> float:
    """Distancia mínima (km) de un punto a la polilínea (aprox por vértices)."""
    return min(geo.haversine_km(lat, lng, p[0], p[1]) for p in geometry)


def analizar_ruta(db: Session, data: RutaAnalisisIn) -> RutaAnalisisOut:
    origen = db.get(Sucursal, data.sucursal_origen_id)
    destino = db.get(Sucursal, data.sucursal_destino_id)
    if not origen or not destino:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sucursal origen o destino no existe.")

    # Geometría: la de OSRM (browser) o, si falta, línea recta origen->destino.
    geometry = data.geometry or [
        [origen.gps_lat, origen.gps_lng],
        [destino.gps_lat, destino.gps_lng],
    ]

    # Distancia: OSRM (browser) o ruta_cache (carretera). Duración: OSRM o estimada.
    distancia = data.distancia_km or geo.distancia_sucursales(db, origen.id, destino.id) or 0.0
    if data.duracion_min:
        duracion_h = round(data.duracion_min / 60.0, 2)
    else:
        duracion_h = round(distancia / VELOCIDAD_KMH, 2) if distancia else 0.0

    # ---- Zonas cercanas a la ruta (point-to-polilínea) ----
    zonas_en_ruta: list[ZonaEnRuta] = []
    zona_ids: list[int] = []
    for z in db.query(ZonaMetrica).all():
        d = _min_dist_km(z.gps_lat, z.gps_lng, geometry)
        if d <= data.umbral_km:
            inc_dia = (
                db.query(func.count(IncidenteZona.id))
                .filter(
                    IncidenteZona.zona_metrica_id == z.id,
                    IncidenteZona.dia_semana == data.dia_semana,
                )
                .scalar()
                or 0
            )
            zonas_en_ruta.append(
                ZonaEnRuta(
                    id=z.id, nombre=z.nombre, codigo=z.codigo, grupo=z.grupo,
                    gps_lat=z.gps_lat, gps_lng=z.gps_lng,
                    num_incidencias=round(z.num_incidencias, 1),
                    incidentes_dia=int(inc_dia),
                    dist_a_ruta_km=round(d, 2),
                )
            )
            zona_ids.append(z.id)
    zonas_en_ruta.sort(key=lambda x: (-(x.incidentes_dia), -x.num_incidencias))

    # ---- Incidentes reportados ese día, cercanos a la ruta ----
    incidentes: list[IncidenteEnRuta] = []
    for inc in db.query(IncidenteZona).filter(IncidenteZona.dia_semana == data.dia_semana).all():
        if _min_dist_km(inc.gps_lat, inc.gps_lng, geometry) <= data.umbral_km:
            incidentes.append(
                IncidenteEnRuta(
                    tipo=inc.tipo, descripcion=inc.descripcion,
                    gps_lat=inc.gps_lat, gps_lng=inc.gps_lng, hora=inc.hora,
                )
            )

    # ---- Riesgo del modelo (RandomForest) — envío sucursal->sucursal, sin zona ----
    probabilidades: dict[str, float] = {}
    try:
        pred = inference.predecir_retraso(
            {
                "peso": data.peso,
                "distancia": distancia,
                "hora": data.hora,
                "dia_semana": data.dia_semana,
                "tipo_servicio": data.tipo_servicio,
            }
        )
        riesgo = pred["riesgo"]
        probabilidades = pred["probabilidades"]
        prob = probabilidades.get(riesgo)
    except FileNotFoundError:
        riesgo, prob = "DESCONOCIDO", None

    # ---- Retraso extra derivado del histórico (corredor origen->destino × día) ----
    retraso = _retraso_estimado(db, origen.id, destino.id, data.dia_semana)
    eta_total = round(duracion_h + retraso, 2)

    # Persistir la predicción (spec: "resultados de prediccion").
    if riesgo != "DESCONOCIDO":
        db.add(Prediccion(tipo="RETRASO", riesgo=riesgo, probabilidad=prob, modelo="RandomForest"))
        db.commit()

    resumen = _resumen(origen, destino, distancia, riesgo, retraso, zonas_en_ruta, data.dia_semana)

    return RutaAnalisisOut(
        origen=SucursalRef.model_validate(origen),
        destino=SucursalRef.model_validate(destino),
        dia_semana=data.dia_semana,
        distancia_km=round(distancia, 2),
        duracion_estimada_h=duracion_h,
        riesgo=riesgo,
        probabilidad=prob,
        probabilidades=probabilidades,
        retraso_estimado_h=retraso,
        eta_total_h=eta_total,
        zonas_en_ruta=zonas_en_ruta,
        incidentes=incidentes,
        resumen=resumen,
    )


def _retraso_estimado(db: Session, origen_id: int, destino_id: int, dia: int) -> float:
    """Horas de retraso extra esperadas = promedio(horas_transito - horas_estimadas)
    sobre los envíos históricos de ESE corredor (origen->destino) ese día. Explicable,
    sin modelo nuevo. Si hay pocos datos, relaja a destino+día, luego solo día."""
    delta = func.avg(EnvioHistorico.horas_transito - EnvioHistorico.horas_estimadas)
    base = db.query(delta).filter(
        EnvioHistorico.dia_semana == dia,
        EnvioHistorico.horas_transito.isnot(None),
        EnvioHistorico.horas_estimadas.isnot(None),
    )
    val = base.filter(
        EnvioHistorico.sucursal_origen_id == origen_id,
        EnvioHistorico.sucursal_destino_id == destino_id,
    ).scalar()
    if val is None:  # relajar: a esta ciudad destino ese día
        val = base.filter(EnvioHistorico.sucursal_destino_id == destino_id).scalar()
    if val is None:  # relajar: promedio del día
        val = base.scalar()
    return round(max(0.0, float(val or 0.0)), 2)


def _resumen(origen, destino, dist, riesgo, retraso, zonas, dia) -> str:
    criticas = [z for z in zonas if z.incidentes_dia > 0 or (z.grupo == "RETRASOS_FRECUENTES")]
    txt = f"Ruta {origen.ciudad} → {destino.ciudad} · {dist:.0f} km · riesgo {riesgo}"
    if retraso > 0:
        txt += f" · +{retraso:.1f} h extra estimadas"
    if criticas:
        nombres = ", ".join(z.nombre for z in criticas[:3])
        txt += f" · zonas sensibles los {DIAS[dia]}: {nombres}"
    return txt
