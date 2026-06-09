import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_token, require_roles
from app.schemas.operacion import EntregaOut, EscaneoQR, EscaneoResult
from app.services import blockchain_service, entrega_service, ms2_client, tracking_service
from app.services.tracking_service import TransicionInvalida

log = logging.getLogger("ms3.entregas")
router = APIRouter(prefix="/api/ops", tags=["entregas"])


# CU-09: escanear QR (solo ASESOR).
@router.post("/escaneo-qr", response_model=EscaneoResult)
def escaneo_qr(
    data: EscaneoQR,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("ASESOR")),
):
    asesor_id = str(user.get("sub"))
    return entrega_service.escanear_qr(db, data.tracking_code, asesor_id)


# CU-10: confirmar entrega con foto (multipart) + GPS (solo ASESOR).
@router.post("/entregas", response_model=EntregaOut, status_code=status.HTTP_201_CREATED)
def confirmar_entrega(
    file: UploadFile = File(...),
    tracking: str = Form(...),
    gps_lat: float | None = Form(None),
    gps_lng: float | None = Form(None),
    qr_validado: bool = Form(False),
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("ASESOR")),
    token: str = Depends(get_current_token),
):
    enc = tracking_service.obtener_por_tracking(db, tracking)
    if not enc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Encomienda no encontrada")

    # Foto -> MS2 (S3 + DynamoDB). Best-effort: si MS2 falla, se registra la entrega sin foto.
    contenido = file.file.read()
    res = ms2_client.subir_evidencia(contenido, file.filename, file.content_type, tracking, token)
    foto_url = (res or {}).get("s3Key") or (res or {}).get("docId")
    if res is None:
        log.warning("Entrega %s: foto no almacenada en MS2 (continua sin foto)", tracking)

    asesor_id = str(user.get("sub"))
    try:
        entrega = entrega_service.confirmar_entrega(
            db, enc, asesor_id, foto_url, gps_lat, gps_lng, qr_validado
        )
    except TransicionInvalida as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))

    # CU-14: hash del evento ENTREGA_CONFIRMADA en blockchain (best-effort + local).
    blockchain_service.registrar(
        db,
        tracking,
        "ENTREGA_CONFIRMADA",
        {
            "tracking": tracking,
            "asesor_id": asesor_id,
            "gps_lat": gps_lat,
            "gps_lng": gps_lng,
            "foto_url": foto_url,
            "fecha": entrega.fecha,
        },
    )
    return entrega
