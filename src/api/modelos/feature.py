from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Feature(BaseModel):
    """Entrada del catálogo global de features (señales)."""

    señal_id: str
    source: str
    categoria: str | None = None
    status_registro: str  # 'incompleto' | 'con_cobertura'
    label: str | None = None
    sublabel: str | None = None
    color: str | None = None
    icon_cls: str | None = None
    agg_fn: str | None = None
    display_mode: str | None = None
    canonical_type: str | None = None
    fallback_señal_id: str | None = None


class EstadoFeature(BaseModel):
    """Estado de una feature para una ubicación concreta (activacion_señales)."""

    señal_id: str
    ubicacion_id: str
    status: str  # 'active' | 'contexto' | 'inactive'
    periodicidad: str | None = None


class CambiarEstadoFeature(BaseModel):
    """Body del PATCH para cambiar el status de una feature."""

    status: Literal["active", "contexto", "inactive"]
