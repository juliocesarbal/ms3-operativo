from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from app.core.database import Base
from app.models.encomienda import utcnow


# Sucursal / nodo logistico del courier (oficina fisica en una ciudad).
# Es el punto de origen/destino de las encomiendas y de las rutas, y la
# referencia geografica para calcular distancias (haversine entre sucursales).
class Sucursal(Base):
    __tablename__ = "sucursal"

    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False)         # "Santa Cruz - Central"
    departamento = Column(String, nullable=False)   # "Santa Cruz", "La Paz", ...
    ciudad = Column(String, nullable=False)
    direccion = Column(String, nullable=True)
    gps_lat = Column(Float, nullable=False)
    gps_lng = Column(Float, nullable=False)
    activa = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
