from __future__ import annotations

from pydantic import BaseModel


class FuenteDisponible(BaseModel):
    """Fuente de datos disponible en el catálogo (leída de CATALOG_ENTRY de cada módulo)."""

    source: str
    categoria: str | None = None
    periodicidad: str | None = None
    descripcion: str | None = None
    url_referencia: str | None = None
    cobertura_desde: str | None = None
    latencia_dias: int | None = None
    paises: list[str] = []
    params_schema: str | None = None
    params_ejemplo: dict | None = None


class ConfigFuente(BaseModel):
    """Configuración activa de una fuente para una ubicación concreta."""

    id: int
    location_uuid: str
    source: str
    params: dict
    activo: bool


class NuevaConfigFuente(BaseModel):
    """Body del POST para configurar una fuente en una ubicación."""

    params: dict
