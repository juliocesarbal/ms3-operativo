"""Schemas del análisis de ruta (mapa interactivo): cruza la ruta recomendada
(OSRM) con las zonas de riesgo y los incidentes del modelo del MS3."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RutaAnalisisIn(BaseModel):
    sucursal_origen_id: int
    sucursal_destino_id: int
    dia_semana: int = Field(ge=0, le=6)        # 0=Lun ... 6=Dom
    hora: int = Field(default=9, ge=0, le=23)
    peso: float = Field(default=5.0, gt=0)
    tipo_servicio: str = "PAQUETE_NORMAL"
    # Geometría de la ruta de OSRM (la calcula el navegador): [[lat, lng], ...].
    # Vacía => el backend asume línea recta origen-destino.
    geometry: list[list[float]] = Field(default_factory=list)
    distancia_km: float | None = None          # de OSRM (display); si falta, usa ruta_cache
    duracion_min: float | None = None          # de OSRM (display)
    umbral_km: float = Field(default=5.0, gt=0)  # cercanía zona/incidente a la ruta


class SucursalRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    ciudad: str
    gps_lat: float
    gps_lng: float


class RutaOsrmOut(BaseModel):
    """Geometría de la ruta de carretera (OSRM) calculada en el backend."""
    geometry: list[list[float]]      # [[lat, lng], ...]
    distancia_km: float
    duracion_min: float | None
    fuente: str                      # OSRM (camino real) | HAVERSINE (recta aprox)


class ZonaEnRuta(BaseModel):
    id: int
    nombre: str
    codigo: str
    grupo: str | None
    gps_lat: float
    gps_lng: float
    num_incidencias: float
    incidentes_dia: int          # incidentes reportados ese día de la semana
    dist_a_ruta_km: float


class IncidenteEnRuta(BaseModel):
    tipo: str
    descripcion: str | None
    gps_lat: float
    gps_lng: float
    hora: int | None


class RutaAnalisisOut(BaseModel):
    origen: SucursalRef
    destino: SucursalRef
    dia_semana: int
    distancia_km: float
    duracion_estimada_h: float
    riesgo: str                  # del modelo (BAJO|MEDIO|ALTO)
    probabilidad: float | None
    probabilidades: dict[str, float] = {}
    retraso_estimado_h: float    # extra derivado del histórico (zona×día)
    eta_total_h: float           # duración + retraso
    zonas_en_ruta: list[ZonaEnRuta]
    incidentes: list[IncidenteEnRuta]
    resumen: str
