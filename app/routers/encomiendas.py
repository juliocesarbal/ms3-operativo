import io

import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
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


# QR de la guia: PNG que codifica el tracking_code. Se genera al vuelo (el QR es el
# tracking, asi el mismo codigo sirve para escaneo-qr y para el detalle del envio).
# Descargable/imprimible desde la web del admin para pegar en el paquete.
@router.get("/{tracking}/qr")
def qr(
    tracking: str,
    box_size: int = 10,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    enc = tracking_service.obtener_por_tracking(db, tracking)
    if not enc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Encomienda no encontrada")

    qr_img = qrcode.QRCode(box_size=max(2, min(box_size, 20)), border=2)
    qr_img.add_data(enc.tracking_code)
    qr_img.make(fit=True)
    img = qr_img.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="QR-{enc.tracking_code}.png"'},
    )
