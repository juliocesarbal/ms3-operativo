"""Chatbot BI (CU-16): endpoints del asistente de reportes por lenguaje natural.

POST /api/ops/bi/chat       -> interpreta el prompt con Claude, consulta los datos
                               y genera el archivo; devuelve un resumen + reporte_id.
GET  /api/ops/bi/descargar/{id} -> descarga el archivo generado (PDF/Excel/CSV).

El archivo se guarda en memoria con un TTL corto (suficiente para descargarlo
tras la respuesta del chat). Solo ADMIN (mismo criterio que las hojas BI).
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_token, require_roles
from app.services import bi_chat_service, bi_data, bi_export

log = logging.getLogger("ms3.bi")
router = APIRouter(prefix="/api/ops/bi", tags=["bi-chat"])

# Store temporal de archivos generados: id -> (bytes, media_type, nombre, expira_ts).
_STORE: dict[str, tuple[bytes, str, str, float]] = {}
_TTL = 600  # 10 minutos


def _purgar():
    ahora = time.time()
    for k in [k for k, v in _STORE.items() if v[3] < ahora]:
        _STORE.pop(k, None)


class ChatIn(BaseModel):
    prompt: str = Field(min_length=2, max_length=1000)


class ChatOut(BaseModel):
    mensaje: str
    reporte_id: str
    tipo: str
    formato: str
    nombre_archivo: str
    descarga_url: str
    parametros: dict
    aviso: str | None = None


@router.post("/chat", response_model=ChatOut)
def chat(
    data: ChatIn = Body(...),
    db: Session = Depends(get_db),
    token: str = Depends(get_current_token),
    _user: dict = Depends(require_roles("ADMIN")),
):
    _purgar()
    # 1) Claude interpreta el pedido -> parámetros del reporte.
    try:
        params = bi_chat_service.interpretar(data.prompt)
    except bi_chat_service.ChatNoConfigurado:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Chatbot BI no configurado: falta CLAUDE_API_KEY en el servidor (.env del MS3).",
        )
    except Exception as e:  # noqa: BLE001 — errores del SDK / API de Claude
        log.exception("Error llamando a Claude")
        nombre = type(e).__name__
        if "Connection" in nombre or "Timeout" in nombre or "APIConnection" in nombre:
            msg = "No se pudo conectar con el asistente (red/API). Intenta de nuevo en unos segundos."
        else:
            msg = f"Error del asistente: {e}"
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, msg)

    # 2) Backend ejecuta la consulta real (no se expone la BD al modelo).
    reporte = bi_data.construir_reporte(db, params, token)

    # 3) Generar el archivo en el formato pedido.
    contenido, media, nombre = bi_export.exportar(reporte, params.get("formato", "PDF"))

    rid = uuid.uuid4().hex
    _STORE[rid] = (contenido, media, nombre, time.time() + _TTL)

    return ChatOut(
        mensaje=bi_chat_service.resumen_humano(params, reporte),
        reporte_id=rid,
        tipo=params.get("tipo", "OPERACION"),
        formato=params.get("formato", "PDF"),
        nombre_archivo=nombre,
        descarga_url=f"/api/ops/bi/descargar/{rid}",
        parametros=params,
        aviso=reporte.get("aviso"),
    )


@router.get("/descargar/{reporte_id}")
def descargar(
    reporte_id: str,
    _user: dict = Depends(require_roles("ADMIN")),
):
    _purgar()
    item = _STORE.get(reporte_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reporte no encontrado o expirado.")
    contenido, media, nombre, _ = item
    return Response(
        content=contenido,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
