"""
Paquete de ingestores diarios de señales de contexto.

Convención por módulo:
  SOURCE: str   — clave de fuente (coincide con feature_registry.source)
  run(...)      — función principal de ingesta → dict[str, int]

Añadir una señal nueva:
  1. Crear el script aquí con SOURCE y run().
  2. Nada más — el scanner lo descubre automáticamente.
"""

from __future__ import annotations

import importlib
import pkgutil
import types
from pathlib import Path


def cargar_modulos() -> dict[str, types.ModuleType]:
    """Devuelve {SOURCE: module} para todos los módulos del paquete."""
    result: dict[str, types.ModuleType] = {}
    pkg_dir = Path(__file__).parent
    for _, modname, _ in pkgutil.iter_modules([str(pkg_dir)]):
        try:
            mod = importlib.import_module(f"src.data_ingestion.diaria.{modname}")
            source = getattr(mod, "SOURCE", None)
            if source and callable(getattr(mod, "run", None)):
                result[source] = mod
        except Exception:
            pass
    return result
