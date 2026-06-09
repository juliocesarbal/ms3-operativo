from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.estados import Estado


class EncomiendaCreate(BaseModel):
    cliente_id: str | None = None
    cliente_nombre: str | None = None
    cliente_direccion: str | None = None
    origen: str | None = None
    destino: str | None = None
    peso: float | None = Field(default=None, ge=0)
    servicio_ref: str | None = None
    zona_ref: str | None = None
    costo: float | None = Field(default=None, ge=0)
    sucursal_origen_id: int | None = None
    sucursal_destino_id: int | None = None


class EstadoHistorialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    estado: str
    fecha: datetime
    ubicacion: str | None = None
    gps_lat: float | None = None
    gps_lng: float | None = None


class EncomiendaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tracking_code: str
    cliente_id: str | None
    cliente_nombre: str | None
    cliente_direccion: str | None
    origen: str | None
    destino: str | None
    peso: float | None
    servicio_ref: str | None
    zona_ref: str | None
    sucursal_origen_id: int | None
    sucursal_destino_id: int | None
    distancia: float | None
    estado: str
    costo: float | None
    riesgo_retraso: str | None
    created_at: datetime


class TrackingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tracking_code: str
    estado: str
    historial: list[EstadoHistorialOut]


class CambiarEstado(BaseModel):
    estado: Estado
    ubicacion: str | None = None
    gps_lat: float | None = None
    gps_lng: float | None = None
