from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_token, get_current_user, require_roles
from app.schemas.encomienda import EncomiendaCreate, EncomiendaOut
from app.services import blockchain_service, ms1_client, tracking_service

router = APIRouter(prefix="/api/ops/encomiendas", tags=["encomiendas"])


# CU-05: registrar encomienda (solo ADMIN).
@router.post("", response_model=EncomiendaOut, status_code=status.HTTP_201_CREATED)
def crear(
    data: EncomiendaCreate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("ADMIN")),
    token: str = Depends(get_current_token),
):
    # Cachea nombre/direccion del cliente desde MS1 si solo vino el id (best-effort).
    if data.cliente_id and not data.cliente_nombre:
        cliente = ms1_client.obtener_cliente(data.cliente_id, token)
        if cliente:
            data.cliente_nombre = cliente.get("nombre")
            data.cliente_direccion = cliente.get("direccion")

    enc = tracking_service.crear_encomienda(db, data)

    # CU-05 (parte MS1): registra el ingreso asociado al servicio (best-effort).
    ms1_client.registrar_ingreso(enc.tracking_code, enc.servicio_ref, enc.costo, token)

    # CU-14: hash del evento CREACION_GUIA en blockchain (best-effort + registro local).
    blockchain_service.registrar(
        db,
        enc.tracking_code,
        "CREACION_GUIA",
        {
            "tracking": enc.tracking_code,
            "cliente_id": enc.cliente_id,
            "origen": enc.origen,
            "destino": enc.destino,
            "estado": enc.estado,
            "created_at": enc.created_at,
        },
    )
    return enc


# Lista todas (filtros opcionales por estado / cliente).
@router.get("", response_model=list[EncomiendaOut])
def listar(
    estado: str | None = None,
    cliente_id: str | None = None,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    return tracking_service.listar(db, estado, cliente_id)


@router.get("/{tracking}", response_model=EncomiendaOut)
def detalle(
    tracking: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    enc = tracking_service.obtener_por_tracking(db, tracking)
    if not enc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Encomienda no encontrada")
    return enc
