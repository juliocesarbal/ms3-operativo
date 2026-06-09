"""Tablas de datos para los modelos de Machine Learning del MS3.

- ZonaMetrica   -> dataset del ML NO supervisado (K-Means, CU-13).
- EnvioHistorico-> dataset del ML supervisado (RandomForest, CU-12).
- Prediccion    -> resultados de prediccion persistidos (spec: "resultados de prediccion").

Las dos primeras se llenan con datos sinteticos realistas (ml_training/seed_dataset.py)
y son la fuente de entrenamiento de los modelos. Ya NO se generan en memoria al vuelo.
"""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.encomienda import utcnow


# ---- CU-13 (ML no supervisado): metricas agregadas por zona de entrega ----
# Cada fila es una zona real (sector de una ciudad/sucursal) con su comportamiento
# operativo. K-Means agrupa estas zonas; el grupo resultante se persiste en `grupo`.
class ZonaMetrica(Base):
    __tablename__ = "zona_metrica"

    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False)         # "Santa Cruz - Norte" | "Ruta SCZ-Cbba · tramo 2"
    codigo = Column(String, nullable=False)         # NORTE|SUR|ESTE|OESTE|CENTRO | TRAMO
    # URBANA = sector de ciudad; CARRETERA = punto en una ruta interurbana usada para el traslado.
    tipo_zona = Column(String, nullable=False, default="URBANA")
    tramo = Column(String, nullable=True)           # corredor (solo CARRETERA): "Santa Cruz ↔ Cochabamba"
    sucursal_id = Column(Integer, ForeignKey("sucursal.id"), nullable=True, index=True)

    gps_lat = Column(Float, nullable=False)
    gps_lng = Column(Float, nullable=False)
    num_envios = Column(Float, nullable=False, default=0)            # tráfico de envíos que pasa por la zona
    tiempo_entrega_prom = Column(Float, nullable=False, default=0)   # horas
    num_incidencias = Column(Float, nullable=False, default=0)       # total de incidencias
    velocidad_prom = Column(Float, nullable=False, default=0)        # km/h (baja = congestión)

    # Desglose de incidencias por tipo (más información para el clustering de zonas).
    inc_trafico = Column(Float, nullable=False, default=0)
    inc_bloqueo = Column(Float, nullable=False, default=0)
    inc_clima = Column(Float, nullable=False, default=0)
    inc_social = Column(Float, nullable=False, default=0)
    inc_accidente = Column(Float, nullable=False, default=0)

    # Lo asigna K-Means: ALTA_DEMANDA|RETRASOS_FRECUENTES|BAJA_DEMANDA. Null = sin clasificar.
    grupo = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    sucursal = relationship("Sucursal")


# ---- CU-12 (ML supervisado): historico de envios ya entregados ----
# Cada fila es un envio pasado con el resultado conocido (label `riesgo`). Es la
# tabla de entrenamiento del RandomForest. Features del modelo: peso, distancia,
# hora, dia_semana, tipo_servicio, zona.
class EnvioHistorico(Base):
    __tablename__ = "envio_historico"

    id = Column(Integer, primary_key=True)
    tracking_ref = Column(String, nullable=True, index=True)
    cliente_nombre = Column(String, nullable=True, index=True)  # denormalizado (BI: top clientes)

    sucursal_origen_id = Column(Integer, ForeignKey("sucursal.id"), nullable=True, index=True)
    sucursal_destino_id = Column(Integer, ForeignKey("sucursal.id"), nullable=True, index=True)
    zona_metrica_id = Column(Integer, ForeignKey("zona_metrica.id"), nullable=True, index=True)

    # --- Features del modelo supervisado ---
    peso = Column(Float, nullable=False)
    distancia = Column(Float, nullable=False)        # km (haversine origen->destino)
    hora = Column(Integer, nullable=False)           # 0-23 (hora de registro)
    dia_semana = Column(Integer, nullable=False)     # 0=Lun ... 6=Dom
    tipo_servicio = Column(String, nullable=False)   # DOCUMENTO|PAQUETE_NORMAL|CARGA_PESADA|EXPRESS
    zona = Column(String, nullable=False)            # NORTE|SUR|ESTE|OESTE|CENTRO

    # --- Contexto realista del envio (no son features, dan trazabilidad) ---
    fecha_registro = Column(DateTime(timezone=True), nullable=True)
    fecha_entrega = Column(DateTime(timezone=True), nullable=True)
    horas_transito = Column(Float, nullable=True)
    horas_estimadas = Column(Float, nullable=True)
    entregado_a_tiempo = Column(Boolean, nullable=True)

    # --- Label (target) ---
    riesgo = Column(String, nullable=False, index=True)  # BAJO|MEDIO|ALTO
    created_at = Column(DateTime(timezone=True), default=utcnow)

    sucursal_origen = relationship("Sucursal", foreign_keys=[sucursal_origen_id])
    sucursal_destino = relationship("Sucursal", foreign_keys=[sucursal_destino_id])
    zona_metrica = relationship("ZonaMetrica")


