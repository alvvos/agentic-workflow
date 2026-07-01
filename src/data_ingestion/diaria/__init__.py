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
import time
import types
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path


def cargar_modulos() -> dict[str, types.ModuleType]:
    """Devuelve {SOURCE: module} para todos los módulos del paquete que exponen SOURCE y run()."""
    result: dict[str, types.ModuleType] = {}
    pkg_dir = Path(__file__).parent
    for _, modname, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if modname.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"src.data_ingestion.diaria.{modname}")
            source = getattr(mod, "SOURCE", None)
            if source and callable(getattr(mod, "run", None)):
                result[source] = mod
        except Exception:
            pass
    return result


_EVENT_SOURCES = {"open_holidays", "ticketmaster", "thesportsdb", "agenda_es"}


def run_all(
    location_uuid: str | None = None,
    skip: set[str] | None = None,
    only: set[str] | None = None,
    max_age_hours: float = 23,
    verbose: bool = True,
) -> dict[str, dict[str, int]]:
    """
    Ejecuta todos los ingestores diarios en paralelo (un worker por source).
    Tiempo total = max(tiempo_source). ev_rank_total se recalcula al final.

    Retorna {source_name: {location_uuid: n_rows}}.
    """
    from src.data_ingestion.diaria._common import (
        EVENTS_DATE_FROM,
        EVENTS_HORIZON,
        get_active_locations,
        update_ev_rank_total,
    )

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    sources = cargar_modulos()
    active = set(sources)
    if only:
        active &= only
    if skip:
        active -= skip

    locations = get_active_locations(location_uuid)
    if not locations:
        log("[!] Sin locations activas.")
        return {}

    width = 60
    log(f"\n{'─'*width}")
    log(f"  diaria/run_all — {len(locations)} location(s)  |  sources: {', '.join(sorted(active))}")
    log(f"  max-age: {max_age_hours:.0f}h")
    log(f"{'─'*width}")

    t0 = time.time()
    results: dict[str, dict[str, int]] = {}

    with ThreadPoolExecutor(max_workers=max(1, len(active))) as pool:
        futures = {
            pool.submit(
                sources[name].run,  # type: ignore[attr-defined]
                location_uuid=location_uuid,
                max_age_hours=max_age_hours,
                verbose=verbose,
            ): name
            for name in active
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as e:
                log(f"  [!] {name}: ERROR no capturado — {e}")
                results[name] = {}

    ran_event_sources = active & _EVENT_SOURCES
    if ran_event_sources:
        date_to = date.today() + timedelta(days=EVENTS_HORIZON)
        for loc in locations:
            update_ev_rank_total(loc["uuid"], EVENTS_DATE_FROM, date_to)

    elapsed = time.time() - t0
    log(f"\n{'─'*width}")
    log(f"  Completado en {elapsed:.0f}s")
    log(f"{'─'*width}\n")

    return results


if __name__ == "__main__":
    import argparse

    sources = cargar_modulos()
    parser = argparse.ArgumentParser(
        description="Sincronización diaria completa (todos los sources en paralelo)"
    )
    parser.add_argument("--location", metavar="UUID")
    parser.add_argument("--skip", action="append", default=[], metavar="SOURCE")
    parser.add_argument("--only", action="append", default=[], metavar="SOURCE")
    parser.add_argument("--max-age", type=float, default=23, metavar="HORAS")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    run_all(
        location_uuid=args.location,
        skip=set(args.skip) or None,
        only=set(args.only) or None,
        max_age_hours=0 if args.force else args.max_age,
        verbose=not args.quiet,
    )
