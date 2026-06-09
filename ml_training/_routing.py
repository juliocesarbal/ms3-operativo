"""Ruteo por carretera con OSRM (gratis, sin API key) para el seed/entrenamiento.

Reemplaza la distancia haversine (línea recta) por la distancia REAL de carretera
entre puntos GPS, usando el servidor público de OSRM. Se usa SOLO en tiempo de
seed (batch offline), no en cada request. Si OSRM no responde (sin internet),
cae a haversine * FACTOR_CARRETERA para que el seed nunca se rompa.

OSRM espera coordenadas como `lng,lat` (¡ojo el orden!).
"""
from __future__ import annotations

import json
import urllib.request
from urllib.error import URLError

from ml_training._geo import haversine_km

OSRM_BASE = "https://router.project-osrm.org"
# Factor de sinuosidad: la carretera real es ~1.4x la línea recta (fallback offline).
FACTOR_CARRETERA = 1.4
_TIMEOUT = 30


def _coords(puntos: list[tuple[float, float]]) -> str:
    # puntos = [(lat, lng)] -> "lng,lat;lng,lat;..."
    return ";".join(f"{lng},{lat}" for lat, lng in puntos)


def osrm_table_km(
    origenes: list[tuple[float, float]],
    destinos: list[tuple[float, float]],
) -> list[list[float]] | None:
    """Matriz de distancias de carretera (km) origenes x destinos vía OSRM /table.

    Devuelve None si OSRM no está disponible (para activar el fallback haversine).
    """
    if not origenes or not destinos:
        return None
    todos = origenes + destinos
    s = len(origenes)
    d = len(destinos)
    src = ";".join(str(i) for i in range(s))
    dst = ";".join(str(i) for i in range(s, s + d))
    url = (
        f"{OSRM_BASE}/table/v1/driving/{_coords(todos)}"
        f"?sources={src}&destinations={dst}&annotations=distance"
    )
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (URLError, TimeoutError, ValueError, OSError) as e:
        print(f"  (OSRM no disponible: {e}; uso haversine*{FACTOR_CARRETERA})")
        return None
    if data.get("code") != "Ok" or "distances" not in data:
        print("  (OSRM sin 'distances'; uso haversine*factor)")
        return None
    # distances vienen en metros -> km. Algún par sin ruta llega como None.
    out: list[list[float]] = []
    for i, fila in enumerate(data["distances"]):
        row = []
        for j, m in enumerate(fila):
            if m is None:
                m = haversine_km(*origenes[i], *destinos[j]) * 1000 * FACTOR_CARRETERA
            row.append(round(m / 1000.0, 2))
        out.append(row)
    return out


def osrm_route_points(
    origen: tuple[float, float],
    destino: tuple[float, float],
    n: int = 3,
) -> list[tuple[float, float]]:
    """n puntos interiores [(lat,lng)] sobre la ruta de carretera (OSRM geometry).

    Sirven para colocar zonas tipo CARRETERA sobre el trazo real del corredor.
    Fallback: interpolación lineal entre origen y destino si OSRM no responde.
    """
    olat, olng = origen
    dlat, dlng = destino
    url = (
        f"{OSRM_BASE}/route/v1/driving/{olng},{olat};{dlng},{dlat}"
        f"?overview=full&geometries=geojson"
    )
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        coords = data["routes"][0]["geometry"]["coordinates"]  # [[lng,lat],...]
        # Tomar n puntos equiespaciados en el interior del trazo.
        pts = []
        for k in range(1, n + 1):
            idx = int(len(coords) * k / (n + 1))
            lng, lat = coords[min(idx, len(coords) - 1)]
            pts.append((round(lat, 5), round(lng, 5)))
        return pts
    except (URLError, TimeoutError, ValueError, OSError, KeyError, IndexError):
        # Interpolación lineal de respaldo.
        return [
            (round(olat + (dlat - olat) * k / (n + 1), 5), round(olng + (dlng - olng) * k / (n + 1), 5))
            for k in range(1, n + 1)
        ]


def matriz_km(
    origenes: list[tuple[float, float]],
    destinos: list[tuple[float, float]],
) -> tuple[list[list[float]], bool]:
    """Matriz de km por carretera. Devuelve (matriz, uso_osrm).

    Intenta OSRM; si falla, calcula haversine * FACTOR_CARRETERA. `uso_osrm`
    indica de dónde salieron los datos (para log/trazabilidad).
    """
    m = osrm_table_km(origenes, destinos)
    if m is not None:
        return m, True
    fallback = [
        [round(haversine_km(*o, *d) * FACTOR_CARRETERA, 2) for d in destinos]
        for o in origenes
    ]
    return fallback, False
