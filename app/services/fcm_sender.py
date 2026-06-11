"""Envio de push real via Firebase Cloud Messaging (FCM).

Es 100% best-effort: si no hay credenciales (`FCM_CREDENTIALS` vacio o archivo
inexistente) o falla la libreria `firebase_admin`, todas las funciones son no-op
y solo registran un log. El centro de notificaciones en BD funciona sin esto.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import settings

log = logging.getLogger("ms3.fcm")

# Estado del init perezoso: None = aun no intentado, True/False = resultado.
_initialized: bool | None = None
_messaging = None  # modulo firebase_admin.messaging cuando esta listo


def _ensure_init() -> bool:
    """Inicializa el SDK de Firebase Admin una sola vez. Devuelve si esta listo."""
    global _initialized, _messaging
    if _initialized is not None:
        return _initialized

    cred_path = settings.fcm_credentials.strip()
    if not cred_path:
        log.info("FCM deshabilitado (FCM_CREDENTIALS vacio). Push = no-op.")
        _initialized = False
        return False

    p = Path(cred_path)
    if not p.exists():
        log.warning("FCM: credenciales no encontradas en '%s'. Push = no-op.", cred_path)
        _initialized = False
        return False

    try:
        import firebase_admin
        from firebase_admin import credentials, messaging

        if not firebase_admin._apps:  # evita doble init con --reload
            cred = credentials.Certificate(str(p))
            firebase_admin.initialize_app(cred)
        _messaging = messaging
        _initialized = True
        log.info("FCM inicializado con '%s'.", cred_path)
    except Exception as e:  # libreria ausente o credenciales invalidas
        log.warning("FCM: no se pudo inicializar (%s). Push = no-op.", e)
        _initialized = False

    return _initialized


def enviar(
    tokens: list[str],
    *,
    titulo: str,
    cuerpo: str | None = None,
    data: dict | None = None,
) -> int:
    """Envia un push a una lista de tokens. Devuelve cuantos se enviaron OK.

    No lanza excepciones: cualquier fallo se loguea y se ignora (best-effort).
    """
    tokens = [t for t in (tokens or []) if t]
    if not tokens:
        return 0
    if not _ensure_init():
        return 0

    msg = _messaging
    # data debe ser dict[str, str] en FCM.
    data_str = {k: str(v) for k, v in (data or {}).items()}

    enviados = 0
    try:
        message = msg.MulticastMessage(
            tokens=tokens,
            notification=msg.Notification(title=titulo, body=cuerpo or ""),
            data=data_str,
            android=msg.AndroidConfig(priority="high"),
        )
        resp = msg.send_each_for_multicast(message)
        enviados = resp.success_count
        if resp.failure_count:
            log.info("FCM: %s enviados, %s fallidos.", resp.success_count, resp.failure_count)
    except Exception as e:
        log.warning("FCM: error al enviar push (%s).", e)
    return enviados
