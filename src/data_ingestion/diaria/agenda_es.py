"""
Prefetch agenda municipal — datos.gob.es / ayuntamientos ES.

Escribe en store_features_ext:
  ev_rank_municipal  (0-100)
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.data_ingestion.prefetch._common import (
    EVENTS_DATE_FROM,
    EVENTS_HORIZON,
    get_active_locations,
    is_fresh,
    write_calendario_org,
    write_ev_features,
    write_sync_marker,
)
from src.data_processing.fuentes_eventos.agenda_es import fetch_agenda_ciudad

SOURCE = "agenda_es"
_SOURCE = SOURCE


def _run_one(loc: dict, verbose: bool) -> int:
    uuid = loc["uuid"]
    ciudad = loc["city"]
    pais_codigo = loc["pais_codigo"]
    date_from = EVENTS_DATE_FROM
    date_to = date.today() + timedelta(days=EVENTS_HORIZON)

    if not ciudad:
        if verbose:
            print(f"  [agenda_es] {loc['nombre']}: sin ciudad configurada — omitido")
        write_sync_marker(uuid, _SOURCE)
        return 0

    events = fetch_agenda_ciudad(ciudad, date_from, date_to)

    daily: dict[date, dict] = {}
    raw_rows: list[dict] = []
    for ev in events:
        d = ev["fecha"]
        if d not in daily:
            daily[d] = {"ev_rank_municipal": 0}
        daily[d]["ev_rank_municipal"] = max(daily[d]["ev_rank_municipal"], ev["score"])
        raw_rows.append(
            {
                "evento_key": "evento_municipal",
                "fecha_inicio": d,
                "fecha_fin": d,
                "fuente": "agenda_municipal",
                "source_key": f"muni:{uuid}:{ev['source_key']}",
                "metadata": {"titulo": ev["titulo"], "categoria": ev["categoria"]},
            }
        )

    write_ev_features(uuid, daily)
    write_calendario_org(uuid, raw_rows, pais_codigo)
    write_sync_marker(uuid, _SOURCE)

    n = len(daily)
    if verbose:
        print(f"  [agenda_es] {loc['nombre']}: {n}d con eventos municipales")
    return n


def run(
    location_uuid: str | None = None,
    max_age_hours: float = 6,
    verbose: bool = True,
) -> dict[str, int]:
    locations = get_active_locations(location_uuid)
    stats: dict[str, int] = {}

    for loc in locations:
        uuid = loc["uuid"]
        if is_fresh(uuid, _SOURCE, max_age_hours):
            if verbose:
                print(f"  [agenda_es] {loc['nombre']}: omitido (datos < {max_age_hours:.0f}h)")
            stats[uuid] = 0
            continue
        try:
            stats[uuid] = _run_one(loc, verbose)
        except Exception as e:
            if verbose:
                print(f"  [agenda_es] {loc['nombre']}: ERROR — {e}")
            stats[uuid] = 0

    return stats


if __name__ == "__main__":
    from src.data_ingestion.prefetch._common import make_parser

    args = make_parser("agenda municipal (datos.gob.es)").parse_args()
    run(
        location_uuid=args.location,
        max_age_hours=0 if args.force else args.max_age,
        verbose=not args.quiet,
    )
