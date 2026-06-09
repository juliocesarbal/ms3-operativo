from sqlalchemy.orm import Session

from app.core.estados import Estado, puede_transicionar
from app.models.encomienda import Encomienda
from app.models.operacion import Ruta
from app.schemas.operacion import RutaCreate
from app.services import tracking_service


# CU-08: crea la ruta, asigna encomiendas y las pasa a EN_TRANSITO (si corresponde).
# K-Means de zonas y push FCM se agregan en fases posteriores.
def crear_ruta(db: Session, data: RutaCreate) -> Ruta:
    encs: list[Encomienda] = []
    if data.encomienda_ids:
        encs = (
            db.query(Encomienda)
            .filter(Encomienda.id.in_(data.encomienda_ids))
            .all()
        )
        faltan = set(data.encomienda_ids) - {e.id for e in encs}
        if faltan:
            raise ValueError(f"Encomiendas no encontradas: {sorted(faltan)}")

    ruta = Ruta(asesor_id=data.asesor_id, zona_ref=data.zona_ref, fecha=data.fecha)
    ruta.encomiendas = encs
    db.add(ruta)

    # Asignar a ruta => en transito (best-effort por estado).
    for e in encs:
        if puede_transicionar(e.estado, Estado.EN_TRANSITO.value):
            tracking_service.transicionar(
                db, e, Estado.EN_TRANSITO.value,
                ubicacion=f"Asignada a ruta (zona {data.zona_ref})",
                commit=False,
            )

    db.commit()
    db.refresh(ruta)
    return ruta


def listar(db: Session, asesor_id: str | None = None) -> list[Ruta]:
    q = db.query(Ruta)
    if asesor_id:
        q = q.filter_by(asesor_id=asesor_id)
    return q.order_by(Ruta.created_at.desc()).all()


def obtener(db: Session, ruta_id: int) -> Ruta | None:
    return db.query(Ruta).filter_by(id=ruta_id).first()
