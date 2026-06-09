"""Definicion compartida de features y rutas de modelos (train + inference)."""
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent

# ---- ML supervisado: prediccion de retraso (CU-12) ----
# Envío sucursal->sucursal (ciudad a ciudad). NO hay "zona de entrega": la empresa
# solo traslada entre sucursales, así que la zona dejó de ser feature del modelo.
RETRASO_NUMERIC = ["peso", "distancia", "hora", "dia_semana"]
RETRASO_CATEGORICAL = ["tipo_servicio"]
RETRASO_FEATURES = RETRASO_NUMERIC + RETRASO_CATEGORICAL

TIPOS_SERVICIO = ["DOCUMENTO", "PAQUETE_NORMAL", "CARGA_PESADA", "EXPRESS"]
CLASES_RIESGO = ["BAJO", "MEDIO", "ALTO"]

RETRASO_MODEL_PATH = MODEL_DIR / "retraso.pkl"

# ---- ML no supervisado: agrupacion de zonas (CU-13) ----
# Columnas completas de una zona (incluyen GPS, que se usa para ubicar/mapear).
ZONA_FEATURES = [
    "gps_lat",
    "gps_lng",
    "num_envios",
    "tiempo_entrega_prom",
    "num_incidencias",
]
# Features del CLUSTERING (comportamiento). Se excluye el GPS a proposito: las zonas
# abarcan todo el pais, asi que incluir lat/lng agruparia por geografia y no por
# comportamiento. El GPS se usa para geolocalizar incidentes y dibujar el mapa.
# Features del clustering = comportamiento operativo. Se añade inc_bloqueo (señal
# clave de tramos de carretera críticos) junto al volumen/tiempo/incidencias.
# velocidad_prom e inc_trafico/clima/social/accidente SE GUARDAN en la tabla (info
# rica para mapa/BI) pero NO entran al clustering: velocidad separaría urbano vs
# carretera por geografía/tipo, no por el comportamiento de los 3 grupos de negocio.
ZONA_CLUSTER_FEATURES = [
    "num_envios",
    "tiempo_entrega_prom",
    "num_incidencias",
    "inc_bloqueo",
]
GRUPOS_ZONA = ["ALTA_DEMANDA", "RETRASOS_FRECUENTES", "BAJA_DEMANDA"]

ZONAS_MODEL_PATH = MODEL_DIR / "kmeans_zonas.pkl"

# ---- IA: clasificacion de foto de paquete (CU-11) ----
IA_IMG_SIZE = 160
# Orden = indice de salida del modelo (0,1,2).
CLASES_IA = ["SIN_DAÑO", "POSIBLE_DAÑO", "ETIQUETA_ILEGIBLE"]
IA_MODEL_PATH = MODEL_DIR / "cnn_paquete.keras"
IA_CLASSES_PATH = MODEL_DIR / "clases_ia.json"
