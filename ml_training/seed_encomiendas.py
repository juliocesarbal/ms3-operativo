"""Materializa encomiendas OPERATIVAS en el MS3 para que la vista "Encomiendas"
no esté casi vacía. Cada encomienda referencia un cliente REAL de MS1.

Diferencia clave con `seed_dataset.py`:
  - `seed_dataset.py`  -> llena `envio_historico` (dataset ML/BI, ~5000 filas).
  - `seed_encomiendas.py` (este) -> llena `encomienda` (tabla operativa que se ve
    en la UI con tracking, estados y trazabilidad), ~300 filas realistas.

Arquitectura (database-per-service): MS1 es DUEÑO del cliente. Este seed pide los
clientes a MS1 por API (login admin -> query clientes) para obtener el `cliente_id`
REAL y cachear `cliente_nombre`/`cliente_direccion` en la encomienda (patrón del
README §4.1). Si MS1 no está accesible, cae a la lista canónica de nombres
(coincide con MS1 por seed) con cliente_id sintético; las vistas igual funcionan
porque muestran `cliente_nombre`.

Las encomiendas sembradas NO registran evento en blockchain (es histórico de
relleno). Las que se crean luego por la UI sí lo hacen, sin cambios.

Requisitos: correr antes `python -m ml_training.seed_dataset` (necesita sucursales
y ruta_cache). Para vincular cliente_id real: MS1 corriendo + `npm run seed` hecho.

Uso:
  python -m ml_training.seed_encomiendas          # siembra si no hay sembradas
  python -m ml_training.seed_encomiendas --reset  # borra las sembradas y regenera
"""
from __future__ import annotations

import os
import secrets
import sys
from datetime import timedelta

import httpx
import numpy as np

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.estados import Estado
from app.models.encomienda import Encomienda, EstadoHistorial, utcnow
from app.models.sucursal import Sucursal
from app.services import geo
from ml_training._geo import TIPOS_SERVICIO

N_ENCOMIENDAS = 300
SEED = 7
PREFIJO = "ENV-"  # marca las encomiendas sembradas (separa de las reales TRK-)

# Probabilidad por servicio (igual que el histórico) y costo base por servicio.
SERVICIO_P = [0.30, 0.40, 0.10, 0.20]  # DOCUMENTO, PAQUETE_NORMAL, CARGA_PESADA, EXPRESS
COSTO_BASE = {"DOCUMENTO": 15.0, "PAQUETE_NORMAL": 35.0, "CARGA_PESADA": 120.0, "EXPRESS": 60.0}

# Distribución de estados (operación realista: la mayoría ya entregada).
ESTADOS_P = {
    Estado.ENTREGADO: 0.50,
    Estado.EN_TRANSITO: 0.15,
    Estado.EN_REPARTO: 0.10,
    Estado.REGISTRADO: 0.08,
    Estado.RETRASADO: 0.09,
    Estado.CON_INCIDENCIA: 0.08,
}

# Secuencia de estados (camino de historial) que lleva a cada estado final.
# Respeta las transiciones válidas de app/core/estados.py.
CAMINO = {
    Estado.REGISTRADO: [Estado.REGISTRADO],
    Estado.EN_TRANSITO: [Estado.REGISTRADO, Estado.EN_TRANSITO],
    Estado.EN_REPARTO: [Estado.REGISTRADO, Estado.EN_TRANSITO, Estado.EN_REPARTO],
    Estado.ENTREGADO: [Estado.REGISTRADO, Estado.EN_TRANSITO, Estado.EN_REPARTO, Estado.ENTREGADO],
    Estado.RETRASADO: [Estado.REGISTRADO, Estado.EN_TRANSITO, Estado.RETRASADO],
    Estado.CON_INCIDENCIA: [Estado.REGISTRADO, Estado.EN_TRANSITO, Estado.CON_INCIDENCIA],
}


