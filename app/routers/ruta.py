"""Análisis de ruta para el mapa interactivo (CU operativo + ML)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.sucursal import Sucursal
from app.schemas.ruta import RutaAnalisisIn, RutaAnalisisOut, RutaOsrmOut
from app.services import geo, ruta_analisis

router = APIRouter(prefix="/api/ops/ruta", tags=["ruta"])


# Ruta de carretera (OSRM) entre dos sucursales, calculada en el BACKEND.
# El navegador la usa como fallback cuando su llamada directa a OSRM falla
# (throttle/CORS del demo server). Server-to-server es estable y cacheable.
@router.get("/osrm", response_model=RutaOsrmOut)
def ruta_osrm(
    origen_id: int,
    destino_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    o = db.get(Sucursal, origen_id)
    d = db.get(Sucursal, destino_id)
    if not o or not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sucursal origen o destino no existe.")
    geometry, dist, dur, fuente = geo.ruta_carretera(o.gps_lat, o.gps_lng, d.gps_lat, d.gps_lng)
    return RutaOsrmOut(geometry=geometry, distancia_km=dist, duracion_min=dur, fuente=fuente)


# Cruza la ruta recomendada (OSRM) con las zonas de riesgo, los incidentes y el
# modelo de retraso. Devuelve todo para el mapa.
@router.post("/analizar", response_model=RutaAnalisisOut)
def analizar(
    data: RutaAnalisisIn,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    return ruta_analisis.analizar_ruta(db, data)
