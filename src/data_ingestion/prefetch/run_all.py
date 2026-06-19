"""
Orquestador — ejecuta todos los prefetch en paralelo (un worker por source).

El tiempo total = max(tiempo_source) en lugar de sum(tiempo_source).
ev_rank_total se recalcula al final, una vez que todos los sources han escrito.

Uso:
    python -m src.data_ingestion.prefetch.run_all
    python -m src.data_ingestion.prefetch.run_all --location UUID
    python -m src.data_ingestion.prefetch.run_all --skip thesportsdb --skip ticketmaster
    python -m src.data_ingestion.prefetch.run_all --only weather
    python -m src.data_ingestion.prefetch.run_all --force          # max-age 0
    python -m src.data_ingestion.prefetch.run_all --max-age 24
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.data_ingestion.prefetch import (
    weather, open_holidays, ticketmaster, thesportsdb, agenda_es, cruceros,
)
from src.data_ingestion.prefetch._common import (
    get_active_locations, update_ev_rank_total,
    EVENTS_DATE_FROM, EVENTS_HORIZON,
)

# geo no se incluye: requiere entrega manual de datos Esri (sin fetch HTTP).
SOURCES: dict[str, object] = {
    'weather':       weather,
    'open_holidays': open_holidays,
    'ticketmaster':  ticketmaster,
    'thesportsdb':   thesportsdb,
    'agenda_es':     agenda_es,
    'cruceros':      cruceros,
}

_EVENT_SOURCES = {'open_holidays', 'ticketmaster', 'thesportsdb', 'agenda_es'}


def run(
    location_uuid: str | None = None,
    skip:          set[str] | None = None,
    only:          set[str] | None = None,
    max_age_hours: float = 6,
    verbose:       bool = True,
) -> dict[str, dict[str, int]]:
    """
    Ejecuta los sources seleccionados en paralelo.
    Retorna {source_name: {location_uuid: n_days}}.
    """
    def log(msg: str) -> None:
        if verbose:
            print(msg)

    active = set(SOURCES)
    if only:
        active &= only
    if skip:
        active -= skip

    locations = get_active_locations(location_uuid)
    if not locations:
        log("[!] Sin locations activas.")
        return {}

    width = min(60, 72)
    log(f"\n{'─'*width}")
    log(f"  prefetch/run_all — {len(locations)} location(s)  |  sources: {', '.join(sorted(active))}")
    log(f"  max-age: {max_age_hours:.0f}h  ({'forzar descarga' if max_age_hours == 0 else 'skip si más reciente'})")
    log(f"{'─'*width}")

    t0 = time.time()
    results: dict[str, dict[str, int]] = {}

    with ThreadPoolExecutor(max_workers=len(active)) as pool:
        futures = {
            pool.submit(
                SOURCES[name].run,          # type: ignore[attr-defined]
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

    # Recalcular ev_rank_total si algún source de eventos corrió
    ran_event_sources = active & _EVENT_SOURCES
    if ran_event_sources:
        date_to = date.today() + timedelta(days=EVENTS_HORIZON)
        for loc in locations:
            update_ev_rank_total(loc['uuid'], EVENTS_DATE_FROM, date_to)

    elapsed = time.time() - t0
    log(f"\n{'─'*width}")
    log(f"  Completado en {elapsed:.0f}s")
    log(f"{'─'*width}\n")

    return results


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Prefetch completo (todos los sources en paralelo)')
    parser.add_argument('--location', metavar='UUID',  help='Procesar solo esta location')
    parser.add_argument('--skip',  action='append', default=[], metavar='SOURCE',
                        choices=list(SOURCES), help='Excluir este source (repetible)')
    parser.add_argument('--only',  action='append', default=[], metavar='SOURCE',
                        choices=list(SOURCES), help='Incluir solo este source (repetible)')
    parser.add_argument('--max-age', type=float, default=6, metavar='HORAS',
                        help='Skip si datos < N horas (default: 6). 0 = siempre descargar')
    parser.add_argument('--force',   action='store_true', help='Fuerza descarga (--max-age 0)')
    parser.add_argument('--quiet',   action='store_true')
    args = parser.parse_args()

    run(
        location_uuid=args.location,
        skip=set(args.skip)  or None,
        only=set(args.only)  or None,
        max_age_hours=0 if args.force else args.max_age,
        verbose=not args.quiet,
    )
