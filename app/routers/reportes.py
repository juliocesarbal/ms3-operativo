"""Reportes BI operativos (MS3): agregaciones del histórico de envíos para el
dashboard gerencial. Alimenta las hojas de Operación y Rankings del frontend."""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.dataset import EnvioHistorico
from app.models.sucursal import Sucursal
from app.schemas.dataset import Par, ReporteOperacion, ReporteRankings

router = APIRouter(prefix="/api/ops/reportes", tags=["reportes"])


def _conteo(db, col):
    return {str(k): int(v) for k, v in db.query(col, func.count()).group_by(col).all() if k is not None}


# Resumen operativo del histórico de envíos (CU-16, BI gerencial).
@router.get("/operacion", response_model=ReporteOperacion)
def operacion(db: Session = Depends(get_db), _user: dict = Depends(get_current_user)):
    total = db.query(func.count(EnvioHistorico.id)).scalar() or 0
    dist = db.query(func.avg(EnvioHistorico.distancia)).scalar() or 0
    tiempo = db.query(func.avg(EnvioHistorico.horas_transito)).scalar() or 0
    a_tiempo = db.query(func.count(EnvioHistorico.id)).filter(EnvioHistorico.entregado_a_tiempo.is_(True)).scalar() or 0

    # Serie por mes (dialect-aware: Postgres to_char / SQLite strftime).
    if db.bind.dialect.name == "postgresql":
        mes = func.to_char(EnvioHistorico.fecha_registro, "YYYY-MM")
    else:
        mes = func.strftime("%Y-%m", EnvioHistorico.fecha_registro)
    por_mes = {str(k): int(v) for k, v in db.query(mes, func.count()).group_by(mes).order_by(mes).all() if k}

    return ReporteOperacion(
        total_envios=total,
        distancia_prom_km=round(float(dist), 1),
        tiempo_prom_h=round(float(tiempo), 1),
        entregados_a_tiempo_pct=round(a_tiempo / total * 100, 1) if total else 0.0,
        por_zona=_conteo(db, EnvioHistorico.zona),
        por_servicio=_conteo(db, EnvioHistorico.tipo_servicio),
        por_riesgo=_conteo(db, EnvioHistorico.riesgo),
        por_mes=por_mes,
    )


# Rankings / Top-N (mayores clientes, servicios, zonas, rutas, sucursales).
@router.get("/rankings", response_model=ReporteRankings)
def rankings(db: Session = Depends(get_db), _user: dict = Depends(get_current_user)):
    sucs = {s.id: s.nombre for s in db.query(Sucursal).all()}

    def top(col, limite=10):
        q = db.query(col, func.count().label("n")).group_by(col).order_by(func.count().desc()).limit(limite)
        return [Par(clave=str(k), valor=int(v)) for k, v in q.all() if k is not None]

    # Top rutas: por par (origen, destino).
    rutas_q = (
        db.query(
            EnvioHistorico.sucursal_origen_id,
            EnvioHistorico.sucursal_destino_id,
            func.count().label("n"),
        )
        .group_by(EnvioHistorico.sucursal_origen_id, EnvioHistorico.sucursal_destino_id)
        .order_by(func.count().desc())
        .limit(10)
        .all()
    )
    top_rutas = [
        Par(clave=f"{sucs.get(o, o)} → {sucs.get(d, d)}", valor=int(n))
        for o, d, n in rutas_q
    ]

    top_suc = [
        Par(clave=sucs.get(int(p.clave), p.clave), valor=p.valor)
        for p in top(EnvioHistorico.sucursal_origen_id)
    ]

    return ReporteRankings(
        top_clientes=top(EnvioHistorico.cliente_nombre),
        top_servicios=top(EnvioHistorico.tipo_servicio),
        top_zonas=top(EnvioHistorico.zona),
        top_rutas=top_rutas,
        top_sucursales=top_suc,
    )
