"""Chatbot BI (CU-16): interpreta un prompt en lenguaje natural con Claude y
extrae los parámetros del informe pedido, mediante tool use.

Ej: "exportame un informe de Ingresos del departamento de Santa Cruz, entre
febrero y marzo, en pdf" -> el modelo llama la tool `generar_reporte` con:
{tipo:"INGRESOS", formato:"PDF", desde:"<año>-02", hasta:"<año>-03",
 departamento:"Santa Cruz"}

Solo se usa Claude para ENTENDER el pedido (extraer parámetros). La consulta de
datos y la generación del archivo las hace el backend (bi_data + bi_export), sin
exponer la BD al modelo. Modelo barato/rápido: claude-haiku-4-5.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.core.config import settings

log = logging.getLogger("ms3.bi_chat")


class ChatNoConfigurado(RuntimeError):
    """Se levanta si falta CLAUDE_API_KEY."""


_client = None


def _get_client():
    """Cliente Anthropic singleton (reusa la conexión HTTP entre requests)."""
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.claude_api_key, max_retries=2)
    return _client


# --- Definición de la tool que el modelo debe llamar ---
TOOL_GENERAR_REPORTE: dict[str, Any] = {
    "name": "generar_reporte",
    "description": (
        "Genera y exporta un informe de Business Intelligence del courier. "
        "Llama esta herramienta con los parámetros extraídos del pedido del usuario."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tipo": {
                "type": "string",
                "enum": ["INGRESOS", "OPERACION", "RANKINGS", "ZONAS"],
                "description": (
                    "Tipo de reporte. INGRESOS=facturación/ingresos por mes y servicio "
                    "(empresarial). OPERACION=envíos, distancia, % a tiempo, por zona/servicio/riesgo. "
                    "RANKINGS=top clientes/servicios/zonas/rutas. ZONAS=clasificación de zonas e "
                    "incidentes."
                ),
            },
            "formato": {
                "type": "string",
                "enum": ["PDF", "EXCEL", "CSV"],
                "description": "Formato de exportación. Si no se especifica, usar PDF.",
            },
            "desde": {
                "type": "string",
                "description": "Mes inicial inclusive en formato YYYY-MM (ej '2026-02'). Omitir si no se pide rango.",
            },
            "hasta": {
                "type": "string",
                "description": "Mes final inclusive en formato YYYY-MM (ej '2026-03'). Omitir si no se pide rango.",
            },
            "dia_semana": {
                "type": "integer",
                "minimum": 0,
                "maximum": 6,
                "description": "0=lunes ... 6=domingo. Solo si el usuario lo menciona.",
            },
            "hora_desde": {"type": "integer", "minimum": 0, "maximum": 23},
            "hora_hasta": {"type": "integer", "minimum": 0, "maximum": 23},
            "tipo_servicio": {
                "type": "string",
                "enum": ["DOCUMENTO", "PAQUETE_NORMAL", "CARGA_PESADA", "EXPRESS"],
                "description": "Filtrar por un tipo de servicio. Solo si se menciona.",
            },
            "riesgo": {
                "type": "string",
                "enum": ["BAJO", "MEDIO", "ALTO"],
                "description": "Filtrar por nivel de riesgo de retraso. Solo si se menciona.",
            },
            "ciudades": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Ciudades a segmentar (una sucursal = una ciudad). Ej ['Santa Cruz','Cochabamba']."
                ),
            },
            "departamento": {
                "type": "string",
                "description": (
                    "Departamento a segmentar (ej 'Santa Cruz'). Incluye todas sus ciudades/sucursales."
                ),
            },
        },
        "required": ["tipo", "formato"],
    },
}


def _system_prompt() -> str:
    hoy = date.today()
    return (
        "Eres el asistente de reportes (BI) de un sistema de courier en Bolivia. "
        "El usuario te pide informes en lenguaje natural y tú extraes los parámetros "
        "y llamas SIEMPRE a la herramienta `generar_reporte`. "
        f"La fecha de hoy es {hoy.isoformat()} (usa este año si el usuario da solo el mes). "
        "Reglas: los meses van en formato YYYY-MM. 'una sucursal es una ciudad': si el "
        "usuario menciona una ciudad o departamento (ej 'departamento de Santa Cruz'), "
        "ponlo en `departamento` o `ciudades`. Si no se especifica formato, usa PDF. "
        "Si el pedido es ambiguo sobre el tipo de reporte, elige el más cercano por contexto "
        "(ingresos→INGRESOS, envíos/operación→OPERACION, mejores/top→RANKINGS, zonas/incidentes→ZONAS). "
        "No inventes filtros que el usuario no pidió."
    )


def interpretar(prompt: str) -> dict[str, Any]:
    """Manda el prompt a Claude y devuelve los parámetros del reporte.

    Devuelve dict con los args de la tool (incluye 'tipo' y 'formato').
    Lanza ChatNoConfigurado si falta la API key.
    """
    if not settings.claude_api_key:
        raise ChatNoConfigurado("CLAUDE_API_KEY no configurado")

    client = _get_client()
    # Timeout amplio + reintentos: ante "Connection error" transitorio reintenta.
    resp = client.with_options(timeout=20.0, max_retries=2).messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=_system_prompt(),
        tools=[TOOL_GENERAR_REPORTE],
        tool_choice={"type": "tool", "name": "generar_reporte"},
        messages=[{"role": "user", "content": prompt}],
    )

    for block in resp.content:
        if block.type == "tool_use" and block.name == "generar_reporte":
            params = dict(block.input)
            params.setdefault("tipo", "OPERACION")
            params.setdefault("formato", "PDF")
            return params

    # Fallback defensivo: si el modelo no llamó la tool (no debería con tool_choice forzado).
    log.warning("Claude no devolvió tool_use; usando defaults")
    return {"tipo": "OPERACION", "formato": "PDF"}


def resumen_humano(params: dict[str, Any], reporte: dict[str, Any]) -> str:
    """Frase corta que el chatbot muestra al usuario describiendo lo generado."""
    partes = [f"Informe de {reporte.get('titulo', params.get('tipo'))}"]
    if params.get("desde") or params.get("hasta"):
        d, h = params.get("desde", "inicio"), params.get("hasta", "hoy")
        partes.append(f"de {d} a {h}")
    seg = reporte.get("segmento_sucursales") or []
    if seg:
        partes.append(f"segmentado por {', '.join(seg)}")
    elif params.get("departamento"):
        partes.append(f"({params['departamento']} no coincidió con sucursales)")
    partes.append(f"en {params.get('formato', 'PDF')}")
    return " ".join(partes) + "."
