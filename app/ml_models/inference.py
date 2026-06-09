"""Carga de modelos entrenados (lazy, una vez) + prediccion. No entrena en runtime."""
import joblib
import pandas as pd

from app.ml_models.features import (
    RETRASO_FEATURES,
    RETRASO_MODEL_PATH,
    ZONA_CLUSTER_FEATURES,
    ZONAS_MODEL_PATH,
)

_retraso = None
_zonas = None


def _load_retraso():
    global _retraso
    if _retraso is None:
        if not RETRASO_MODEL_PATH.exists():
            raise FileNotFoundError(
                "Modelo de retraso no entrenado. Corre: python -m ml_training.train_retraso"
            )
        _retraso = joblib.load(RETRASO_MODEL_PATH)
    return _retraso


def _load_zonas():
    global _zonas
    if _zonas is None:
        if not ZONAS_MODEL_PATH.exists():
            raise FileNotFoundError(
                "Modelo de zonas no entrenado. Corre: python -m ml_training.train_zonas"
            )
        _zonas = joblib.load(ZONAS_MODEL_PATH)
    return _zonas


# CU-12: riesgo de retraso BAJO/MEDIO/ALTO + probabilidades.
def predecir_retraso(features: dict) -> dict:
    pipe = _load_retraso()["pipeline"]
    row = pd.DataFrame([{c: features.get(c) for c in RETRASO_FEATURES}])
    pred = pipe.predict(row)[0]
    proba = pipe.predict_proba(row)[0]
    probabilidades = {
        str(c): round(float(p), 4) for c, p in zip(pipe.classes_, proba)
    }
    return {"riesgo": str(pred), "probabilidades": probabilidades}


# CU-13: asigna una zona a su grupo (alta demanda / retrasos / baja demanda).
def agrupar_zona(features: dict) -> dict:
    modelo = _load_zonas()
    km, scaler, labels = modelo["kmeans"], modelo["scaler"], modelo["labels"]
    row = [[float(features.get(c, 0)) for c in ZONA_CLUSTER_FEATURES]]
    cluster = int(km.predict(scaler.transform(row))[0])
    return {"cluster": cluster, "grupo": labels.get(cluster, str(cluster))}
