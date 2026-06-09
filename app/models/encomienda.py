from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Encomienda(Base):
    __tablename__ = "encomienda"

    id = Column(Integer, primary_key=True)
    tracking_code = Column(String, unique=True, index=True, nullable=False)

    # Referencia logica a MS1 + cache (evita llamada cruzada en cada lectura).
    cliente_id = Column(String, nullable=True)
    cliente_nombre = Column(String, nullable=True)
    cliente_direccion = Column(String, nullable=True)

    origen = Column(String, nullable=True)
    destino = Column(String, nullable=True)
    peso = Column(Float, nullable=True)
    servicio_ref = Column(String, nullable=True)
    zona_ref = Column(String, nullable=True)

    # Nodos logisticos (sucursal de salida y de llegada). Permiten calcular la
    # distancia real del envio y conectar la operacion con la red de sucursales.
    sucursal_origen_id = Column(Integer, ForeignKey("sucursal.id"), nullable=True, index=True)
    sucursal_destino_id = Column(Integer, ForeignKey("sucursal.id"), nullable=True, index=True)
    distancia = Column(Float, nullable=True)  # km (haversine origen->destino), se calcula al crear

    estado = Column(String, nullable=False, default="REGISTRADO", index=True)
    costo = Column(Float, nullable=True)
    riesgo_retraso = Column(String, nullable=True)  # BAJO|MEDIO|ALTO (fase ML)

    created_at = Column(DateTime(timezone=True), default=utcnow)

    historial = relationship(
        "EstadoHistorial",
        back_populates="encomienda",
        cascade="all, delete-orphan",
        order_by="EstadoHistorial.fecha",
    )
    sucursal_origen = relationship("Sucursal", foreign_keys=[sucursal_origen_id])
    sucursal_destino = relationship("Sucursal", foreign_keys=[sucursal_destino_id])


class EstadoHistorial(Base):
    __tablename__ = "estado_historial"

    id = Column(Integer, primary_key=True)
    encomienda_id = Column(Integer, ForeignKey("encomienda.id"), nullable=False, index=True)
    estado = Column(String, nullable=False)
    fecha = Column(DateTime(timezone=True), default=utcnow)
    ubicacion = Column(String, nullable=True)
    gps_lat = Column(Float, nullable=True)
    gps_lng = Column(Float, nullable=True)

    encomienda = relationship("Encomienda", back_populates="historial")
