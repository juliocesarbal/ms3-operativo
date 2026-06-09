from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.encomienda import utcnow

# N:M ruta <-> encomienda
ruta_encomienda = Table(
    "ruta_encomienda",
    Base.metadata,
    Column("ruta_id", Integer, ForeignKey("ruta.id"), primary_key=True),
    Column("encomienda_id", Integer, ForeignKey("encomienda.id"), primary_key=True),
)


class Ruta(Base):
    __tablename__ = "ruta"

    id = Column(Integer, primary_key=True)
    asesor_id = Column(String, nullable=False, index=True)  # ref MS1
    zona_ref = Column(String, nullable=True)
    sucursal_id = Column(Integer, ForeignKey("sucursal.id"), nullable=True, index=True)  # sucursal de salida
    fecha = Column(String, nullable=True)  # fecha planificada (ISO date / texto)
    estado = Column(String, nullable=False, default="PENDIENTE")  # PENDIENTE|EN_CURSO|COMPLETADA
    created_at = Column(DateTime(timezone=True), default=utcnow)

    encomiendas = relationship(
        "Encomienda", secondary=ruta_encomienda, lazy="selectin"
    )
    sucursal = relationship("Sucursal")


class Entrega(Base):
    __tablename__ = "entrega"

    id = Column(Integer, primary_key=True)
    encomienda_id = Column(Integer, ForeignKey("encomienda.id"), nullable=False, index=True)
    asesor_id = Column(String, nullable=True)
    foto_url = Column(String, nullable=True)  # s3Key/docId devuelto por MS2
    gps_lat = Column(Float, nullable=True)
    gps_lng = Column(Float, nullable=True)
    qr_validado = Column(Boolean, default=False)
    fecha = Column(DateTime(timezone=True), default=utcnow)

    encomienda = relationship("Encomienda")


class Incidencia(Base):
    __tablename__ = "incidencia"

    id = Column(Integer, primary_key=True)
    encomienda_id = Column(Integer, ForeignKey("encomienda.id"), nullable=True, index=True)
    tipo = Column(String, nullable=False)  # DANIO | RETRASO | NO_ENTREGA
    descripcion = Column(String, nullable=True)
    foto_url = Column(String, nullable=True)
    fecha = Column(DateTime(timezone=True), default=utcnow)

    encomienda = relationship("Encomienda")


class EventoBlockchain(Base):
    __tablename__ = "evento_blockchain"

    id = Column(Integer, primary_key=True)
    tracking = Column(String, index=True, nullable=True)
    # CREACION_GUIA | CAMBIO_ESTADO | ENTREGA_CONFIRMADA | HASH_DOCUMENTO
    tipo_evento = Column(String, nullable=False)
    hash_sha256 = Column(String, nullable=False)
    tx_hash = Column(String, nullable=True)  # null = no enviado a la cadena (pendiente)
    fecha = Column(DateTime(timezone=True), default=utcnow)
