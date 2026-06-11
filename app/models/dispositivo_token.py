from sqlalchemy import Column, DateTime, Integer, String

from app.core.database import Base
from app.models.encomienda import utcnow


# Token FCM de un dispositivo, para enviar push real al celular del usuario.
# Se asocia al sub de MS1 (usuario_id) y al rol, para poder dirigir el push tanto
# a un usuario concreto como a un rol (broadcast, p.ej. cualquier ADMIN).
class DispositivoToken(Base):
    __tablename__ = "dispositivo_token"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(String, nullable=False, index=True)  # sub del usuario
    rol = Column(String, nullable=True, index=True)          # ADMIN | ASESOR
    token = Column(String, nullable=False, unique=True, index=True)  # token FCM
    plataforma = Column(String, nullable=True)               # android | ios
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
