from pydantic import BaseModel


class EtiquetaIA(BaseModel):
    label: str
    score: float


class AnalizarFotoOut(BaseModel):
    clase: str  # SIN_DAÑO | POSIBLE_DAÑO | ETIQUETA_ILEGIBLE
    confianza: float
    probabilidades: dict[str, float]
    incidencia_creada: bool = False
    tracking: str | None = None
    # Origen del analisis: HUGGINGFACE | LOCAL. Y etiquetas crudas del modelo
    # externo (lo que "vio" la IA), para mostrarlas en la app.
    fuente: str = "LOCAL"
    etiquetas: list[EtiquetaIA] = []
