import secrets

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.estados import Estado, puede_transicionar
from app.models.encomienda import Encomienda, EstadoHistorial
from app.schemas.encomienda import CambiarEstado, EncomiendaCreate
from app.services import blockchain_service, geo, n8n_client


class TransicionInvalida(ValueError):
    """Cambio de estado no permitido por el flujo."""


def generar_tracking(db: Session) -> str:
    for _ in range(10):
        code = "TRK-" + secrets.token_hex(4).upper()
        if not db.query(Encomienda).filter_by(tracking_code=code).first():
            return code
    raise RuntimeError("No se pudo generar un tracking unico")


# CU-05: crea la encomienda, genera tracking y deja estado REGISTRADO + historial inicial.
def crear_encomienda(db: Session, data: EncomiendaCreate) -> Encomienda:
    # Distancia real entre sucursales (haversine) — feature clave para el ML de retraso.
    distancia = geo.distancia_sucursales(db, data.sucursal_origen_id, data.sucursal_destino_id)
    enc = Encomienda(
        tracking_code=generar_tracking(db),
        estado=Estado.REGISTRADO.value,
        distancia=distancia,
        **data.model_dump(),
    )
    db.add(enc)
    db.flush()  # asigna enc.id
    db.add(EstadoHistorial(encomienda_id=enc.id, estado=Estado.REGISTRADO.value))
    db.commit()
    db.refresh(enc)
    return enc


def obtener_por_tracking(db: Session, tracking: str) -> Encomienda | None:
    return db.query(Encomienda).filter_by(tracking_code=tracking).first()


def listar(
    db: Session, estado: str | None = None, cliente_id: str | None = None
) -> list[Encomienda]:
    q = db.query(Encomienda)
    if estado:
        q = q.filter_by(estado=estado)
    if cliente_id:
        q = q.filter_by(cliente_id=cliente_id)
    return q.order_by(Encomienda.created_at.desc()).all()


# Aplica una transicion de estado validando el flujo y registrando historial.
# commit=False permite agrupar varias en una sola transaccion (p.ej. asignar ruta).
# bg!=None registra el cambio en blockchain (CAMBIO_ESTADO) en background: persiste
# el evento al instante (tx_hash pendiente) y lo mina despues sin bloquear la respuesta.
def transicionar(
    db: Session,
    enc: Encomienda,
    nuevo_estado: str,
    ubicacion: str | None = None,
    gps_lat: float | None = None,
    gps_lng: float | None = None,
    commit: bool = True,
    bg: BackgroundTasks | None = None,
) -> Encomienda:
    if not puede_transicionar(enc.estado, nuevo_estado):
        raise TransicionInvalida(f"Transicion invalida: {enc.estado} -> {nuevo_estado}")
    anterior = enc.estado
    enc.estado = nuevo_estado
    db.add(
        EstadoHistorial(
            encomienda_id=enc.id,
            estado=nuevo_estado,
            ubicacion=ubicacion,
            gps_lat=gps_lat,
            gps_lng=gps_lng,
        )
    )
    if commit:
        db.commit()
        db.refresh(enc)

    # CU-14: registra CADA cambio de estado en blockchain (trazabilidad inmutable).
    # Requiere commit=True (necesita enc.id persistido). La entrega ya emite su
    # propio ENTREGA_CONFIRMADA; aqui se cubre el resto del flujo.
    if bg is not None and commit:
        evento_id = blockchain_service.crear_pendiente(
            db,
            enc.tracking_code,
            "CAMBIO_ESTADO",
            {
                "tracking": enc.tracking_code,
                "estado_anterior": anterior,
                "estado_nuevo": nuevo_estado,
                "ubicacion": ubicacion,
                "gps_lat": gps_lat,
                "gps_lng": gps_lng,
            },
        )
        bg.add_task(blockchain_service.registrar_en_cadena, evento_id)

    # CU-15: al detectar retraso, dispara el flujo de aviso en n8n (best-effort).
    if nuevo_estado == Estado.RETRASADO.value:
        n8n_client.disparar_retraso(
            enc.tracking_code,
            {
                "estado": nuevo_estado,
                "cliente_nombre": enc.cliente_nombre,
                "destino": enc.destino,
                "ubicacion": ubicacion,
            },
        )
    return enc


# CU-07: cambia el estado (endpoint manual). bg propaga el registro en blockchain.
def cambiar_estado(
    db: Session, enc: Encomienda, cambio: CambiarEstado, bg: BackgroundTasks | None = None
) -> Encomienda:
    return transicionar(
        db, enc, cambio.estado.value, cambio.ubicacion, cambio.gps_lat, cambio.gps_lng, bg=bg
    )
