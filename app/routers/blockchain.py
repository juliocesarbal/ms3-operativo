from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.operacion import EventoBlockchain
from app.schemas.blockchain import EventoBlockchainOut, RegistrarEventoIn
from app.services import blockchain_service

router = APIRouter(prefix="/api/ops/blockchain", tags=["blockchain"])


# CU-14: registrar hash de evento critico (ADMIN / sistema).
@router.post("/evento", response_model=EventoBlockchainOut, status_code=status.HTTP_201_CREATED)
def registrar_evento(
    data: RegistrarEventoIn,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("ADMIN")),
):
    return blockchain_service.registrar(db, data.tracking, data.tipo_evento, data.datos)


@router.get("/eventos", response_model=list[EventoBlockchainOut])
def listar(
    tracking: str | None = None,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    q = db.query(EventoBlockchain)
    if tracking:
        q = q.filter_by(tracking=tracking)
    return q.order_by(EventoBlockchain.fecha.desc()).all()
