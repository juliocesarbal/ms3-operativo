from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.schemas.encomienda import CambiarEstado, EncomiendaOut, TrackingOut
from app.services import tracking_service
from app.services.tracking_service import TransicionInvalida

router = APIRouter(prefix="/api/ops/encomiendas", tags=["tracking"])


# CU-07: historial de estados (linea de tiempo) de un envio.
@router.get("/{tracking}/tracking", response_model=TrackingOut)
def historial(
    tracking: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    enc = tracking_service.obtener_por_tracking(db, tracking)
    if not enc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Encomienda no encontrada")
    return enc


# Avanza el estado del envio (valida el flujo). Solo ADMIN por ahora;
# en fases siguientes lo disparan rutas/entregas (ASESOR).
@router.post("/{tracking}/estado", response_model=EncomiendaOut)
def cambiar_estado(
    tracking: str,
    cambio: CambiarEstado,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("ADMIN")),
):
    enc = tracking_service.obtener_por_tracking(db, tracking)
    if not enc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Encomienda no encontrada")
    try:
        # CU-14: cada cambio de estado queda registrado en blockchain (background).
        return tracking_service.cambiar_estado(db, enc, cambio, bg=bg)
    except TransicionInvalida as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
