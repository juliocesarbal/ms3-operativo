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


# MS1 espera servicioId (Int, FK a su tabla servicio). La encomienda guarda el
# servicio como string ("PAQUETE_NORMAL"); se mapea al nombre de MS1 y se resuelve
# su id (cacheado). Sin esto, registrarIngreso fallaba siempre (string -> Int).
SERVICIO_REF_A_NOMBRE = {
    "DOCUMENTO": "Documento",
    "PAQUETE_NORMAL": "Paquete normal",
    "CARGA_PESADA": "Carga pesada",
    "EXPRESS": "Express",
}
_servicios_cache: dict[str, int] = {}


def _resolver_servicio_id(servicio_ref: str | None, token: str) -> int | None:
    nombre = SERVICIO_REF_A_NOMBRE.get((servicio_ref or "").upper())
    if not nombre:
        return None
    if not _servicios_cache:
        try:
            r = httpx.post(
                settings.ms1_url,
                json={"query": "query{ servicios{ id nombre } }"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
            r.raise_for_status()
            for s in (r.json().get("data") or {}).get("servicios") or []:
                _servicios_cache[s["nombre"]] = int(s["id"])
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
            log.warning("MS1 servicios fetch fallo (best-effort): %s", e)
            return None
    return _servicios_cache.get(nombre)


# CU-05: registra el ingreso asociado al servicio en MS1. Best-effort.
def registrar_ingreso(
    encomienda_ref: str, servicio_ref: str | None, monto: float | None, token: str
) -> bool:
    if not settings.ms1_url or monto is None:
        return False
    servicio_id = _resolver_servicio_id(servicio_ref, token)
    if servicio_id is None:
        log.warning("MS1 registrar_ingreso: no se pudo mapear servicio '%s'", servicio_ref)
        return False
    mutation = {
        "query": "mutation($input: IngresoInput!){ registrarIngreso(input:$input){ id } }",
        "variables": {
            "input": {
                "encomiendaRef": encomienda_ref,
                "servicioId": servicio_id,
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
