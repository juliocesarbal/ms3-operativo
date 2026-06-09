from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.sucursal import Sucursal
from app.schemas.sucursal import SucursalCreate, SucursalOut

router = APIRouter(prefix="/api/ops/sucursales", tags=["sucursales"])


# Lista las sucursales (red logistica). Cualquier usuario autenticado.
@router.get("", response_model=list[SucursalOut])
def listar(
    solo_activas: bool = False,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    q = db.query(Sucursal)
    if solo_activas:
        q = q.filter(Sucursal.activa.is_(True))
    return q.order_by(Sucursal.departamento, Sucursal.nombre).all()


# Crea una sucursal (solo ADMIN).
@router.post("", response_model=SucursalOut, status_code=status.HTTP_201_CREATED)
def crear(
    data: SucursalCreate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("ADMIN")),
):
    suc = Sucursal(**data.model_dump())
    db.add(suc)
    db.commit()
    db.refresh(suc)
    return suc
