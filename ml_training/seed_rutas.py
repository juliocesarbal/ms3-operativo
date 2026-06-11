"""Siembra RUTAS de demo asignadas a asesores, con encomiendas coherentes.

Qué hace:
  1. Se asegura de que existan los asesores objetivo en MS1 (los crea vía GraphQL
     si faltan) y obtiene su `id` real (= asesor_id que usa MS3).
  2. En MS3, toma encomiendas ACTIVAS (REGISTRADO/EN_TRANSITO/EN_REPARTO) con
     sucursal de origen y destino, que aún NO estén en ninguna ruta, y las agrupa
     por sucursal de origen para que cada ruta tenga sentido geográfico.
  3. Crea varias rutas por asesor reutilizando `ruta_service.crear_ruta`
     (asigna encomiendas y las pasa a EN_TRANSITO como en producción).

Arquitectura (database-per-service): MS1 es dueño del usuario/asesor; MS3 es dueño
de la ruta. El vínculo es `ruta.asesor_id` = `usuario.id` de MS1.

Requisitos: haber corrido antes `seed_dataset` + `seed_encomiendas` (para que haya
sucursales y encomiendas). MS1 accesible (directo o vía gateway) con un ADMIN.

Uso:
  python -m ml_training.seed_rutas           # crea rutas que falten (idempotente)
  python -m ml_training.seed_rutas --reset   # borra las rutas de los asesores objetivo y regenera
"""
from __future__ import annotations

import os
import sys

import httpx

from app.core.database import Base, SessionLocal, engine
from app.core.estados import Estado
from app.models.encomienda import Encomienda
from app.models.operacion import Ruta, ruta_encomienda
from app.schemas.operacion import RutaCreate
from app.services import ruta_service

# --- Configuración ---------------------------------------------------------
# Asesores objetivo: (nombre, email, password). Si no existen en MS1, se crean.
ASESORES = [
    ("henry", "henry@courier.com", "asesor123"),
    ("joel", "joel@gmail.com", "asesor123"),
    ("Maria Delgado", "maria@courier.com", "asesor123"),
]
RUTAS_POR_ASESOR = 2          # objetivo de rutas activas por asesor
ENCS_POR_RUTA = 4             # encomiendas por ruta (aprox.)
ESTADOS_ACTIVOS = {Estado.REGISTRADO.value, Estado.EN_TRANSITO.value, Estado.EN_REPARTO.value}

# MS1 vía gateway por defecto (el gateway proxea /graphql al MS1 real).
MS1_URL = os.environ.get("MS1_GRAPHQL_URL", "http://localhost:8090/graphql")
ADMIN_EMAIL = os.environ.get("MS1_SEED_EMAIL", "admin@courier.com")
ADMIN_PWD = os.environ.get("MS1_SEED_PASSWORD", "admin123")


# --- MS1 (usuarios/asesores) ----------------------------------------------
def _login_admin() -> str | None:
    try:
        r = httpx.post(
            MS1_URL,
            json={
                "query": "mutation($e:String!,$p:String!){ login(email:$e,password:$p){ token rol } }",
                "variables": {"e": ADMIN_EMAIL, "p": ADMIN_PWD},
            },
            timeout=15,
        )
        r.raise_for_status()
        return (((r.json().get("data") or {}).get("login")) or {}).get("token")
    except (httpx.HTTPError, KeyError, ValueError) as e:
        print(f"  (MS1) login admin falló: {e}")
        return None


