"""Schemas para exponer los datasets de ML (solo lectura, para ver/dashboard)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

TIPOS_INCIDENTE = ["BLOQUEO", "TRAFICO", "SOCIAL", "ACCIDENTE", "CLIMA", "OTRO"]


class ZonaMetricaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    codigo: str
    tipo_zona: str
    tramo: str | None
    sucursal_id: int | None
    gps_lat: float
    gps_lng: float
    num_envios: float
    tiempo_entrega_prom: float
    num_incidencias: float
    velocidad_prom: float
    inc_trafico: float
    inc_bloqueo: float
    inc_clima: float
    inc_social: float
    inc_accidente: float
    grupo: str | None


class EnvioHistoricoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tracking_ref: str | None
    sucursal_origen_id: int | None
    sucursal_destino_id: int | None
    peso: float
    distancia: float
    hora: int
    dia_semana: int
    tipo_servicio: str
    zona: str
    horas_estimadas: float | None
    horas_transito: float | None
    entregado_a_tiempo: bool | None
    riesgo: str
    fecha_registro: datetime | None


class ZonaDiaMetricaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    zona_metrica_id: int
    dia_semana: int
    gps_lat: float
    gps_lng: float
    num_envios: float
    tiempo_entrega_prom: float
    num_incidencias: float
    velocidad_prom: float
    inc_trafico: float
    inc_bloqueo: float
    inc_clima: float
    inc_social: float
    inc_accidente: float
    grupo: str | None


class IncidenteZonaCreate(BaseModel):
    tracking_ref: str | None = None
    tipo: str = Field(default="BLOQUEO")  # BLOQUEO|TRAFICO|SOCIAL|ACCIDENTE|CLIMA|OTRO
    descripcion: str | None = None
    gps_lat: float = Field(ge=-90, le=90)
    gps_lng: float = Field(ge=-180, le=180)
    dia_semana: int | None = Field(default=None, ge=0, le=6)  # si falta, se infiere de hoy
    hora: int | None = Field(default=None, ge=0, le=23)


class IncidenteZonaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tracking_ref: str | None
    tipo: str
    descripcion: str | None
    gps_lat: float
    gps_lng: float
    dia_semana: int
    hora: int | None
    zona_metrica_id: int | None
    asesor_id: str | None
    fecha: datetime


class Par(BaseModel):
    clave: str
    valor: float


class ReporteOperacion(BaseModel):
    total_envios: int
    distancia_prom_km: float
    tiempo_prom_h: float
    entregados_a_tiempo_pct: float
    por_zona: dict[str, int]
    por_servicio: dict[str, int]
    por_riesgo: dict[str, int]
    por_mes: dict[str, int]


class ReporteRankings(BaseModel):
    top_clientes: list[Par]
    top_servicios: list[Par]
    top_zonas: list[Par]
    top_rutas: list[Par]
    top_sucursales: list[Par]


class ResumenDataset(BaseModel):
    sucursales: int
    zonas: int
    envios_historicos: int
    incidentes: int
    zonas_por_grupo: dict[str, int]
    envios_por_riesgo: dict[str, int]
    envios_por_servicio: dict[str, int]
    incidentes_por_tipo: dict[str, int]
    incidentes_por_dia: dict[str, int]
