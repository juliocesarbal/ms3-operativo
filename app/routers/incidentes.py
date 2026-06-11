from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.dataset import IncidenteZona, ZonaDiaMetrica
from app.schemas.dataset import IncidenteZonaCreate, IncidenteZonaOut
from app.services import geo, n8n_client, notificacion_service

router = APIRouter(prefix="/api/ops/incidentes", tags=["incidentes"])


# CU-13 (refuerzo): un asesor reporta un incidente de ruta/zona desde el campo
# (bloqueo, tráfico, evento social...). Se ubica en la zona más cercana por GPS
# y suma a la métrica de esa zona EN ESE DÍA (alimenta el K-Means). ASESOR/ADMIN.
@router.post("", response_model=IncidenteZonaOut, status_code=status.HTTP_201_CREATED)
def reportar(
    data: IncidenteZonaCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("ASESOR", "ADMIN")),
):
    dia = data.dia_semana if data.dia_semana is not None else datetime.now(timezone.utc).weekday()
    zona = geo.zona_mas_cercana(db, data.gps_lat, data.gps_lng)

    inc = IncidenteZona(
        tracking_ref=data.tracking_ref,
        tipo=data.tipo,
        descripcion=data.descripcion,
        gps_lat=data.gps_lat,
        gps_lng=data.gps_lng,
        dia_semana=dia,
        hora=data.hora,
        zona_metrica_id=zona.id if zona else None,
        asesor_id=str(user.get("sub")) if user.get("sub") is not None else None,
    )
    db.add(inc)

    # Suma a la métrica de esa zona en ese día (el K-Means lo verá al reentrenar).
    if zona:
        fila = (
            db.query(ZonaDiaMetrica)
            .filter(ZonaDiaMetrica.zona_metrica_id == zona.id, ZonaDiaMetrica.dia_semana == dia)
            .first()
        )
        if fila:
            fila.num_incidencias = (fila.num_incidencias or 0) + 1

    db.commit()
    db.refresh(inc)

    # Notifica al admin (centro de notificaciones) que hay un incidente nuevo.
    notificacion_service.crear(
        db,
        tipo="INCIDENCIA",
        titulo=f"Nuevo incidente: {inc.tipo}",
        cuerpo=inc.descripcion or "Un asesor reportó un incidente de zona.",
        destinatario_rol="ADMIN",
        data={
            "incidente_id": inc.id,
            "tipo": inc.tipo,
            "asesor_id": inc.asesor_id,
            "gps_lat": inc.gps_lat,
            "gps_lng": inc.gps_lng,
            "tracking_ref": inc.tracking_ref,
        },
    )

    # Alerta externa (email + Telegram) via n8n. Best-effort: no afecta el reporte.
    n8n_client.disparar_incidente(
        inc.tracking_ref,
        {
            "tipo": inc.tipo,
            "descripcion": inc.descripcion,
            "zona": zona.nombre if zona else None,
            "gps_lat": inc.gps_lat,
            "gps_lng": inc.gps_lng,
            "asesor_id": inc.asesor_id,
        },
    )
    return inc


# Lista de incidentes (para mapa / dashboard). Filtros por día y tipo.
@router.get("", response_model=list[IncidenteZonaOut])
def listar(
    dia_semana: int | None = None,
    tipo: str | None = None,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    q = db.query(IncidenteZona)
    if dia_semana is not None:
        q = q.filter(IncidenteZona.dia_semana == dia_semana)
    if tipo:
        q = q.filter(IncidenteZona.tipo == tipo)
    return q.order_by(IncidenteZona.fecha.desc()).limit(500).all()
