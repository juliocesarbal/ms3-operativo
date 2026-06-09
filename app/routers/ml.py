from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.ml_models import inference
from app.models.dataset import (
    EnvioHistorico,
    IncidenteZona,
    Prediccion,
    ZonaDiaMetrica,
    ZonaMetrica,
)
from app.models.sucursal import Sucursal
from app.services import geo
from app.schemas.dataset import (
    EnvioHistoricoOut,
    ResumenDataset,
    ZonaDiaMetricaOut,
    ZonaMetricaOut,
)
from app.schemas.ml import (
    AgruparZonasIn,
    PredecirRetrasoOut,
    PredecirRetrasoIn,
    ZonaGrupoOut,
)

router = APIRouter(prefix="/api/ops/ml", tags=["ml"])


# CU-12: predecir riesgo de retraso (ML supervisado). Solo ADMIN.
# La distancia (feature clave) se calcula de las sucursales origen/destino.
# Persiste el resultado en la tabla `prediccion` (spec: "resultados de prediccion").
@router.post("/predecir-retraso", response_model=PredecirRetrasoOut)
def predecir_retraso(
    data: PredecirRetrasoIn,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("ADMIN")),
):
    # Distancia: 1) de sucursales (haversine), 2) manual de respaldo.
    distancia = geo.distancia_sucursales(db, data.sucursal_origen_id, data.sucursal_destino_id)
    if distancia is None:
        distancia = data.distancia
    if distancia is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Falta la distancia: elige sucursal de origen y destino, o envía 'distancia'.",
        )

    features = {
        "peso": data.peso,
        "distancia": distancia,
        "hora": data.hora,
        "dia_semana": data.dia_semana,
        "tipo_servicio": data.tipo_servicio,
    }
    try:
        res = inference.predecir_retraso(features)
    except FileNotFoundError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    prob = res["probabilidades"].get(res["riesgo"])
    db.add(
        Prediccion(tipo="RETRASO", riesgo=res["riesgo"], probabilidad=prob, modelo="RandomForest")
    )
    db.commit()
    res["distancia"] = round(float(distancia), 2)
    return res


# CU-13: agrupar zonas (ML no supervisado, K-Means). Solo ADMIN.
@router.post("/agrupar-zonas", response_model=list[ZonaGrupoOut])
def agrupar_zonas(
    data: AgruparZonasIn,
    _user: dict = Depends(require_roles("ADMIN")),
):
    try:
        salida: list[ZonaGrupoOut] = []
        for z in data.zonas:
            res = inference.agrupar_zona(z.model_dump())
            salida.append(
                ZonaGrupoOut(
                    nombre=z.nombre,
                    cluster=res["cluster"],
                    grupo=res["grupo"],
                    num_envios=z.num_envios,
                    num_incidencias=z.num_incidencias,
                )
            )
        return salida
    except FileNotFoundError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))


# ---------- Datasets (lectura) — para ver de donde se entrena ----------

@router.get("/dataset/resumen", response_model=ResumenDataset)
def dataset_resumen(db: Session = Depends(get_db), _user: dict = Depends(get_current_user)):
    def _conteo(col):
        return {k: v for k, v in db.query(col, func.count()).group_by(col).all()}

    dias = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
    inc_dia = {dias[k]: v for k, v in db.query(IncidenteZona.dia_semana, func.count()).group_by(IncidenteZona.dia_semana).all()}
    return ResumenDataset(
        sucursales=db.query(Sucursal).count(),
        zonas=db.query(ZonaMetrica).count(),
        envios_historicos=db.query(EnvioHistorico).count(),
        incidentes=db.query(IncidenteZona).count(),
        zonas_por_grupo=_conteo(ZonaMetrica.grupo),
        envios_por_riesgo=_conteo(EnvioHistorico.riesgo),
        envios_por_servicio=_conteo(EnvioHistorico.tipo_servicio),
        incidentes_por_tipo=_conteo(IncidenteZona.tipo),
        incidentes_por_dia=inc_dia,
    )


# Métricas por zona y día (dataset temporal del K-Means). Filtro opcional por día.
@router.get("/dataset/zona-dia", response_model=list[ZonaDiaMetricaOut])
def dataset_zona_dia(
    dia_semana: int | None = None,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    q = db.query(ZonaDiaMetrica)
    if dia_semana is not None:
        q = q.filter(ZonaDiaMetrica.dia_semana == dia_semana)
    return q.order_by(ZonaDiaMetrica.zona_metrica_id, ZonaDiaMetrica.dia_semana).all()


@router.get("/dataset/zonas", response_model=list[ZonaMetricaOut])
def dataset_zonas(db: Session = Depends(get_db), _user: dict = Depends(get_current_user)):
    return db.query(ZonaMetrica).order_by(ZonaMetrica.nombre).all()


@router.get("/dataset/envios", response_model=list[EnvioHistoricoOut])
def dataset_envios(
    limit: int = 100,
    riesgo: str | None = None,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    q = db.query(EnvioHistorico)
    if riesgo:
        q = q.filter(EnvioHistorico.riesgo == riesgo)
    return q.order_by(EnvioHistorico.id).limit(min(limit, 1000)).all()


# Aplica el K-Means entrenado a las zonas de la BD y persiste el grupo. Solo ADMIN.
@router.post("/zonas/reclasificar", response_model=list[ZonaMetricaOut])
def reclasificar_zonas(db: Session = Depends(get_db), _user: dict = Depends(require_roles("ADMIN"))):
    zonas = db.query(ZonaMetrica).all()
    if not zonas:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No hay zonas. Corre el seed primero.")
    try:
        for z in zonas:
            res = inference.agrupar_zona(
                {
                    "num_envios": z.num_envios,
                    "tiempo_entrega_prom": z.tiempo_entrega_prom,
                    "num_incidencias": z.num_incidencias,
                    "inc_trafico": z.inc_trafico,
                    "inc_bloqueo": z.inc_bloqueo,
                    "velocidad_prom": z.velocidad_prom,
                }
            )
            z.grupo = res["grupo"]
    except FileNotFoundError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    db.commit()
    return db.query(ZonaMetrica).order_by(ZonaMetrica.nombre).all()
