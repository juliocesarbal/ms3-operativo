"""CU-14: calcula el hash del evento, lo registra en la cadena (best-effort) y
SIEMPRE persiste el registro local (tx_hash null si no se envio = pendiente)."""
import json

from sqlalchemy.orm import Session

from app.blockchain import web3_client
from app.models.operacion import EventoBlockchain


def registrar(db: Session, tracking: str | None, tipo_evento: str, payload: dict) -> EventoBlockchain:
    hash_hex = web3_client.calcular_hash(json.dumps(payload, sort_keys=True, default=str))
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
