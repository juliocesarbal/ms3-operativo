import logging

import httpx

from app.core.config import settings

log = logging.getLogger("ms3.ms1_client")


# Obtiene datos del cliente desde MS1 (GraphQL) para cachearlos en la encomienda.
# Best-effort: si MS1 no responde, devuelve None y el flujo sigue.
def obtener_cliente(cliente_id: str, token: str) -> dict | None:
    if not settings.ms1_url or not cliente_id:
        return None
    query = {
        "query": "query($id: ID!){ cliente(id:$id){ id nombre direccion } }",
        "variables": {"id": cliente_id},
    }
    try:
        r = httpx.post(
            settings.ms1_url,
            json=query,
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        r.raise_for_status()
        return (r.json().get("data") or {}).get("cliente")
    except httpx.HTTPError as e:
        log.warning("MS1 obtener_cliente fallo (best-effort): %s", e)
        return None


# CU-05: registra el ingreso asociado al servicio en MS1. Best-effort.
def registrar_ingreso(
    encomienda_ref: str, servicio_ref: str | None, monto: float | None, token: str
) -> bool:
    if not settings.ms1_url or monto is None:
        return False
    mutation = {
        "query": "mutation($input: IngresoInput!){ registrarIngreso(input:$input){ id } }",
        "variables": {
            "input": {
                "encomiendaRef": encomienda_ref,
                "servicioId": servicio_ref,
                "monto": monto,
            }
        },
    }
    try:
        r = httpx.post(
            settings.ms1_url,
            json=mutation,
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        r.raise_for_status()
        return "errors" not in r.json()
    except httpx.HTTPError as e:
        log.warning("MS1 registrar_ingreso fallo (best-effort): %s", e)
        return False