# ---- CU-13 (refuerzo): metricas por zona Y dia de la semana ----
# El comportamiento de una zona cambia segun el dia (ej: lunes con eventos sociales
# => trafico). K-Means agrupa estos puntos (zona x dia) para descubrir patrones
# temporales. Cada fila es una zona en un dia concreto.
class ZonaDiaMetrica(Base):
    __tablename__ = "zona_dia_metrica"

    id = Column(Integer, primary_key=True)
    zona_metrica_id = Column(Integer, ForeignKey("zona_metrica.id"), nullable=False, index=True)
    dia_semana = Column(Integer, nullable=False)   # 0=Lun ... 6=Dom

    gps_lat = Column(Float, nullable=False)
    gps_lng = Column(Float, nullable=False)
    num_envios = Column(Float, nullable=False, default=0)
    tiempo_entrega_prom = Column(Float, nullable=False, default=0)
    num_incidencias = Column(Float, nullable=False, default=0)
    velocidad_prom = Column(Float, nullable=False, default=0)

    # Desglose por tipo (mismas columnas que zona_metrica, pero por día — feature del K-Means).
    inc_trafico = Column(Float, nullable=False, default=0)
    inc_bloqueo = Column(Float, nullable=False, default=0)
    inc_clima = Column(Float, nullable=False, default=0)
    inc_social = Column(Float, nullable=False, default=0)
    inc_accidente = Column(Float, nullable=False, default=0)

    grupo = Column(String, nullable=True)  # K-Means: ALTA_DEMANDA|RETRASOS_FRECUENTES|BAJA_DEMANDA
    created_at = Column(DateTime(timezone=True), default=utcnow)

    zona = relationship("ZonaMetrica")


# ---- Incidentes de ruta/zona reportados por asesores en campo (alimenta K-Means) ----
# Ej: "en camino La Paz->Santa Cruz hay un bloqueo". El asesor sube tracking, obs,
# GPS y dia. Se resuelve la zona mas cercana y se suma a su metrica del dia.
class IncidenteZona(Base):
    __tablename__ = "incidente_zona"

    id = Column(Integer, primary_key=True)
    tracking_ref = Column(String, nullable=True, index=True)   # numero de pedido
    tipo = Column(String, nullable=False)                      # BLOQUEO|TRAFICO|SOCIAL|ACCIDENTE|CLIMA|OTRO
    descripcion = Column(String, nullable=True)                # observacion del asesor

    gps_lat = Column(Float, nullable=False)
    gps_lng = Column(Float, nullable=False)
    dia_semana = Column(Integer, nullable=False)               # 0=Lun ... 6=Dom
    hora = Column(Integer, nullable=True)

    zona_metrica_id = Column(Integer, ForeignKey("zona_metrica.id"), nullable=True, index=True)
    asesor_id = Column(String, nullable=True)                  # ref MS1 (quien reporta)
    fecha = Column(DateTime(timezone=True), default=utcnow)

    zona = relationship("ZonaMetrica")


# ---- Distancias de carretera precalculadas (OSRM) entre sucursales ----
# El modelo de retraso se entrena con distancia de CARRETERA (no línea recta).
# Para que la inferencia use la misma métrica sin llamar a OSRM en cada request,
# las distancias sucursal->sucursal se precalculan en el seed y se guardan aquí.
class RutaCache(Base):
    __tablename__ = "ruta_cache"

    id = Column(Integer, primary_key=True)
    sucursal_origen_id = Column(Integer, ForeignKey("sucursal.id"), nullable=False, index=True)
    sucursal_destino_id = Column(Integer, ForeignKey("sucursal.id"), nullable=False, index=True)
    distancia_km = Column(Float, nullable=False)     # carretera (OSRM) o haversine*factor
    duracion_min = Column(Float, nullable=True)      # estimación OSRM (si disponible)
    fuente = Column(String, nullable=True)           # OSRM | HAVERSINE
    created_at = Column(DateTime(timezone=True), default=utcnow)

    sucursal_origen = relationship("Sucursal", foreign_keys=[sucursal_origen_id])
    sucursal_destino = relationship("Sucursal", foreign_keys=[sucursal_destino_id])


# ---- Resultados de prediccion persistidos ----
class Prediccion(Base):
    __tablename__ = "prediccion"

    id = Column(Integer, primary_key=True)
    encomienda_id = Column(Integer, ForeignKey("encomienda.id"), nullable=True, index=True)
    tipo = Column(String, nullable=False, default="RETRASO")  # RETRASO
    riesgo = Column(String, nullable=False)                   # BAJO|MEDIO|ALTO
    probabilidad = Column(Float, nullable=True)               # confianza de la clase predicha
    modelo = Column(String, nullable=True)                    # "RandomForest"
    fecha = Column(DateTime(timezone=True), default=utcnow)

    encomienda = relationship("Encomienda")
