"""
Paquete de ingestores mensuales de señales de contexto.

Convención por módulo:
  SOURCE: str            — clave de fuente (coincide con feature_registry.source)
  sync(jobs, fecha)      — función estándar de ingesta → int (filas escritas)
  CATALOG_ENTRY: dict    — entrada para Context Scout (omitir si no es señal de contexto)
  CATALOG_PAISES: list[str]  — países donde aplica la señal ([] = todos)

Añadir una señal nueva:
  1. Crear el script aquí con SOURCE, sync(), CATALOG_ENTRY, CATALOG_PAISES.
  2. Nada más — el scanner lo descubre automáticamente.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Callable


def cargar_ingestores() -> dict[str, Callable]:
    """Devuelve {SOURCE: sync_fn} para todos los módulos del paquete."""
    result: dict[str, Callable] = {}
    pkg_dir = Path(__file__).parent
    for _, modname, _ in pkgutil.iter_modules([str(pkg_dir)]):
        try:
            mod = importlib.import_module(f"src.data_ingestion.mensual.{modname}")
            source = getattr(mod, "SOURCE", None)
            sync_fn = getattr(mod, "sync", None)
            if source and callable(sync_fn):
                result[source] = sync_fn
        except Exception:
            pass
    return result


def cargar_catalog(pais: str) -> list[dict]:
    """Devuelve entradas de catálogo aplicables al país dado."""
    result: list[dict] = []
    pkg_dir = Path(__file__).parent
    for _, modname, _ in pkgutil.iter_modules([str(pkg_dir)]):
        try:
            mod = importlib.import_module(f"src.data_ingestion.mensual.{modname}")
            entry = getattr(mod, "CATALOG_ENTRY", None)
            paises = getattr(mod, "CATALOG_PAISES", [])
            if entry is not None and (not paises or pais in paises):
                result.append(entry)
        except Exception:
            pass
    return result
