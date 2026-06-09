from pydantic import BaseModel


class AnalizarFotoOut(BaseModel):
    clase: str  # SIN_DAÑO | POSIBLE_DAÑO | ETIQUETA_ILEGIBLE
    confianza: float
    probabilidades: dict[str, float]
    incidencia_creada: bool = False
    tracking: str | None = None
