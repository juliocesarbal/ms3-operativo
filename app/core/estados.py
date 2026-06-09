from enum import Enum


# Estados de una encomienda (ver README seccion 7).
class Estado(str, Enum):
    REGISTRADO = "REGISTRADO"
    EN_TRANSITO = "EN_TRANSITO"
    EN_REPARTO = "EN_REPARTO"
    ENTREGADO = "ENTREGADO"
    RETRASADO = "RETRASADO"
    CON_INCIDENCIA = "CON_INCIDENCIA"


# Flujo:
#   REGISTRADO -> EN_TRANSITO -> EN_REPARTO -> ENTREGADO
#                                    \-> RETRASADO
#                                    \-> CON_INCIDENCIA
# Se permiten transiciones de recuperacion desde RETRASADO/CON_INCIDENCIA.
TRANSICIONES: dict[Estado, set[Estado]] = {
    Estado.REGISTRADO: {Estado.EN_TRANSITO, Estado.CON_INCIDENCIA},
    Estado.EN_TRANSITO: {Estado.EN_REPARTO, Estado.RETRASADO, Estado.CON_INCIDENCIA},
    Estado.EN_REPARTO: {Estado.ENTREGADO, Estado.RETRASADO, Estado.CON_INCIDENCIA},
    Estado.RETRASADO: {Estado.EN_TRANSITO, Estado.EN_REPARTO, Estado.CON_INCIDENCIA},
    Estado.CON_INCIDENCIA: {Estado.EN_TRANSITO, Estado.EN_REPARTO, Estado.ENTREGADO},
    Estado.ENTREGADO: set(),  # terminal
}


def puede_transicionar(actual: str, nuevo: str) -> bool:
    try:
        return Estado(nuevo) in TRANSICIONES[Estado(actual)]
    except (KeyError, ValueError):
        return False
