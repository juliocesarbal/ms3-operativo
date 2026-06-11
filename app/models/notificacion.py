from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.core.database import Base
from app.models.encomienda import utcnow


# Notificacion in-app (centro de notificaciones). Dirigida a un usuario concreto
# (destinatario_id = sub de MS1) o por rol (destinatario_rol con destinatario_id NULL
# = broadcast a todos los de ese rol, p.ej. cualquier ADMIN).
class Notificacion(Base):
    __tablename__ = "notificacion"

    id = Column(Integer, primary_key=True)
    destinatario_id = Column(String, nullable=True, index=True)   # sub del usuario destino
    destinatario_rol = Column(String, nullable=True, index=True)  # ADMIN | ASESOR
    tipo = Column(String, nullable=False)  # INCIDENCIA | RUTA_ASIGNADA | RESPUESTA_ADMIN | ENTREGA | RETRASO | OTRO
    titulo = Column(String, nullable=False)
    cuerpo = Column(Text, nullable=True)
    data_json = Column(Text, nullable=True)  # payload extra (tracking, ruta_id, ...)
    leida = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
