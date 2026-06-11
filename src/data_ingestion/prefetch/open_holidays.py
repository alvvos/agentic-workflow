"""
Prefetch vacaciones escolares + festivos regionales — Open Holidays API.

Escribe en store_features_ext:
  ev_vacaciones_escolares  (0/1)
  ev_festivo_regional      (0/1)
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.data_ingestion.prefetch._common import (
    get_active_locations, is_fresh, write_ev_features,
    write_calendario_org, write_sync_marker,
    EVENTS_DATE_FROM, EVENTS_HORIZON,
)
from src.data_processing.fuentes_eventos.open_holidays import (
    get_school_holidays, get_public_holidays_detail, expand_periods,
)

_SOURCE = 'open_holidays'


def _run_one(loc: dict, verbose: bool) -> int:
    uuid         = loc['uuid']
    pais_codigo  = loc['pais_codigo']
    region_code  = loc['region_code']
    date_from    = EVENTS_DATE_FROM
    date_to      = date.today() + timedelta(days=EVENTS_HORIZON)
    years        = list(range(date_from.year, date_to.year + 1))

    daily: dict[date, dict] = {}
    raw_rows: list[dict] = []

    def _slot(d: date) -> dict:
        if d not in daily:
            daily[d] = {'ev_vacaciones_escolares': 0, 'ev_festivo_regional': 0}
        return daily[d]

    for year in years:
        for d in expand_periods(get_school_holidays(pais_codigo, year, region_code)):
            if date_from <= d <= date_to:
                _slot(d)['ev_vacaciones_escolares'] = 1
                raw_rows.append({
                    'evento_key':   'vacaciones_escolares',
                    'fecha_inicio':  d,
                    'fecha_fin':     d,
                    'fuente':        'open_holidays',
                    'source_key':    f"oh_school:{pais_codigo}:{region_code or ''}:{d}",
                    'metadata':      {'pais': pais_codigo, 'region': region_code},
                })

        for fh in get_public_holidays_detail(pais_codigo, year, region_code):
            if not fh.get('nationwide', True) and date_from <= fh['fecha'] <= date_to:
                _slot(fh['fecha'])['ev_festivo_regional'] = 1
                raw_rows.append({
                    'evento_key':   'festivo_regional',
                    'fecha_inicio':  fh['fecha'],
                    'fecha_fin':     fh['fecha'],
                    'fuente':        'open_holidays',
                    'source_key':    f"oh_ph:{pais_codigo}:{region_code or ''}:{fh['fecha']}:{fh['name'][:20]}",
                    'metadata':      {'nombre': fh['name'], 'scope': fh.get('scope', '')},
                })

    write_ev_features(uuid, daily)
    write_calendario_org(uuid, raw_rows, pais_codigo)
    write_sync_marker(uuid, _SOURCE)

    n = len(daily)
    if verbose:
        print(f"  [open_holidays] {loc['nombre']}: {n}d  (vacaciones + festivos regionales)")
    return n


def run(
    location_uuid: str | None = None,
    max_age_hours: float = 6,
    verbose: bool = True,
) -> dict[str, int]:
    locations = get_active_locations(location_uuid)
    stats: dict[str, int] = {}

    for loc in locations:
        uuid = loc['uuid']
        if is_fresh(uuid, _SOURCE, max_age_hours):
            if verbose:
                print(f"  [open_holidays] {loc['nombre']}: omitido (datos < {max_age_hours:.0f}h)")
            stats[uuid] = 0
            continue
        try:
            stats[uuid] = _run_one(loc, verbose)
        except Exception as e:
            if verbose:
                print(f"  [open_holidays] {loc['nombre']}: ERROR — {e}")
            stats[uuid] = 0

    return stats


if __name__ == '__main__':
    from src.data_ingestion.prefetch._common import make_parser
    args = make_parser('vacaciones escolares + festivos regionales (Open Holidays)').parse_args()
    run(
        location_uuid=args.location,
        max_age_hours=0 if args.force else args.max_age,
        verbose=not args.quiet,
    )
