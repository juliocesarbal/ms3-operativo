"""Análisis de ruta para el mapa interactivo (CU operativo + ML)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.ruta import RutaAnalisisIn, RutaAnalisisOut
from app.services import ruta_analisis

router = APIRouter(prefix="/api/ops/ruta", tags=["ruta"])


# Cruza la ruta recomendada (OSRM, calculada en el browser) con las zonas de
# riesgo, los incidentes y el modelo de retraso. Devuelve todo para el mapa.
@router.post("/analizar", response_model=RutaAnalisisOut)
def analizar(
    data: RutaAnalisisIn,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    return ruta_analisis.analizar_ruta(db, data)
