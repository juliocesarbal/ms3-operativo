from pydantic import BaseModel, Field


# ---- CU-12: prediccion de retraso ----
# Envío sucursal->sucursal (sin zona de entrega). La distancia sale de las
# sucursales (origen/destino); `distancia` manual queda de respaldo.
class PredecirRetrasoIn(BaseModel):
    peso: float = Field(ge=0)
    hora: int = Field(ge=0, le=23)
    dia_semana: int = Field(ge=0, le=6)
    tipo_servicio: str
    sucursal_origen_id: int | None = None
    sucursal_destino_id: int | None = None
    distancia: float | None = Field(default=None, ge=0)


class PredecirRetrasoOut(BaseModel):
    riesgo: str  # BAJO | MEDIO | ALTO
    probabilidades: dict[str, float]
    distancia: float | None = None  # distancia usada (calculada de sucursales)


# ---- CU-13: agrupacion de zonas ----
class ZonaIn(BaseModel):
    nombre: str | None = None
    gps_lat: float = 0
    gps_lng: float = 0
    num_envios: float = Field(default=0, ge=0)
    tiempo_entrega_prom: float = Field(default=0, ge=0)
    num_incidencias: float = Field(default=0, ge=0)
    # Features enriquecidos del clustering (carretera vs urbana):
    inc_trafico: float = Field(default=0, ge=0)
    inc_bloqueo: float = Field(default=0, ge=0)
    velocidad_prom: float = Field(default=0, ge=0)


class AgruparZonasIn(BaseModel):
    zonas: list[ZonaIn]


class ZonaGrupoOut(BaseModel):
    nombre: str | None = None
    cluster: int
    grupo: str  # ALTA_DEMANDA | RETRASOS_FRECUENTES | BAJA_DEMANDA
    num_envios: float
    num_incidencias: float
