import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.estados import Estado, puede_transicionar
from app.core.security import require_roles
from app.ml_models import ia_inference
from app.models.operacion import Incidencia
from app.schemas.ia import AnalizarFotoOut
from app.services import hf_client, notificacion_service, tracking_service

log = logging.getLogger("ms3.ia")
router = APIRouter(prefix="/api/ops/ia", tags=["ia"])


# CU-11: analizar foto de paquete con IA (ADMIN o ASESOR).
# Primario: Hugging Face Inference API (gratuita). Fallback: modelo local (TF).
# Si POSIBLE_DAÑO y se pasa tracking -> genera incidencia + pasa a CON_INCIDENCIA.
@router.post("/analizar-foto", response_model=AnalizarFotoOut)
def analizar_foto(
    file: UploadFile = File(...),
    tracking: str | None = Form(None),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("ADMIN", "ASESOR")),
):
    contenido = file.file.read()

    res: dict | None = None
    try:
        res = hf_client.analizar_imagen(contenido)
    except RuntimeError as e:
        log.warning("IA Hugging Face no disponible: %s", e)
        if settings.ia_fallback_local:
            try:
                res = ia_inference.analizar_imagen(contenido)
                res["fuente"] = "LOCAL"
            except FileNotFoundError as e2:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    f"IA no disponible: Hugging Face falló ({e}) y no hay modelo local ({e2})",
                )
        else:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"IA externa no disponible: {e}")

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

            # Avisa al admin del posible daño detectado por IA.
            notificacion_service.crear(
                db,
                tipo="INCIDENCIA",
                titulo=f"IA: posible daño en {tracking}",
                cuerpo=f"La IA detectó posible daño (confianza {res['confianza']}).",
                destinatario_rol="ADMIN",
                data={"tracking": tracking, "confianza": res["confianza"]},
            )

    return AnalizarFotoOut(**res, incidencia_creada=incidencia_creada, tracking=tracking)
