"""
Prefetch fixtures deportivos — TheSportsDB (API v1 gratuita, sin key).

Escribe en store_features_ext:
  ev_rank_deportivo  (0-100)
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
from src.data_processing.fuentes_eventos.thesportsdb import (
    get_events_for_city,
)
from src.data_processing.fuentes_eventos.thesportsdb import (
    prewarm as _prewarm_cache,
)

SOURCE = "thesportsdb"
_SOURCE = SOURCE


def _run_one(loc: dict, verbose: bool) -> int:
    uuid = loc["uuid"]
    ciudad = loc["city"]
    pais_codigo = loc["pais_codigo"]
    date_from = EVENTS_DATE_FROM
    date_to = date.today() + timedelta(days=EVENTS_HORIZON)

    if not ciudad:
        if verbose:
            print(f"  [thesportsdb] {loc['nombre']}: sin ciudad configurada — omitido")
        write_sync_marker(uuid, _SOURCE)
        return 0

    events = get_events_for_city(ciudad, pais_codigo, date_from, date_to)

    daily: dict[date, dict] = {}
    raw_rows: list[dict] = []
    for ev in events:
        d = ev["fecha"]
        if d not in daily:
            daily[d] = {"ev_rank_deportivo": 0}
        daily[d]["ev_rank_deportivo"] = max(daily[d]["ev_rank_deportivo"], ev["score"])
        raw_rows.append(
            {
                "evento_key": "partido_deportivo",
                "fecha_inicio": d,
                "fecha_fin": d,
                "fuente": "thesportsdb",
                "source_key": f"tsdb:{uuid}:{ev['source_key']}",
                "metadata": {
                    "evento": ev["evento"],
                    "liga": ev["liga"],
                    "sede": ev.get("sede", ""),
                    "ciudad_sede": ev.get("ciudad_sede", ""),
                    "es_local": ev.get("es_local", True),
                },
            }
        )

    write_ev_features(uuid, daily)
    write_calendario_org(uuid, raw_rows, pais_codigo)
    write_sync_marker(uuid, _SOURCE)

    n = len(daily)
    if verbose:
        print(f"  [thesportsdb] {loc['nombre']}: {n}d con partidos  ({len(events)} eventos)")
    return n


def run(
    location_uuid: str | None = None,
    max_age_hours: float = 23,
    verbose: bool = True,
) -> dict[str, int]:
    locations = get_active_locations(location_uuid)
    stats: dict[str, int] = {}

    # Pre-calentar caché: una sola pasada HTTP por liga+temporada antes del loop.
    # Las llamadas posteriores a get_events_for_city() solo filtran desde memoria.
    if locations and not location_uuid:
        paises = {loc["pais_codigo"] for loc in locations if loc["pais_codigo"]}
        if verbose:
            print(f"  [thesportsdb] precalentando caché ({', '.join(sorted(paises))})…")
        _prewarm_cache(paises, EVENTS_DATE_FROM, date.today() + timedelta(days=EVENTS_HORIZON))

    for loc in locations:
        uuid = loc["uuid"]
        if is_fresh(uuid, _SOURCE, max_age_hours):
            if verbose:
                print(f"  [thesportsdb] {loc['nombre']}: omitido (datos < {max_age_hours:.0f}h)")
            stats[uuid] = 0
            continue
        try:
            stats[uuid] = _run_one(loc, verbose)
        except Exception as e:
            if verbose:
                print(f"  [thesportsdb] {loc['nombre']}: ERROR — {e}")
            stats[uuid] = 0

    return stats


if __name__ == "__main__":
    from src.data_ingestion.prefetch._common import make_parser

    args = make_parser("fixtures deportivos (TheSportsDB)").parse_args()
    run(
        location_uuid=args.location,
        max_age_hours=0 if args.force else args.max_age,
        verbose=not args.quiet,
    )
