"""Centro de notificaciones in-app (BD). Otros services llaman a `crear(...)`
cuando ocurre un evento (incidencia, ruta asignada, entrega, respuesta admin).

Las notificaciones se dirigen a un usuario (destinatario_id = sub de MS1) o a un
rol completo (destinatario_rol con destinatario_id NULL = todos los de ese rol).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.dispositivo_token import DispositivoToken
from app.models.notificacion import Notificacion
from app.services import fcm_sender

log = logging.getLogger("ms3.notif")


def registrar_token(db: Session, user: dict, token: str, plataforma: str | None = None) -> None:
    """Guarda/actualiza el token FCM de un dispositivo para el usuario actual.

    El token es unico: si ya existe (mismo dispositivo), solo reasigna el dueño/rol.
    """
    sub = str(user.get("sub"))
    rol = user.get("rol")
    existente = db.query(DispositivoToken).filter(DispositivoToken.token == token).first()
    if existente:
        existente.usuario_id = sub
        existente.rol = rol
        if plataforma:
            existente.plataforma = plataforma
    else:
        db.add(DispositivoToken(usuario_id=sub, rol=rol, token=token, plataforma=plataforma))
    db.commit()


def _tokens_destino(db: Session, destinatario_id: str | None, destinatario_rol: str | None) -> list[str]:
    """Tokens FCM de quien debe recibir el push: por usuario concreto o por rol."""
    q = db.query(DispositivoToken.token)
    if destinatario_id is not None:
        q = q.filter(DispositivoToken.usuario_id == str(destinatario_id))
    elif destinatario_rol is not None:
        q = q.filter(DispositivoToken.rol == destinatario_rol)
    else:
        return []
    return [t[0] for t in q.all()]


def crear(
    db: Session,
    *,
    tipo: str,
    titulo: str,
    cuerpo: str | None = None,
    destinatario_id: str | int | None = None,
    destinatario_rol: str | None = None,
    data: dict | None = None,
    commit: bool = True,
) -> Notificacion:
    notif = Notificacion(
        destinatario_id=str(destinatario_id) if destinatario_id is not None else None,
        destinatario_rol=destinatario_rol,
        tipo=tipo,
        titulo=titulo,
        cuerpo=cuerpo,
        data_json=json.dumps(data, ensure_ascii=False) if data else None,
    )
    db.add(notif)
    if commit:
        db.commit()
        db.refresh(notif)
    # Push FCM best-effort: si hay credenciales y tokens registrados, manda el
    # aviso al celular. Si no, es no-op (el centro en BD ya quedo guardado).
    try:
        destino_id = str(destinatario_id) if destinatario_id is not None else None
        tokens = _tokens_destino(db, destino_id, destinatario_rol)
        if tokens:
            fcm_sender.enviar(
                tokens,
                titulo=titulo,
                cuerpo=cuerpo,
                data={"tipo": tipo, **(data or {})},
            )
    except Exception as e:  # nunca romper el flujo principal por el push
        log.warning("No se pudo emitir push FCM: %s", e)
    return notif


def _filtro_mias(query, user: dict):
    sub = user.get("sub")
    rol = user.get("rol")
    sub_str = str(sub) if sub is not None else None
    return query.filter(
        or_(
            Notificacion.destinatario_id == sub_str,
            and_(
                Notificacion.destinatario_rol == rol,
                Notificacion.destinatario_id.is_(None),
            ),
        )
    )


def listar(db: Session, user: dict, solo_no_leidas: bool = False, limit: int = 100) -> list[Notificacion]:
    q = _filtro_mias(db.query(Notificacion), user)
    if solo_no_leidas:
        q = q.filter(Notificacion.leida.is_(False))
    return q.order_by(Notificacion.created_at.desc()).limit(limit).all()


def contar_no_leidas(db: Session, user: dict) -> int:
    return _filtro_mias(db.query(Notificacion), user).filter(Notificacion.leida.is_(False)).count()


def marcar_leida(db: Session, user: dict, notif_id: int) -> bool:
    notif = _filtro_mias(db.query(Notificacion), user).filter(Notificacion.id == notif_id).first()
    if not notif:
        return False
    if not notif.leida:
        notif.leida = True
        notif.read_at = datetime.now(timezone.utc)
        db.commit()
    return True


def marcar_todas(db: Session, user: dict) -> int:
    pendientes = _filtro_mias(db.query(Notificacion), user).filter(Notificacion.leida.is_(False)).all()
    ahora = datetime.now(timezone.utc)
    for n in pendientes:
        n.leida = True
        n.read_at = ahora
    db.commit()
    return len(pendientes)
