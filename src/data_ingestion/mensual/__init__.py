"""
Paquete de ingestores mensuales de señales de contexto.

Convención por módulo:
  SOURCE: str            — clave de fuente (coincide con feature_registry.source)
  run(...)               — interfaz nightly: respeta max_age_hours, devuelve {uuid: n}
  CATALOG_ENTRY: dict    — entrada para Context Scout (omitir si no es señal de contexto)
  CATALOG_PAISES: list[str]  — países donde aplica la señal ([] = todos)

Añadir una señal nueva:
  1. Crear el script aquí con SOURCE, run(), CATALOG_ENTRY, CATALOG_PAISES.
  2. Nada más — el scanner lo descubre automáticamente.
"""

from __future__ import annotations

import importlib
import pkgutil
import types
from pathlib import Path


def cargar_modulos() -> dict[str, types.ModuleType]:
    """Devuelve {SOURCE: module} para todos los módulos que exponen SOURCE y run()."""
    result: dict[str, types.ModuleType] = {}
    pkg_dir = Path(__file__).parent
    for _, modname, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if modname.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"src.data_ingestion.mensual.{modname}")
            source = getattr(mod, "SOURCE", None)
            if source and callable(getattr(mod, "run", None)):
                result[source] = mod
        except Exception:
            pass
    return result


def cargar_ingestores():
    """Backward-compat: devuelve {SOURCE: sync_fn}. Preferir cargar_modulos()."""
    result = {}
    pkg_dir = Path(__file__).parent
    for _, modname, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if modname.startswith("_"):
            continue
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
        if modname.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"src.data_ingestion.mensual.{modname}")
            entry = getattr(mod, "CATALOG_ENTRY", None)
            paises = getattr(mod, "CATALOG_PAISES", [])
            if entry is not None and (not paises or pais in paises):
                result.append(entry)
        except Exception:
            pass
    return result


def sync_all(
    location_uuid: str | None = None,
    max_age_hours: float = 168,
    verbose: bool = True,
) -> dict[str, dict[str, int]]:
    """
    Ejecuta todos los ingestores mensuales secuencialmente.
    Cada módulo respeta su propio max_age_hours para auto-throttling.
    Por defecto 168h (semanal) — apropiado para datos con lag de días/semanas.

    Retorna {source_name: {location_uuid: n_rows}}.
    """

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    sources = cargar_modulos()
    results: dict[str, dict[str, int]] = {}

    log(f"\n  mensual/sync_all — {len(sources)} source(s): {', '.join(sorted(sources))}")

    for name, mod in sorted(sources.items()):
        try:
            res = mod.run(  # type: ignore[attr-defined]
                location_uuid=location_uuid,
                max_age_hours=max_age_hours,
                verbose=verbose,
            )
            results[name] = res
            total = sum(res.values()) if res else 0
            log(f"  [{name}] {total} filas escritas")
        except Exception as e:
            log(f"  [!] {name}: ERROR — {e}")
            results[name] = {}

    return results
