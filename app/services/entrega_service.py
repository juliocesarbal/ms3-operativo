from sqlalchemy.orm import Session

from app.core.estados import Estado
from app.models.encomienda import Encomienda
from app.models.operacion import Entrega, Ruta
from app.schemas.operacion import EscaneoResult
from app.services import tracking_service


def _asignada_a(db: Session, enc: Encomienda, asesor_id: str) -> bool:
    return (
        db.query(Ruta)
        .filter(Ruta.asesor_id == asesor_id, Ruta.encomiendas.any(Encomienda.id == enc.id))
        .first()
        is not None
    )


# CU-09: valida el QR (tracking) contra el envio asignado al asesor.
# Si esta EN_TRANSITO, lo pasa a EN_REPARTO (el asesor inicia el reparto).
def escanear_qr(db: Session, tracking: str, asesor_id: str) -> EscaneoResult:
    enc = tracking_service.obtener_por_tracking(db, tracking)
    if not enc:
        return EscaneoResult(valido=False, tracking_code=tracking, estado="-", mensaje="Encomienda no encontrada")
    if not _asignada_a(db, enc, asesor_id):
        return EscaneoResult(valido=False, tracking_code=tracking, estado=enc.estado, mensaje="No asignada a este asesor")
    if enc.estado == Estado.ENTREGADO.value:
        return EscaneoResult(valido=False, tracking_code=tracking, estado=enc.estado, mensaje="Ya entregada")

    if enc.estado == Estado.EN_TRANSITO.value:
        tracking_service.transicionar(db, enc, Estado.EN_REPARTO.value, ubicacion="Inicio de reparto")
    return EscaneoResult(valido=True, tracking_code=tracking, estado=enc.estado, mensaje="QR valido")


# CU-10: confirma la entrega (foto ya subida a MS2), GPS y estado ENTREGADO.
def confirmar_entrega(
    db: Session,
    enc: Encomienda,
    asesor_id: str,
    foto_url: str | None,
    gps_lat: float | None,
    gps_lng: float | None,
    qr_validado: bool,
) -> Entrega:
    # ENTREGADO valido desde EN_REPARTO o CON_INCIDENCIA (ver flujo). Lanza TransicionInvalida si no.
    tracking_service.transicionar(
        db, enc, Estado.ENTREGADO.value, ubicacion="Entrega confirmada",
        gps_lat=gps_lat, gps_lng=gps_lng, commit=False,
    )
    entrega = Entrega(
        encomienda_id=enc.id,
        asesor_id=asesor_id,
        foto_url=foto_url,
        gps_lat=gps_lat,
        gps_lng=gps_lng,
        qr_validado=qr_validado,
    )
    db.add(entrega)
    db.commit()
    db.refresh(entrega)
    # TODO Fase 4: registrar evento ENTREGA_CONFIRMADA en blockchain.
    return entrega
