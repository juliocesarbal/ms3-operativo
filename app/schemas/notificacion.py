from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificacionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: str
    titulo: str
    cuerpo: str | None = None
    data_json: str | None = None
    leida: bool
    created_at: datetime
    read_at: datetime | None = None


class ContadorOut(BaseModel):
    no_leidas: int


# El admin envia un aviso a un asesor (p.ej. respuesta a una incidencia).
class NotificacionAdminIn(BaseModel):
    asesor_id: str
    titulo: str
    cuerpo: str | None = None
    tipo: str = "RESPUESTA_ADMIN"


# El movil registra su token FCM para recibir push real.
class RegistrarTokenIn(BaseModel):
    token: str
    plataforma: str | None = None  # android | ios
