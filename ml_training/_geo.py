"""Geografia de Bolivia + utilidades compartidas por el seed y el entrenamiento.

Coordenadas reales de ciudades bolivianas para que los datos sinteticos tengan
sentido espacial (distancias haversine plausibles entre sucursales).
"""
from __future__ import annotations

import math

# --- Sucursales (nodos logisticos): ciudad real -> (depto, ciudad, direccion, lat, lng) ---
SUCURSALES = [
    ("Santa Cruz - Central", "Santa Cruz", "Santa Cruz de la Sierra", "Av. Cañoto / 2do anillo", -17.7833, -63.1821),
    ("Montero", "Santa Cruz", "Montero", "Av. Circunvalación", -17.3392, -63.2514),
    ("La Paz - Central", "La Paz", "La Paz", "Av. Mariscal Santa Cruz", -16.5000, -68.1193),
    ("El Alto", "La Paz", "El Alto", "Av. 6 de Marzo", -16.5111, -68.1664),
    ("Cochabamba - Central", "Cochabamba", "Cochabamba", "Av. Heroínas", -17.3895, -66.1568),
    ("Sucre", "Chuquisaca", "Sucre", "Calle España", -19.0333, -65.2627),
    ("Tarija", "Tarija", "Tarija", "Av. Las Américas", -21.5355, -64.7296),
    ("Oruro", "Oruro", "Oruro", "Av. 6 de Octubre", -17.9833, -67.1167),
    ("Potosí", "Potosí", "Potosí", "Av. Camacho", -19.5836, -65.7531),
    ("Trinidad", "Beni", "Trinidad", "Av. 6 de Agosto", -14.8333, -64.9000),
]

# Ciudades con sub-zonas de reparto (las grandes). El resto opera solo como nodo.
CIUDADES_CON_ZONAS = [
    "Santa Cruz - Central",
    "Montero",
    "La Paz - Central",
    "El Alto",
    "Cochabamba - Central",
    "Sucre",
]

ZONA_CODIGOS = ["NORTE", "SUR", "ESTE", "OESTE", "CENTRO"]

# Desfase aproximado (en grados) de cada sector respecto al centro de la ciudad.
# ~0.03 grados ≈ 3.3 km, escala urbana realista.
ZONA_OFFSET = {
    "NORTE": (0.030, 0.0),
    "SUR": (-0.030, 0.0),
    "ESTE": (0.0, 0.030),
    "OESTE": (0.0, -0.030),
    "CENTRO": (0.0, 0.0),
}

TIPOS_SERVICIO = ["DOCUMENTO", "PAQUETE_NORMAL", "CARGA_PESADA", "EXPRESS"]

# Horas estimadas de entrega segun servicio (referencia para medir retraso).
HORAS_BASE_SERVICIO = {
    "DOCUMENTO": 24,
    "PAQUETE_NORMAL": 48,
    "CARGA_PESADA": 72,
    "EXPRESS": 12,
}

HORAS_PICO = [7, 8, 18, 19, 20]

# Arquetipos de zona para generar metricas separables (los descubre K-Means).
# (num_envios_mu, tiempo_entrega_prom_mu (h), num_incidencias_mu)
ARQUETIPOS_ZONA = {
    "ALTA_DEMANDA": (520, 24, 5),
    "RETRASOS_FRECUENTES": (150, 72, 42),
    "BAJA_DEMANDA": (40, 30, 3),
}

# --- Corredores interurbanos: carreteras REALES usadas para el traslado suc->suc ---
# La empresa solo envía de sucursal a sucursal; estos son los tramos por donde
# pasan los envíos. Cada corredor genera zonas tipo CARRETERA (puntos sobre la ruta).
CORREDORES = [
    ("Santa Cruz - Central", "Montero"),
    ("Santa Cruz - Central", "Cochabamba - Central"),
    ("Cochabamba - Central", "Oruro"),
    ("Oruro", "La Paz - Central"),
    ("La Paz - Central", "El Alto"),
    ("Oruro", "Potosí"),
    ("Potosí", "Sucre"),
    ("Cochabamba - Central", "Sucre"),
    ("Potosí", "Tarija"),
    ("Santa Cruz - Central", "Trinidad"),
]

# Arquetipos con DESGLOSE de incidencias por tipo + velocidad típica.
# mix = (trafico, bloqueo, clima, social, accidente)  -> fracciones de num_incidencias.
ARQ_URBANA = {
    "ALTA_DEMANDA": dict(num_envios=520, tiempo=24, inc=9, vel=22, mix=(0.55, 0.05, 0.05, 0.25, 0.10)),
    "MEDIA":        dict(num_envios=180, tiempo=30, inc=5, vel=26, mix=(0.50, 0.05, 0.08, 0.27, 0.10)),
    "BAJA_DEMANDA": dict(num_envios=45,  tiempo=22, inc=3, vel=30, mix=(0.45, 0.05, 0.10, 0.30, 0.10)),
}
# Tramos de carretera: BLOQUEO = propenso a bloqueos/accidentes (lento, muchas
# incidencias) -> el K-Means lo manda a RETRASOS_FRECUENTES. FLUIDA = vía rápida.
ARQ_CARRETERA = {
    "BLOQUEO": dict(num_envios=160, tiempo=70, inc=44, vel=32, mix=(0.20, 0.45, 0.15, 0.00, 0.20)),
    "FLUIDA":  dict(num_envios=130, tiempo=40, inc=7,  vel=72, mix=(0.30, 0.15, 0.30, 0.00, 0.25)),
}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distancia en km entre dos puntos GPS (formula del haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))
