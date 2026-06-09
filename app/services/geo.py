"""Utilidades geográficas para la operación (distancias entre sucursales/zonas).

La distancia es el parámetro más fuerte del modelo de retraso. El modelo se
entrena con distancia de CARRETERA (OSRM), precalculada en `ruta_cache`. En
inferencia se lee de esa tabla (sin llamar a OSRM); si un par no está cacheado,
se aproxima con haversine * FACTOR_CARRETERA para mantener la misma métrica.
"""
from __future__ import annotations

import math

from sqlalchemy.orm import Session

from app.models.sucursal import Sucursal

# Debe coincidir con ml_training/_routing.py (sinuosidad carretera vs línea recta).
FACTOR_CARRETERA = 1.4


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distancia en km entre dos puntos GPS (línea recta)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def distancia_sucursales(db: Session, origen_id: int | None, destino_id: int | None) -> float | None:
    """Distancia (km) de CARRETERA entre dos sucursales. None si falta alguna.

    Lee de `ruta_cache` (precalculado con OSRM en el seed). Fallback: haversine
    * factor si el par no está cacheado (misma métrica que usa el seed offline).
    """
    if not origen_id or not destino_id:
        return None
    if origen_id == destino_id:
        return 0.0
    from app.models.dataset import RutaCache

    rc = (
        db.query(RutaCache)
        .filter(
            RutaCache.sucursal_origen_id == origen_id,
            RutaCache.sucursal_destino_id == destino_id,
        )
        .first()
    )
    if rc:
        return round(rc.distancia_km, 2)

    o = db.get(Sucursal, origen_id)
    d = db.get(Sucursal, destino_id)
    if not o or not d:
        return None
    return round(haversine_km(o.gps_lat, o.gps_lng, d.gps_lat, d.gps_lng) * FACTOR_CARRETERA, 2)


def zona_mas_cercana(db: Session, lat: float, lng: float):
    """Devuelve la ZonaMetrica más cercana a un punto GPS (para ubicar incidentes)."""
    from app.models.dataset import ZonaMetrica

    zonas = db.query(ZonaMetrica).all()
    if not zonas:
        return None
    return min(zonas, key=lambda z: haversine_km(lat, lng, z.gps_lat, z.gps_lng))
