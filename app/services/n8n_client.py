"""CU-15: dispara el webhook de n8n cuando se detecta un retraso. Best-effort:
si N8N_WEBHOOK_URL esta vacio o n8n no responde, no rompe el flujo."""
import logging

import httpx

from app.core.config import settings

log = logging.getLogger("ms3.n8n")


def disparar_retraso(tracking: str, datos: dict) -> bool:
    if not settings.n8n_webhook_url:
        return False
    payload = {"tracking": tracking, **datos}
    try:
        r = httpx.post(settings.n8n_webhook_url, json=payload, timeout=8)
        r.raise_for_status()
        log.info("n8n: webhook de retraso disparado para %s", tracking)
        return True
    except httpx.HTTPError as e:
        log.warning("n8n: webhook fallo (best-effort): %s", e)
        return False
