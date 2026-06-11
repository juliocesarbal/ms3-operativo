import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import Base, engine
from app import models  # noqa: F401  (registra los modelos en Base.metadata)
from app.routers import (
    blockchain,
    encomiendas,
    entregas,
    ia,
    incidentes,
    ml,
    notificaciones,
    reportes,
    ruta,
    rutas,
    sucursales,
    tracking,
)

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crea las tablas si no existen (MVP). En produccion: Alembic.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="MS3 - Operativo, Inteligente y Logistico",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/ops/health", tags=["health"])
def health():
    return {"status": "MS3 Operativo OK"}


app.include_router(encomiendas.router)
app.include_router(tracking.router)
app.include_router(sucursales.router)
app.include_router(incidentes.router)
app.include_router(rutas.router)
app.include_router(entregas.router)
app.include_router(ml.router)
app.include_router(ruta.router)
app.include_router(ia.router)
app.include_router(reportes.router)
app.include_router(blockchain.router)
app.include_router(notificaciones.router)
