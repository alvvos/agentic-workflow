"""Servidor FastAPI — fábrica de la app y punto de arranque."""

from __future__ import annotations

from fastapi import FastAPI

from src.api.rutas import features, fuentes, salud, ubicaciones


def crear_app() -> FastAPI:
    app = FastAPI(
        title="Agentic Workflow API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.include_router(salud.router)
    app.include_router(ubicaciones.router)
    app.include_router(fuentes.router)
    app.include_router(features.router)
    return app


app = crear_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.servidor:app", host="0.0.0.0", port=8001, reload=True)
