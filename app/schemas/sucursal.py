from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SucursalCreate(BaseModel):
    nombre: str
    departamento: str
    ciudad: str
    direccion: str | None = None
    gps_lat: float = Field(ge=-90, le=90)
    gps_lng: float = Field(ge=-180, le=180)
    activa: bool = True


class SucursalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    departamento: str
    ciudad: str
    direccion: str | None
    gps_lat: float
    gps_lng: float
    activa: bool
    created_at: datetime
