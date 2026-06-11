"""CU-11 (IA externa): analiza la foto del paquete con la Hugging Face Inference
API (gratuita). Usa un modelo de image-classification: devuelve etiquetas+score,
que mapeamos a nuestras 3 clases de estado del paquete.

El token sale de settings.hf_api_token (.env: HF_API_TOKEN). Si no hay token o la
API falla, se lanza RuntimeError para que el router pueda caer al modelo local.
"""
from __future__ import annotations

import logging
import time

import httpx

from app.core.config import settings

log = logging.getLogger("ms3.hf")

CLASES = ["SIN_DAÑO", "POSIBLE_DAÑO", "ETIQUETA_ILEGIBLE"]

# Palabras (en las etiquetas ImageNet) que sugieren un paquete/embalaje en orden.
_OK_KEYWORDS = (
    "carton", "box", "packet", "package", "envelope", "crate", "container",
    "wrapping", "paper", "parcel", "mailbag", "sack", "bag",
)


def _mapear(label: str, score: float) -> str:
    """Mapea una etiqueta generica + confianza a nuestra clase de estado."""
    l = label.lower()
    if score < 0.20:
        # El modelo no esta seguro de lo que ve -> tratamos como ilegible/dudoso.
        return "ETIQUETA_ILEGIBLE"
    if any(k in l for k in _OK_KEYWORDS):
        return "SIN_DAÑO"
    # Reconoce algo con confianza pero no parece un embalaje intacto.
    return "POSIBLE_DAÑO"


def _probabilidades(clase: str, conf: float) -> dict[str, float]:
    conf = max(0.0, min(conf, 1.0))
    resto = round((1.0 - conf) / 2, 4)
    return {c: (round(conf, 4) if c == clase else resto) for c in CLASES}


def disponible() -> bool:
    return bool(settings.hf_api_token)


def analizar_imagen(contenido: bytes) -> dict:
    if not settings.hf_api_token:
        raise RuntimeError("HF_API_TOKEN no configurado")

    url = f"{settings.hf_api_base.rstrip('/')}/{settings.hf_model}"
    headers = {
        "Authorization": f"Bearer {settings.hf_api_token}",
        "Content-Type": "application/octet-stream",
    }

    data = None
    # El modelo serverless puede estar "cargando" (503): reintenta una vez.
    for intento in range(2):
        try:
            r = httpx.post(url, headers=headers, content=contenido, timeout=30)
        except httpx.HTTPError as e:
            raise RuntimeError(f"Hugging Face inaccesible: {e}") from e

        if r.status_code == 503 and intento == 0:
            espera = 8.0
            try:
                espera = min(float(r.json().get("estimated_time", 8.0)), 20.0)
            except (ValueError, KeyError):
                pass
            log.info("HF modelo cargando, reintento en %.1fs", espera)
            time.sleep(espera)
            continue
        if r.status_code == 401:
            raise RuntimeError("Token de Hugging Face invalido (401)")
        if r.status_code >= 400:
            raise RuntimeError(f"Hugging Face error {r.status_code}: {r.text[:200]}")
        data = r.json()
        break

    if not isinstance(data, list) or not data:
        raise RuntimeError("Respuesta inesperada de Hugging Face")

    # data = [{ "label": "...", "score": 0.9 }, ...] ordenado desc por score.
    etiquetas = [
        {"label": str(d.get("label", "")), "score": round(float(d.get("score", 0.0)), 4)}
        for d in data[:5]
    ]
    top = etiquetas[0]
    clase = _mapear(top["label"], top["score"])
    conf = top["score"]
    return {
        "clase": clase,
        "confianza": round(float(conf), 4),
        "probabilidades": _probabilidades(clase, conf),
        "etiquetas": etiquetas,
        "fuente": "HUGGINGFACE",
    }
