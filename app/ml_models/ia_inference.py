"""CU-11: carga del modelo CNN (lazy) + clasificacion de una foto de paquete."""
import io
import json

import numpy as np

from app.ml_models.features import IA_CLASSES_PATH, IA_IMG_SIZE, IA_MODEL_PATH

_model = None
_clases = None


def _load():
    global _model, _clases
    if _model is None:
        if not IA_MODEL_PATH.exists():
            raise FileNotFoundError(
                "Modelo IA no entrenado. Corre: python -m ml_training.train_ia"
            )
        import tensorflow as tf  # import pesado: solo al primer uso

        _model = tf.keras.models.load_model(IA_MODEL_PATH)
        _clases = json.loads(IA_CLASSES_PATH.read_text(encoding="utf-8"))
    return _model, _clases


# Salida: SIN_DAÑO | POSIBLE_DAÑO | ETIQUETA_ILEGIBLE + confianza + probabilidades.
def analizar_imagen(contenido: bytes) -> dict:
    from PIL import Image

    model, clases = _load()
    img = Image.open(io.BytesIO(contenido)).convert("RGB").resize((IA_IMG_SIZE, IA_IMG_SIZE))
    arr = np.asarray(img, dtype="float32")[None, ...]  # (1,H,W,3); el Rescaling esta en el modelo
    probs = model.predict(arr, verbose=0)[0]
    i = int(probs.argmax())
    return {
        "clase": clases[i],
        "confianza": round(float(probs[i]), 4),
        "probabilidades": {clases[j]: round(float(p), 4) for j, p in enumerate(probs)},
    }
