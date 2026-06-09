from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RutaCreate(BaseModel):
    asesor_id: str
    zona_ref: str | None = None
    fecha: str | None = None
    encomienda_ids: list[int] = []


class EncomiendaResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tracking_code: str
    estado: str
    destino: str | None = None


class RutaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asesor_id: str
    zona_ref: str | None
    fecha: str | None
    estado: str
    created_at: datetime
    encomiendas: list[EncomiendaResumen]


class EscaneoQR(BaseModel):
    tracking_code: str


class EscaneoResult(BaseModel):
    valido: bool
    tracking_code: str
    estado: str
    mensaje: str


class EntregaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    encomienda_id: int
    asesor_id: str | None
    foto_url: str | None
    gps_lat: float | None
    gps_lng: float | None
    qr_validado: bool
    fecha: datetime
