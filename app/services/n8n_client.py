"""CU-15: dispara webhooks de n8n para automatizar avisos (email + Telegram).

Best-effort SIEMPRE: si la URL del webhook esta vacia o n8n no responde, se
registra un warning y el flujo de negocio continua sin romperse. Nunca lanza.

Eventos soportados (cada uno tiene su propio webhook en n8n):
  - retraso     -> alerta de envio retrasado (supervisor + cliente + Telegram)
  - bienvenida  -> aviso al registrar una encomienda (tracking + seguimiento)
  - incidente   -> alerta de incidente/daño detectado (admin)

Las URLs se configuran por .env. Si una falta, ese evento simplemente no se
dispara (no es error). Mismo host de n8n, distinto path por evento.
"""
import logging

import httpx

from app.core.config import settings

log = logging.getLogger("ms3.n8n")


def _disparar(url: str, evento: str, payload: dict) -> bool:
    """POST best-effort a un webhook de n8n. Nunca lanza excepcion."""
    if not url:
        return False
    try:
        r = httpx.post(url, json=payload, timeout=8)
        r.raise_for_status()
        log.info("n8n: webhook '%s' disparado (%s)", evento, payload.get("tracking", ""))
        return True
    except httpx.HTTPError as e:
        log.warning("n8n: webhook '%s' fallo (best-effort): %s", evento, e)
        return False
    except Exception as e:  # noqa: BLE001 — jamas romper el flujo de negocio por n8n
        log.warning("n8n: webhook '%s' error inesperado (best-effort): %s", evento, e)
        return False


# CU-15: aviso de retraso (se mantiene la firma original para no romper lo existente).
def disparar_retraso(tracking: str, datos: dict) -> bool:
    return _disparar(
        settings.n8n_webhook_url, "retraso", {"tracking": tracking, **datos}
    )


# Aviso de bienvenida al registrar una encomienda (CU-05).
def disparar_bienvenida(tracking: str, datos: dict) -> bool:
    return _disparar(
        settings.n8n_bienvenida_url, "bienvenida", {"tracking": tracking, **datos}
    )


# Alerta de incidente / posible daño detectado (campo o IA).
def disparar_incidente(tracking: str | None, datos: dict) -> bool:
    return _disparar(
        settings.n8n_incidente_url, "incidente", {"tracking": tracking, **datos}
    )
