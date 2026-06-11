from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.schemas.notificacion import (
    ContadorOut,
    NotificacionAdminIn,
    NotificacionOut,
    RegistrarTokenIn,
)
from app.services import notificacion_service

router = APIRouter(prefix="/api/ops/notificaciones", tags=["notificaciones"])


# Mis notificaciones (por sub o por rol). ?solo_no_leidas=true para el filtro.
@router.get("", response_model=list[NotificacionOut])
def listar(
    solo_no_leidas: bool = False,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return notificacion_service.listar(db, user, solo_no_leidas)


@router.get("/contador", response_model=ContadorOut)
def contador(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return ContadorOut(no_leidas=notificacion_service.contar_no_leidas(db, user))


@router.post("/{notif_id}/leer", status_code=status.HTTP_204_NO_CONTENT)
def leer(
    notif_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if not notificacion_service.marcar_leida(db, user, notif_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notificacion no encontrada")


@router.post("/leer-todas")
def leer_todas(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    n = notificacion_service.marcar_todas(db, user)
    return {"marcadas": n}


# El movil registra su token FCM (para push real). Cualquier usuario autenticado.
@router.post("/registrar-token", status_code=status.HTTP_204_NO_CONTENT)
def registrar_token(
    data: RegistrarTokenIn,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    notificacion_service.registrar_token(db, user, data.token, data.plataforma)


# El ADMIN responde/avisa a un asesor (p.ej. "tu incidencia sera atendida").
@router.post("/admin", response_model=NotificacionOut, status_code=status.HTTP_201_CREATED)
def enviar_a_asesor(
    data: NotificacionAdminIn,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("ADMIN")),
):
    return notificacion_service.crear(
        db,
        tipo=data.tipo,
        titulo=data.titulo,
        cuerpo=data.cuerpo,
        destinatario_id=data.asesor_id,
    )
