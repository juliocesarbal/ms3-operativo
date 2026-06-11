"""Chatbot BI (CU-16): ejecuta las consultas de los reportes que el chatbot pide.

Reusa la fuente de datos de los reportes ya existentes:
  - INGRESOS  -> MS1 (GraphQL): reportes(desde,hasta) — empresarial.
  - OPERACION -> MS3: agregados de EnvioHistorico (envios, distancia, % a tiempo).
  - RANKINGS  -> MS3: top clientes / servicios / zonas / rutas / sucursales.
  - ZONAS     -> MS3: clasificacion K-Means + incidentes por tipo.

"Sucursal = ciudad". El chatbot puede segmentar por ciudad o departamento; aqui
se traduce ese texto libre a los `sucursal_id` correspondientes y se filtra el
historico por sucursal de ORIGEN o DESTINO.

Devuelve un dict normalizado (ReporteData) que bi_export convierte a PDF/Excel/CSV.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Any

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dataset import EnvioHistorico, IncidenteZona, ZonaMetrica
from app.models.sucursal import Sucursal

log = logging.getLogger("ms3.bi_data")

TIPOS = ["INGRESOS", "OPERACION", "RANKINGS", "ZONAS"]
FORMATOS = ["PDF", "EXCEL", "CSV"]


def _norm(s: str) -> str:
    """minúsculas sin acentos, para comparar 'Santa Cruz' == 'santa cruz'."""
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()


def resolver_sucursales(
    db: Session, ciudades: list[str] | None, departamento: str | None
) -> tuple[list[int], list[str]]:
    """Traduce ciudad(es)/departamento (texto libre) a sucursal_id.

    Devuelve (ids, etiquetas). Si no se pidió segmento geográfico => ([], []).
    El match es por substring normalizado contra ciudad, departamento y nombre.
    """
    terminos = [t for t in (ciudades or []) if t and t.strip()]
    if departamento and departamento.strip():
        terminos.append(departamento)
    if not terminos:
        return [], []

    terminos_n = [_norm(t) for t in terminos]
    ids: list[int] = []
    etiquetas: list[str] = []
    for suc in db.query(Sucursal).all():
        campos = _norm(f"{suc.ciudad} {suc.departamento} {suc.nombre}")
        if any(t in campos for t in terminos_n):
            ids.append(suc.id)
            etiquetas.append(f"{suc.nombre} ({suc.ciudad})")
    return ids, etiquetas


# ---- Filtros compartidos sobre EnvioHistorico (mismos que routers/reportes.py) ----
def _condiciones_envio(db: Session, params: dict[str, Any], sucursal_ids: list[int]) -> list:
    E = EnvioHistorico
    c: list = []
    desde, hasta = params.get("desde"), params.get("hasta")
    if desde or hasta:
        if db.bind.dialect.name == "postgresql":
            mes = func.to_char(E.fecha_registro, "YYYY-MM")
        else:
            mes = func.strftime("%Y-%m", E.fecha_registro)
        if desde:
            c.append(mes >= desde)
        if hasta:
            c.append(mes <= hasta)
    if params.get("dia_semana") is not None:
        c.append(E.dia_semana == params["dia_semana"])
    if params.get("hora_desde") is not None:
        c.append(E.hora >= params["hora_desde"])
    if params.get("hora_hasta") is not None:
        c.append(E.hora <= params["hora_hasta"])
    if params.get("tipo_servicio"):
        c.append(E.tipo_servicio == params["tipo_servicio"])
    if params.get("riesgo"):
        c.append(E.riesgo == params["riesgo"])
    if sucursal_ids:
        # envío que toca alguna de las sucursales del segmento (origen o destino).
        c.append(
            E.sucursal_origen_id.in_(sucursal_ids) | E.sucursal_destino_id.in_(sucursal_ids)
        )
    return c


def _conteo(db, col, cond) -> dict[str, int]:
    q = db.query(col, func.count()).filter(*cond).group_by(col)
    return {str(k): int(v) for k, v in q.all() if k is not None}


# ===== Reporte estructurado normalizado (consume bi_export) =====
# {
#   "titulo": str, "subtitulo": str,
#   "kpis": [{"label","valor"}],
#   "tablas": [{"titulo","columnas":[...],"filas":[[...]]}],
# }
def construir_reporte(db: Session, params: dict[str, Any], token: str | None) -> dict[str, Any]:
    tipo = (params.get("tipo") or "OPERACION").upper()
    sucursal_ids, etiquetas = resolver_sucursales(
        db, params.get("ciudades"), params.get("departamento")
    )
    seg = f" · {', '.join(etiquetas)}" if etiquetas else ""
    rango = _rango_texto(params)

    if tipo == "INGRESOS":
        rep = _reporte_ingresos(params, token)
    elif tipo == "RANKINGS":
        rep = _reporte_rankings(db, params, sucursal_ids)
    elif tipo == "ZONAS":
        rep = _reporte_zonas(db)
    else:
        rep = _reporte_operacion(db, params, sucursal_ids)

    rep["subtitulo"] = (rep.get("subtitulo", "") + rango + seg).strip(" ·")
    rep["segmento_sucursales"] = etiquetas
    return rep


def _rango_texto(params: dict[str, Any]) -> str:
    d, h = params.get("desde"), params.get("hasta")
    if d and h:
        return f" · {d} a {h}"
    if d:
        return f" · desde {d}"
    if h:
        return f" · hasta {h}"
    return ""


# ---- INGRESOS (MS1 GraphQL) ----
def _reporte_ingresos(params: dict[str, Any], token: str | None) -> dict[str, Any]:
    # MS1 filtra por fecha (desde/hasta como YYYY-MM o fecha). No segmenta por sucursal.
    data = _consultar_ms1_reportes(params.get("desde"), params.get("hasta"), token)
    if data is None:
        return {
            "titulo": "Ingresos y facturación",
            "subtitulo": "MS1 no disponible",
            "kpis": [],
            "tablas": [],
            "aviso": "No se pudo consultar MS1 (ingresos). Verifica MS1_URL / conexión.",
        }
    por_mes = data.get("ingresosPorMes") or []
    return {
        "titulo": "Ingresos y facturación",
        "subtitulo": "Resultados empresariales (MS1)",
        "kpis": [
            {"label": "Ingresos totales", "valor": f"Bs {_n(data.get('totalIngresos'))}"},
            {"label": "Cantidad de ingresos", "valor": _n(data.get("cantidadIngresos"))},
            {"label": "Ticket promedio", "valor": f"Bs {_n(data.get('ticketPromedio'))}"},
            {"label": "Clientes", "valor": _n(data.get("totalClientes"))},
        ],
        "tablas": [
            {
                "titulo": "Ingresos por mes (Bs)",
                "columnas": ["Mes", "Ingresos (Bs)"],
                "filas": [[x.get("clave"), _n(x.get("valor"), 2)] for x in por_mes],
            }
        ],
    }


def _consultar_ms1_reportes(desde, hasta, token) -> dict | None:
    if not settings.ms1_url:
        return None
    query = {
        "query": (
            "query($d:String,$h:String){ reportes(desde:$d,hasta:$h){ "
            "totalIngresos cantidadIngresos ticketPromedio totalClientes "
            "ingresosPorMes{ clave valor } } }"
        ),
        "variables": {"d": desde or None, "h": hasta or None},
    }
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = httpx.post(settings.ms1_url, json=query, headers=headers, timeout=12)
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            log.warning("MS1 reportes errors: %s", body["errors"])
            return None
        return (body.get("data") or {}).get("reportes")
    except httpx.HTTPError as e:
        log.warning("MS1 reportes fallo: %s", e)
        return None


# ---- OPERACION (MS3) ----
def _reporte_operacion(db: Session, params: dict, sucursal_ids: list[int]) -> dict[str, Any]:
    E = EnvioHistorico
    cond = _condiciones_envio(db, params, sucursal_ids)
    total = db.query(func.count(E.id)).filter(*cond).scalar() or 0
    dist = db.query(func.avg(E.distancia)).filter(*cond).scalar() or 0
    tiempo = db.query(func.avg(E.horas_transito)).filter(*cond).scalar() or 0
    a_tiempo = (
        db.query(func.count(E.id)).filter(*cond, E.entregado_a_tiempo.is_(True)).scalar() or 0
    )
    por_zona = _conteo(db, E.zona, cond)
    por_serv = _conteo(db, E.tipo_servicio, cond)
    por_riesgo = _conteo(db, E.riesgo, cond)
    pct = round(a_tiempo / total * 100, 1) if total else 0.0
    return {
        "titulo": "Envíos y operación",
        "subtitulo": "Indicadores logísticos (MS3)",
        "kpis": [
            {"label": "Envíos totales", "valor": _n(total)},
            {"label": "Distancia promedio", "valor": f"{_n(dist, 1)} km"},
            {"label": "Tiempo promedio", "valor": f"{_n(tiempo, 1)} h"},
            {"label": "Entregas a tiempo", "valor": f"{pct}%"},
        ],
        "tablas": [
            _tabla_dict("Envíos por zona", por_zona, "Zona"),
            _tabla_dict("Envíos por servicio", por_serv, "Servicio"),
            _tabla_dict("Envíos por riesgo", por_riesgo, "Riesgo"),
        ],
    }


# ---- RANKINGS (MS3) ----
def _reporte_rankings(db: Session, params: dict, sucursal_ids: list[int]) -> dict[str, Any]:
    E = EnvioHistorico
    cond = _condiciones_envio(db, params, sucursal_ids)
    sucs = {s.id: s.nombre for s in db.query(Sucursal).all()}

    def top(col, limite=10):
        q = (
            db.query(col, func.count().label("n"))
            .filter(*cond)
            .group_by(col)
            .order_by(func.count().desc())
            .limit(limite)
        )
        return [(str(k), int(v)) for k, v in q.all() if k is not None]

    rutas_q = (
        db.query(E.sucursal_origen_id, E.sucursal_destino_id, func.count().label("n"))
        .filter(*cond)
        .group_by(E.sucursal_origen_id, E.sucursal_destino_id)
        .order_by(func.count().desc())
        .limit(10)
        .all()
    )
    top_rutas = [(f"{sucs.get(o, o)} → {sucs.get(d, d)}", int(n)) for o, d, n in rutas_q]
    top_suc = [(sucs.get(int(k), k), v) for k, v in top(E.sucursal_origen_id)]

    return {
        "titulo": "Rankings y tops",
        "subtitulo": "Mayores clientes, servicios y rutas (MS3)",
        "kpis": [],
        "tablas": [
            _tabla_pares("Top clientes", top(E.cliente_nombre), "Cliente"),
            _tabla_pares("Top servicios", top(E.tipo_servicio), "Servicio"),
            _tabla_pares("Top zonas", top(E.zona), "Zona"),
            _tabla_pares("Top rutas", top_rutas, "Ruta"),
            _tabla_pares("Top sucursales (origen)", top_suc, "Sucursal"),
        ],
    }


# ---- ZONAS e incidentes (MS3) ----
def _reporte_zonas(db: Session) -> dict[str, Any]:
    por_grupo = _conteo(db, ZonaMetrica.grupo, [])
    por_tipo = _conteo(db, IncidenteZona.tipo, [])
    total_inc = db.query(func.count(IncidenteZona.id)).scalar() or 0
    total_zonas = db.query(func.count(ZonaMetrica.id)).scalar() or 0
    return {
        "titulo": "Zonas e incidentes",
        "subtitulo": "Clasificación K-Means y eventos (MS3)",
        "kpis": [
            {"label": "Zonas analizadas", "valor": _n(total_zonas)},
            {"label": "Incidentes registrados", "valor": _n(total_inc)},
        ],
        "tablas": [
            _tabla_dict("Zonas por grupo (K-Means)", por_grupo, "Grupo"),
            _tabla_dict("Incidentes por tipo", por_tipo, "Tipo"),
        ],
    }


# ---- helpers de formato ----
def _n(x, dec=0) -> str:
    try:
        v = float(x or 0)
    except (TypeError, ValueError):
        return "0"
    if dec == 0:
        return f"{v:,.0f}".replace(",", ".")
    return f"{v:,.{dec}f}"


def _tabla_dict(titulo: str, d: dict[str, int], col1: str) -> dict:
    filas = sorted(d.items(), key=lambda kv: -kv[1])
    return {"titulo": titulo, "columnas": [col1, "Cantidad"], "filas": [[k, v] for k, v in filas]}


def _tabla_pares(titulo: str, pares: list[tuple], col1: str) -> dict:
    return {"titulo": titulo, "columnas": [col1, "Cantidad"], "filas": [[k, v] for k, v in pares]}
