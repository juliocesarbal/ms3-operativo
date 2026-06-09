import logging

import httpx

from app.core.config import settings

log = logging.getLogger("ms3.ms2_client")


# CU-10: sube la foto de evidencia de entrega al MS2 (S3 + DynamoDB).
# Reenvia el JWT del asesor. Best-effort: si MS2 falla, devuelve None.
def subir_evidencia(
    contenido: bytes,
    filename: str,
    content_type: str | None,
    envio_id: str,
    token: str,
) -> dict | None:
    if not settings.ms2_url:
        return None
    files = {"file": (filename, contenido, content_type or "application/octet-stream")}
    data = {"envioId": envio_id, "tipo": "EVIDENCIA"}
    try:
        r = httpx.post(
            f"{settings.ms2_url}/documentos",
            files=files,
            data=data,
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        log.warning("MS2 subir_evidencia fallo (best-effort): %s", e)
        return None