# --- Roster de clientes: pide a MS1 (fuente de verdad) o cae a la lista canónica ---
def _roster_desde_ms1() -> list[tuple[str, str, str | None]] | None:
    """Devuelve [(cliente_id, nombre, direccion)] desde MS1 (GraphQL). None si falla."""
    url = os.environ.get("MS1_GRAPHQL_URL") or settings.ms1_url or "http://localhost:3001/graphql"
    email = os.environ.get("MS1_SEED_EMAIL", "admin@courier.com")
    pwd = os.environ.get("MS1_SEED_PASSWORD", "admin123")
    try:
        login = httpx.post(
            url,
            json={
                "query": "mutation($e:String!,$p:String!){ login(email:$e,password:$p){ token } }",
                "variables": {"e": email, "p": pwd},
            },
            timeout=8,
        )
        login.raise_for_status()
        token = (((login.json().get("data") or {}).get("login")) or {}).get("token")
        if not token:
            print("  (MS1) login sin token; ¿credenciales? -> uso roster canónico")
            return None
        r = httpx.post(
            url,
            json={"query": "query{ clientes{ id nombre direccion } }"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        r.raise_for_status()
        data = (r.json().get("data") or {}).get("clientes") or []
        roster = [(str(c["id"]), c["nombre"], c.get("direccion")) for c in data]
        if not roster:
            print("  (MS1) 0 clientes; ¿corriste `npm run seed`? -> uso roster canónico")
            return None
        print(f"  (MS1) {len(roster)} clientes reales -> cliente_id vinculado")
        return roster
    except (httpx.HTTPError, KeyError, ValueError) as e:
        print(f"  (MS1) inaccesible ({e}); uso roster canónico (cliente_id sintético)")
        return None


def _roster_canonico() -> list[tuple[str, str, str | None]]:
    from ml_training.seed_dataset import CLIENTES

    return [(str(i + 1), nombre, None) for i, nombre in enumerate(CLIENTES)]


def _eliminar_sembradas(db) -> int:
    sembradas = db.query(Encomienda).filter(Encomienda.tracking_code.like(f"{PREFIJO}%")).all()
    n = len(sembradas)
    for enc in sembradas:  # db.delete dispara el cascade a estado_historial
        db.delete(enc)
    db.commit()
    print(f"  (reset) encomiendas sembradas borradas: {n}")
    return n


def _tracking_unico(db, vistos: set[str]) -> str:
    for _ in range(20):
        code = PREFIJO + secrets.token_hex(3).upper()  # ENV-AB12CD
        if code in vistos:
            continue
        if not db.query(Encomienda).filter_by(tracking_code=code).first():
            vistos.add(code)
            return code
    raise RuntimeError("No se pudo generar un tracking único")


def main() -> None:
    reset = "--reset" in sys.argv
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        sucs = db.query(Sucursal).all()
        if len(sucs) < 2:
            print("No hay sucursales. Corré primero: python -m ml_training.seed_dataset")
            return

        if reset:
            _eliminar_sembradas(db)

        ya = db.query(Encomienda).filter(Encomienda.tracking_code.like(f"{PREFIJO}%")).count()
        if ya > 0:
            print(f"Ya hay {ya} encomiendas sembradas. Usá --reset para regenerar.")
            return

        roster = _roster_desde_ms1() or _roster_canonico()
        rng = np.random.default_rng(SEED)

        # Clientes ponderados (Zipf 1/rank): los primeros del roster envían mucho más.
        w_cli = 1.0 / np.arange(1, len(roster) + 1)
        w_cli /= w_cli.sum()

        estados = list(ESTADOS_P.keys())
        p_estados = list(ESTADOS_P.values())

        vistos: set[str] = set()
        creadas = 0
        for _ in range(N_ENCOMIENDAS):
            cli_id, cli_nombre, cli_dir = roster[int(rng.choice(len(roster), p=w_cli))]

            o = sucs[int(rng.integers(0, len(sucs)))]
            d = sucs[int(rng.integers(0, len(sucs)))]
            if o.id == d.id:
                d = sucs[(sucs.index(d) + 1) % len(sucs)]  # forzar inter-ciudad
            distancia = geo.distancia_sucursales(db, o.id, d.id)

            servicio = str(rng.choice(TIPOS_SERVICIO, p=SERVICIO_P))
            peso = float(np.clip(rng.gamma(2.0, 3.0), 0.1, 60))
            costo = round(COSTO_BASE[servicio] + peso * 2.0 + (distancia or 0) * 0.08, 2)
            riesgo = str(rng.choice(["BAJO", "MEDIO", "ALTO"], p=[0.50, 0.30, 0.20]))

            estado_final = estados[int(rng.choice(len(estados), p=p_estados))]
            fecha_reg = utcnow() - timedelta(
                days=int(rng.integers(0, 120)), minutes=int(rng.integers(0, 24 * 60))
            )

            enc = Encomienda(
                tracking_code=_tracking_unico(db, vistos),
                cliente_id=cli_id,
                cliente_nombre=cli_nombre,
                cliente_direccion=cli_dir,
                origen=o.ciudad,
                destino=d.ciudad,
                peso=round(peso, 2),
                servicio_ref=servicio,
                zona_ref=None,  # operación suc->suc, sin zona de entrega
                sucursal_origen_id=o.id,
                sucursal_destino_id=d.id,
                distancia=distancia,
                estado=estado_final.value,
                costo=costo,
                riesgo_retraso=riesgo,
                created_at=fecha_reg,
            )
            db.add(enc)
            db.flush()  # asigna enc.id

            # Historial coherente: cada paso ocurre algunas horas después del anterior.
            t = fecha_reg
            for paso in CAMINO[estado_final]:
                db.add(
                    EstadoHistorial(
                        encomienda_id=enc.id,
                        estado=paso.value,
                        fecha=t,
                        ubicacion=o.ciudad if paso == Estado.REGISTRADO else d.ciudad,
                    )
                )
                t = t + timedelta(hours=float(rng.uniform(4, 36)))
            creadas += 1

        db.commit()
        # Resumen por estado para verificar de un vistazo.
        resumen = {
            e.value: db.query(Encomienda)
            .filter(Encomienda.tracking_code.like(f"{PREFIJO}%"), Encomienda.estado == e.value)
            .count()
            for e in estados
        }
        print(f"OK. Encomiendas sembradas: {creadas}  ->  {resumen}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
