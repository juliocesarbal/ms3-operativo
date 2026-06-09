import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.estados import Estado, puede_transicionar
from app.core.security import require_roles
from app.ml_models import ia_inference
from app.models.operacion import Incidencia
from app.schemas.ia import AnalizarFotoOut
from app.services import tracking_service

log = logging.getLogger("ms3.ia")
router = APIRouter(prefix="/api/ops/ia", tags=["ia"])


# CU-11: analizar foto de paquete con IA (ADMIN o ASESOR).
# Si POSIBLE_DAÑO y se pasa tracking -> genera incidencia + pasa a CON_INCIDENCIA.
@router.post("/analizar-foto", response_model=AnalizarFotoOut)
def analizar_foto(
    file: UploadFile = File(...),
    tracking: str | None = Form(None),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("ADMIN", "ASESOR")),
):
    contenido = file.file.read()
    try:
        res = ia_inference.analizar_imagen(contenido)
    except FileNotFoundError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    incidencia_creada = False
    if res["clase"] == "POSIBLE_DAÑO" and tracking:
        enc = tracking_service.obtener_por_tracking(db, tracking)
        if enc:
            db.add(
                Incidencia(
                    encomienda_id=enc.id,
                    tipo="DANIO",
                    descripcion=f"IA: posible daño (confianza {res['confianza']})",
                )
            )
            if puede_transicionar(enc.estado, Estado.CON_INCIDENCIA.value):
                tracking_service.transicionar(
                    db, enc, Estado.CON_INCIDENCIA.value,
                    ubicacion="IA: posible daño", commit=False,
                )
            db.commit()
            incidencia_creada = True
            # TODO Fase 4: disparar webhook n8n por incidencia.

    return AnalizarFotoOut(**res, incidencia_creada=incidencia_creada, tracking=tracking)
