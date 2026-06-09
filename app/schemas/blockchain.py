from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RegistrarEventoIn(BaseModel):
    tracking: str | None = None
    tipo_evento: str  # CREACION_GUIA | CAMBIO_ESTADO | ENTREGA_CONFIRMADA | HASH_DOCUMENTO
    datos: dict = {}


class EventoBlockchainOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tracking: str | None
    tipo_evento: str
    hash_sha256: str
    tx_hash: str | None
    fecha: datetime
