"""Reportes BI operativos (MS3): agregaciones del histórico de envíos para el
dashboard gerencial. Alimenta las hojas de Operación, Rankings y el drill-down
por cliente del frontend.

Todas las consultas comparten un mismo conjunto de FILTROS (dimensiones): rango
de meses, día de semana, hora, tipo de servicio, riesgo y sucursal origen/destino.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.dataset import EnvioHistorico
from app.models.sucursal import Sucursal
from app.schemas.dataset import (
    Par,
    RankingClienteDetalle,
    ReporteOperacion,
    ReporteRankings,
)

router = APIRouter(prefix="/api/ops/reportes", tags=["reportes"])


# ----- Filtros compartidos (dimensiones) -------------------------------------
class FiltrosReporte:
    """Dependencia: lee los filtros del query string y arma la lista de
    condiciones SQLAlchemy aplicables a EnvioHistorico."""

    def __init__(
        self,
        desde: str | None = Query(None, description="Mes inicial YYYY-MM (inclusive)"),
        hasta: str | None = Query(None, description="Mes final YYYY-MM (inclusive)"),
        dia_semana: int | None = Query(None, ge=0, le=6),
        hora_desde: int | None = Query(None, ge=0, le=23),
        hora_hasta: int | None = Query(None, ge=0, le=23),
        tipo_servicio: str | None = Query(None),
        riesgo: str | None = Query(None),
        sucursal_origen_id: int | None = Query(None),
        sucursal_destino_id: int | None = Query(None),
    ):
        self.desde = desde
        self.hasta = hasta
        self.dia_semana = dia_semana
        self.hora_desde = hora_desde
        self.hora_hasta = hora_hasta
        self.tipo_servicio = tipo_servicio
        self.riesgo = riesgo
        self.sucursal_origen_id = sucursal_origen_id
        self.sucursal_destino_id = sucursal_destino_id

    def condiciones(self, db: Session) -> list:
        c = []
        E = EnvioHistorico
        # Mes (texto YYYY-MM) — dialect-aware sobre fecha_registro.
        if self.desde or self.hasta:
            if db.bind.dialect.name == "postgresql":
                mes = func.to_char(E.fecha_registro, "YYYY-MM")
            else:
                mes = func.strftime("%Y-%m", E.fecha_registro)
            if self.desde:
                c.append(mes >= self.desde)
            if self.hasta:
                c.append(mes <= self.hasta)
        if self.dia_semana is not None:
            c.append(E.dia_semana == self.dia_semana)
        if self.hora_desde is not None:
            c.append(E.hora >= self.hora_desde)
        if self.hora_hasta is not None:
            c.append(E.hora <= self.hora_hasta)
        if self.tipo_servicio:
            c.append(E.tipo_servicio == self.tipo_servicio)
        if self.riesgo:
            c.append(E.riesgo == self.riesgo)
        if self.sucursal_origen_id:
            c.append(E.sucursal_origen_id == self.sucursal_origen_id)
        if self.sucursal_destino_id:
            c.append(E.sucursal_destino_id == self.sucursal_destino_id)
        return c


def _conteo(db, col, cond):
    q = db.query(col, func.count()).filter(*cond).group_by(col)
    return {str(k): int(v) for k, v in q.all() if k is not None}


# Resumen operativo del histórico de envíos (CU-16, BI gerencial), con filtros.
@router.get("/operacion", response_model=ReporteOperacion)
def operacion(
    db: Session = Depends(get_db),
    filtros: FiltrosReporte = Depends(),
    _user: dict = Depends(get_current_user),
):
    cond = filtros.condiciones(db)
    E = EnvioHistorico
    total = db.query(func.count(E.id)).filter(*cond).scalar() or 0
    dist = db.query(func.avg(E.distancia)).filter(*cond).scalar() or 0
    tiempo = db.query(func.avg(E.horas_transito)).filter(*cond).scalar() or 0
    a_tiempo = db.query(func.count(E.id)).filter(*cond, E.entregado_a_tiempo.is_(True)).scalar() or 0

    if db.bind.dialect.name == "postgresql":
        mes = func.to_char(E.fecha_registro, "YYYY-MM")
    else:
        mes = func.strftime("%Y-%m", E.fecha_registro)
    por_mes = {
        str(k): int(v)
        for k, v in db.query(mes, func.count()).filter(*cond).group_by(mes).order_by(mes).all()
        if k
    }

    return ReporteOperacion(
        total_envios=total,
        distancia_prom_km=round(float(dist), 1),
        tiempo_prom_h=round(float(tiempo), 1),
        entregados_a_tiempo_pct=round(a_tiempo / total * 100, 1) if total else 0.0,
        por_zona=_conteo(db, E.zona, cond),
        por_servicio=_conteo(db, E.tipo_servicio, cond),
        por_riesgo=_conteo(db, E.riesgo, cond),
        por_mes=por_mes,
    )


# Rankings / Top-N (mayores clientes, servicios, zonas, rutas, sucursales), con filtros.
@router.get("/rankings", response_model=ReporteRankings)
def rankings(
    db: Session = Depends(get_db),
    filtros: FiltrosReporte = Depends(),
    _user: dict = Depends(get_current_user),
):
    cond = filtros.condiciones(db)
    sucs = {s.id: s.nombre for s in db.query(Sucursal).all()}
    E = EnvioHistorico

    def top(col, limite=10):
        q = (
            db.query(col, func.count().label("n"))
            .filter(*cond)
            .group_by(col)
            .order_by(func.count().desc())
            .limit(limite)
        )
        return [Par(clave=str(k), valor=int(v)) for k, v in q.all() if k is not None]

    rutas_q = (
        db.query(E.sucursal_origen_id, E.sucursal_destino_id, func.count().label("n"))
        .filter(*cond)
        .group_by(E.sucursal_origen_id, E.sucursal_destino_id)
        .order_by(func.count().desc())
        .limit(10)
        .all()
    )
    top_rutas = [
        Par(clave=f"{sucs.get(o, o)} → {sucs.get(d, d)}", valor=int(n)) for o, d, n in rutas_q
    ]
    top_suc = [
        Par(clave=sucs.get(int(p.clave), p.clave), valor=p.valor)
        for p in top(E.sucursal_origen_id)
    ]

    return ReporteRankings(
        top_clientes=top(E.cliente_nombre),
        top_servicios=top(E.tipo_servicio),
        top_zonas=top(E.zona),
        top_rutas=top_rutas,
        top_sucursales=top_suc,
    )


# Drill-down de un cliente: desglose de SUS envíos (panel interactivo del ranking).
# Respeta los mismos filtros activos en la hoja.
@router.get("/rankings/cliente/{nombre}", response_model=RankingClienteDetalle)
def ranking_cliente(
    nombre: str,
    db: Session = Depends(get_db),
    filtros: FiltrosReporte = Depends(),
    _user: dict = Depends(get_current_user),
):
    E = EnvioHistorico
    cond = filtros.condiciones(db) + [E.cliente_nombre == nombre]
    sucs = {s.id: s.nombre for s in db.query(Sucursal).all()}

    total = db.query(func.count(E.id)).filter(*cond).scalar() or 0
    dist = db.query(func.avg(E.distancia)).filter(*cond).scalar() or 0
    a_tiempo = db.query(func.count(E.id)).filter(*cond, E.entregado_a_tiempo.is_(True)).scalar() or 0

    def top(col, limite=8):
        q = (
            db.query(col, func.count().label("n"))
            .filter(*cond)
            .group_by(col)
            .order_by(func.count().desc())
            .limit(limite)
        )
        return [Par(clave=str(k), valor=int(v)) for k, v in q.all() if k is not None]

    rutas_q = (
        db.query(E.sucursal_origen_id, E.sucursal_destino_id, func.count().label("n"))
        .filter(*cond)
        .group_by(E.sucursal_origen_id, E.sucursal_destino_id)
        .order_by(func.count().desc())
        .limit(8)
        .all()
    )
    por_rutas = [
        Par(clave=f"{sucs.get(o, o)} → {sucs.get(d, d)}", valor=int(n)) for o, d, n in rutas_q
    ]

    return RankingClienteDetalle(
        cliente=nombre,
        total_envios=total,
        entregados_a_tiempo_pct=round(a_tiempo / total * 100, 1) if total else 0.0,
        distancia_prom_km=round(float(dist), 1),
        por_servicio=top(E.tipo_servicio),
        por_zona=top(E.zona),
        por_rutas=por_rutas,
        por_riesgo=top(E.riesgo),
    )
