"""
Prefetch clima — Open-Meteo archivo histórico + pronóstico.

  Archivo  : 2024-01-01 → hoy-7d   (datos confirmados, DO NOTHING en conflicto)
  Pronóstico: hoy-7d → hoy+16d     (cambia cada día, DO UPDATE en conflicto)

Escribe en store_features_ext: temp_max, temp_min, llueve
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.data_ingestion.prefetch._common import (
    get_active_locations, is_fresh, write_sync_marker,
    WEATHER_ARCHIVE_LAG, WEATHER_FORECAST,
)
from src.db.queries import _fetch_weather, _fetch_weather_forecast, _cache_weather

_SOURCE = 'weather'
_HIST_FROM = date(2024, 1, 1)


def _run_one(loc: dict, verbose: bool) -> int:
    lat, lon, uuid = loc['lat'], loc['lon'], loc['uuid']
    hoy = date.today()

    arch_to   = hoy - timedelta(days=WEATHER_ARCHIVE_LAG)
    arch_from = _HIST_FROM
    n_arch = 0
    if arch_from <= arch_to:
        df = _fetch_weather(lat, lon, str(arch_from), str(arch_to))
        if not df.empty:
            _cache_weather(uuid, df, overwrite=False)
            n_arch = len(df)

    df_fore = _fetch_weather_forecast(lat, lon, past_days=WEATHER_ARCHIVE_LAG, forecast_days=WEATHER_FORECAST)
    n_fore = 0
    if not df_fore.empty:
        _cache_weather(uuid, df_fore, overwrite=True)
        n_fore = len(df_fore)

    write_sync_marker(uuid, _SOURCE)
    if verbose:
        print(f"  [weather] {loc['nombre']}: archivo={n_arch}d  pronóstico={n_fore}d")
    return n_arch + n_fore


def run(
    location_uuid: str | None = None,
    max_age_hours: float = 6,
    verbose: bool = True,
) -> dict[str, int]:
    """Actualiza clima para todas las locations activas (o una sola si se indica uuid)."""
    locations = get_active_locations(location_uuid)
    stats: dict[str, int] = {}

    for loc in locations:
        uuid = loc['uuid']
        if is_fresh(uuid, _SOURCE, max_age_hours):
            if verbose:
                print(f"  [weather] {loc['nombre']}: omitido (datos < {max_age_hours:.0f}h)")
            stats[uuid] = 0
            continue
        try:
            stats[uuid] = _run_one(loc, verbose)
        except Exception as e:
            if verbose:
                print(f"  [weather] {loc['nombre']}: ERROR — {e}")
            stats[uuid] = 0

    return stats


if __name__ == '__main__':
    from src.data_ingestion.prefetch._common import make_parser
    args = make_parser('clima (Open-Meteo)').parse_args()
    run(
        location_uuid=args.location,
        max_age_hours=0 if args.force else args.max_age,
        verbose=not args.quiet,
    )
