"""
Prefetch eventos Ticketmaster — conciertos, deportes, festivales.

Requiere TICKETMASTER_KEY en .env. Sin key → omite silenciosamente.

Escribe en store_features_ext:
  ev_rank_deportivo, ev_rank_concierto, ev_rank_festival  (0-100)
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
from src.data_processing.fuentes_eventos.ticketmaster import (
    _key,
    events_to_daily_scores,
    events_to_raw_rows,
    fetch_events_raw,
)

SOURCE = "ticketmaster"
_SOURCE = SOURCE


def _run_one(loc: dict, verbose: bool) -> int:
    uuid = loc["uuid"]
    lat, lon = loc["lat"], loc["lon"]
    date_from = EVENTS_DATE_FROM
    date_to = date.today() + timedelta(days=EVENTS_HORIZON)

    raw = fetch_events_raw(lat, lon, date_from, date_to)
    scores = events_to_daily_scores(raw)
    rows = events_to_raw_rows(raw, uuid)

    daily: dict[date, dict] = {}
    for d, cats in scores.items():
        if date_from <= d <= date_to:
            daily[d] = {
                "ev_rank_deportivo": cats.get("deportivo", 0),
                "ev_rank_concierto": cats.get("concierto", 0),
                "ev_rank_festival": cats.get("festival", 0),
            }

    write_ev_features(uuid, daily)
    write_calendario_org(uuid, rows, loc["pais_codigo"])
    write_sync_marker(uuid, _SOURCE)

    n = len(daily)
    if verbose:
        print(f"  [ticketmaster] {loc['nombre']}: {n}d con eventos  ({len(raw)} raw)")
    return n


def run(
    location_uuid: str | None = None,
    max_age_hours: float = 6,
    verbose: bool = True,
) -> dict[str, int]:
    if not _key():
        if verbose:
            print("  [ticketmaster] TICKETMASTER_KEY no configurada — omitido")
        return {}

    locations = get_active_locations(location_uuid)
    stats: dict[str, int] = {}

    for loc in locations:
        uuid = loc["uuid"]
        if is_fresh(uuid, _SOURCE, max_age_hours):
            if verbose:
                print(f"  [ticketmaster] {loc['nombre']}: omitido (datos < {max_age_hours:.0f}h)")
            stats[uuid] = 0
            continue
        try:
            stats[uuid] = _run_one(loc, verbose)
        except Exception as e:
            if verbose:
                print(f"  [ticketmaster] {loc['nombre']}: ERROR — {e}")
            stats[uuid] = 0

    return stats


if __name__ == "__main__":
    from src.data_ingestion.prefetch._common import make_parser

    args = make_parser("eventos Ticketmaster").parse_args()
    run(
        location_uuid=args.location,
        max_age_hours=0 if args.force else args.max_age,
        verbose=not args.quiet,
    )
