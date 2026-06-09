"""Utilidades geográficas para la operación (distancias entre sucursales/zonas).

La distancia es el parámetro más fuerte del modelo de retraso. El modelo se
entrena con distancia de CARRETERA (OSRM), precalculada en `ruta_cache`. En
inferencia se lee de esa tabla (sin llamar a OSRM); si un par no está cacheado,
se aproxima con haversine * FACTOR_CARRETERA para mantener la misma métrica.
"""
from __future__ import annotations

import json
import math
import urllib.request
from functools import lru_cache
from urllib.error import URLError

from sqlalchemy.orm import Session

from app.models.sucursal import Sucursal

# Debe coincidir con ml_training/_routing.py (sinuosidad carretera vs línea recta).
FACTOR_CARRETERA = 1.4

# OSRM público (gratis, sin API key). Se llama SERVER-SIDE (no desde el navegador)
# para que el ruteo no dependa del CORS/throttle del browser contra el demo server.
OSRM_BASE = "https://router.project-osrm.org"
_OSRM_TIMEOUT = 12


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


@lru_cache(maxsize=256)
def _osrm_route_cached(olat: float, olng: float, dlat: float, dlng: float):
    """Pide a OSRM la ruta de carretera (server-side). Cacheado en proceso.

    Devuelve (geometry [[lat,lng],...], distancia_km, duracion_min, "OSRM") o
    None si OSRM no responde. OSRM espera coordenadas como lng,lat.
    """
    url = (
        f"{OSRM_BASE}/route/v1/driving/{olng},{olat};{dlng},{dlat}"
        f"?overview=full&geometries=geojson"
    )
    try:
        with urllib.request.urlopen(url, timeout=_OSRM_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (URLError, TimeoutError, ValueError, OSError) as e:
        print(f"  (OSRM ruta no disponible: {e})")
        return None
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    r = data["routes"][0]
    coords = r["geometry"]["coordinates"]                  # [[lng,lat],...]
    geometry = [[lat, lng] for lng, lat in coords]         # -> [[lat,lng],...]
    return geometry, round(r["distance"] / 1000.0, 2), round(r["duration"] / 60.0, 1), "OSRM"


def ruta_carretera(
    olat: float, olng: float, dlat: float, dlng: float
) -> tuple[list[list[float]], float, float | None, str]:
    """Ruta de carretera entre dos puntos. Intenta OSRM (server-side); si falla,
    cae a línea recta con distancia haversine*factor (misma métrica del seed).

    Devuelve (geometry [[lat,lng],...], distancia_km, duracion_min|None, fuente).
    fuente = "OSRM" (camino real) o "HAVERSINE" (recta aproximada).
    """
    osrm = _osrm_route_cached(olat, olng, dlat, dlng)
    if osrm is not None:
        return osrm
    dist = round(haversine_km(olat, olng, dlat, dlng) * FACTOR_CARRETERA, 2)
    return [[olat, olng], [dlat, dlng]], dist, None, "HAVERSINE"
