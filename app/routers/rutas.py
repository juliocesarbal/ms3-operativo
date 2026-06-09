from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.schemas.operacion import RutaCreate, RutaOut
from app.services import ruta_service

router = APIRouter(prefix="/api/ops/rutas", tags=["rutas"])


# CU-08: asignar ruta a un asesor (solo ADMIN).
@router.post("", response_model=RutaOut, status_code=status.HTTP_201_CREATED)
def crear(
    data: RutaCreate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("ADMIN")),
):
    try:
        return ruta_service.crear_ruta(db, data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("", response_model=list[RutaOut])
def listar(
    asesor_id: str | None = None,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    return ruta_service.listar(db, asesor_id)


@router.get("/{ruta_id}", response_model=RutaOut)
def detalle(
    ruta_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    ruta = ruta_service.obtener(db, ruta_id)
    if not ruta:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ruta no encontrada")
    return ruta