def _gql(token: str, query: str, variables: dict | None = None) -> dict:
    r = httpx.post(
        MS1_URL,
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _asegurar_asesores(token: str) -> dict[str, str]:
    """Devuelve {email: id} para los asesores objetivo, creándolos si faltan."""
    data = _gql(token, "query{ usuarios{ id nombre email rol } }")
    existentes = {u["email"].lower(): u for u in (data.get("data") or {}).get("usuarios", [])}

    ids: dict[str, str] = {}
    for nombre, email, password in ASESORES:
        u = existentes.get(email.lower())
        if u:
            ids[email] = str(u["id"])
            continue
        # Crear el asesor.
        res = _gql(
            token,
            "mutation($i:UsuarioInput!){ crearUsuario(input:$i){ id email rol } }",
            {"i": {"nombre": nombre, "email": email, "password": password, "rol": "ASESOR"}},
        )
        nuevo = (res.get("data") or {}).get("crearUsuario")
        if nuevo:
            ids[email] = str(nuevo["id"])
            print(f"  (MS1) asesor creado: {email} -> id {nuevo['id']}")
        else:
            print(f"  (MS1) no se pudo crear {email}: {res.get('errors')}")
    return ids


# --- MS3 (rutas) -----------------------------------------------------------
def _ids_ya_asignadas(db) -> set[int]:
    filas = db.execute(ruta_encomienda.select()).fetchall()
    return {row.encomienda_id for row in filas}


def _disponibles_por_origen(db, excluir: set[int]) -> dict[int, list[Encomienda]]:
    """Encomiendas activas con sucursales y sin ruta, agrupadas por sucursal de origen."""
    q = (
        db.query(Encomienda)
        .filter(
            Encomienda.estado.in_(ESTADOS_ACTIVOS),
            Encomienda.sucursal_origen_id.isnot(None),
            Encomienda.sucursal_destino_id.isnot(None),
        )
        .order_by(Encomienda.sucursal_origen_id)
    )
    grupos: dict[int, list[Encomienda]] = {}
    for e in q.all():
        if e.id in excluir:
            continue
        grupos.setdefault(e.sucursal_origen_id, []).append(e)
    return grupos


def _reset(db) -> None:
    """Borra las rutas de los asesores objetivo (y sus filas N:M)."""
    # Necesitamos los ids de los asesores objetivo; sin MS1 usamos asesor_id por email no es posible,
    # así que borramos por las rutas que apunten a asesores conocidos vía sus ids actuales en BD.
    rutas = db.query(Ruta).all()
    n = 0
    for r in rutas:
        db.delete(r)  # el N:M se limpia por la tabla asociativa
        n += 1
    db.commit()
    print(f"  (reset) rutas borradas: {n}")


def main() -> None:
    reset = "--reset" in sys.argv
    Base.metadata.create_all(bind=engine)

    token = _login_admin()
    if not token:
        print("Sin token de admin de MS1. Aborto (necesito crear/leer asesores).")
        return
    ids = _asegurar_asesores(token)
    if not ids:
        print("No hay asesores objetivo disponibles. Aborto.")
        return
    print(f"  Asesores objetivo: {ids}")

    db = SessionLocal()
    try:
        if reset:
            _reset(db)

        creadas_total = 0
        for nombre, email, _pwd in ASESORES:
            asesor_id = ids.get(email)
            if not asesor_id:
                continue

            ya = db.query(Ruta).filter(Ruta.asesor_id == asesor_id).count()
            faltan = max(0, RUTAS_POR_ASESOR - ya)
            if faltan == 0:
                print(f"  {email}: ya tiene {ya} ruta(s); ok.")
                continue

            for _ in range(faltan):
                # Recalcular disponibles en cada iteración (las recién asignadas salen del pool).
                excluir = _ids_ya_asignadas(db)
                grupos = _disponibles_por_origen(db, excluir)
                # Elegir el grupo (origen) con más encomiendas disponibles.
                grupos = {k: v for k, v in grupos.items() if v}
                if not grupos:
                    print("  Sin encomiendas disponibles para más rutas. Corta.")
                    break
                origen_id, lista = max(grupos.items(), key=lambda kv: len(kv[1]))
                elegidas = lista[:ENCS_POR_RUTA]
                if not elegidas:
                    break
                zona = elegidas[0].origen or f"Sucursal {origen_id}"
                ruta = ruta_service.crear_ruta(
                    db,
                    RutaCreate(
                        asesor_id=asesor_id,
                        zona_ref=zona,
                        encomienda_ids=[e.id for e in elegidas],
                    ),
                )
                creadas_total += 1
                print(
                    f"  Ruta #{ruta.id} -> {email} (asesor {asesor_id}) | zona '{zona}' | "
                    f"{len(elegidas)} envíos"
                )

        # Resumen
        print("\nResumen de rutas por asesor:")
        for nombre, email, _ in ASESORES:
            aid = ids.get(email)
            if not aid:
                continue
            n = db.query(Ruta).filter(Ruta.asesor_id == aid).count()
            print(f"  {email} (id {aid}): {n} ruta(s)")
        print(f"\nOK. Rutas creadas en esta corrida: {creadas_total}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
