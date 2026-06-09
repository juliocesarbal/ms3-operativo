"""CU-14: calcula el hash del evento, lo registra en la cadena (best-effort) y
SIEMPRE persiste el registro local (tx_hash null si no se envio = pendiente)."""
import json
import logging

from sqlalchemy.orm import Session

from app.blockchain import web3_client
from app.core.database import SessionLocal
from app.models.operacion import EventoBlockchain

log = logging.getLogger("ms3.blockchain")


def _hash_payload(payload: dict) -> str:
    return web3_client.calcular_hash(json.dumps(payload, sort_keys=True, default=str))


# Sincrono: espera el minado (~5-25s) antes de devolver. Usado donde el link a
# Etherscan debe funcionar inmediatamente (CREACION_GUIA, ENTREGA_CONFIRMADA).
def registrar(db: Session, tracking: str | None, tipo_evento: str, payload: dict) -> EventoBlockchain:
    hash_hex = _hash_payload(payload)
    res = web3_client.registrar_evento(tracking, tipo_evento, hash_hex)

    evento = EventoBlockchain(
        tracking=tracking,
        tipo_evento=tipo_evento,
        hash_sha256=hash_hex,
        tx_hash=(res or {}).get("tx_hash"),
    )
    db.add(evento)
    db.commit()
    db.refresh(evento)
    return evento


# Persiste YA el evento (tx_hash=null = pendiente) y devuelve su id. La UI ve el
# evento al instante; el minado se hace despues en background (registrar_en_cadena).
def crear_pendiente(db: Session, tracking: str | None, tipo_evento: str, payload: dict) -> int:
    evento = EventoBlockchain(
        tracking=tracking,
        tipo_evento=tipo_evento,
        hash_sha256=_hash_payload(payload),
    )
    db.add(evento)
    db.commit()
    db.refresh(evento)
    return evento.id


# Background task: mina el tx en la cadena y rellena tx_hash en la fila pendiente.
# Abre su PROPIA sesion (la del request ya se cerro). Best-effort: si falla, la
# fila queda pendiente (tx_hash=null) y se puede reintentar.
def registrar_en_cadena(evento_id: int) -> None:
    db = SessionLocal()
    try:
        evento = db.get(EventoBlockchain, evento_id)
        if evento is None or evento.tx_hash:
            return
        res = web3_client.registrar_evento(evento.tracking, evento.tipo_evento, evento.hash_sha256)
        if res and res.get("tx_hash"):
            evento.tx_hash = res["tx_hash"]
            db.commit()
    except Exception as e:  # noqa: BLE001  best-effort
        log.warning("registrar_en_cadena fallo (evento %s): %s", evento_id, e)
    finally:
        db.close()
