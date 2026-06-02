"""
Prefetch de features externas — mantiene store_features_ext al día.

Clima (Open-Meteo):
  Archivo   2024-01-01 → hoy-7d    datos históricos confirmados, DO NOTHING
  Pronóstico hoy-7d → hoy+16d     cambia cada día, DO UPDATE
  Máximo prudente: 16 días (límite gratuito Open-Meteo forecast).

Eventos (Open Holidays + Ticketmaster + TheSportsDB + agenda municipal):
  2024-01-01 → hoy+90d  — siempre fuerza re-descarga (fechas de eventos cambian).
  Máximo prudente: 90 días (conciertos/partidos se anuncian con ~3 meses de antelación).

Uso:
  python -m src.data_ingestion.prefetch_features
  python -m src.data_ingestion.prefetch_features --location <uuid>  # solo una location
  python -m src.data_ingestion.prefetch_features --skip-events       # solo clima
  python -m src.data_ingestion.prefetch_features --skip-weather      # solo eventos
"""
import argparse
import sys
import time
from datetime import date, timedelta

from src.db.store import get_conn
from src.db.queries import (
    get_location_coords,
    _fetch_weather,
    _fetch_weather_forecast,
    _cache_weather,
)
from src.data_processing.eventos_client import prefetch_eventos

# ── Ventanas de tiempo ────────────────────────────────────────────────────────

WEATHER_HIST_FROM   = date(2024, 1, 1)
WEATHER_ARCHIVE_LAG = 7    # días de retraso del archivo de Open-Meteo
WEATHER_FORECAST    = 16   # días máximos de pronóstico (límite free tier)
EVENTS_HORIZON      = 90   # días adelante para eventos


def _get_all_active_locations() -> list[dict]:
    rows = get_conn().execute("""
        SELECT u.location_uuid, u.nombre, u.lat, u.lon
        FROM dim_ubicaciones u
        WHERE u.activa = TRUE
          AND u.lat IS NOT NULL
          AND u.lon IS NOT NULL
    """).fetchall()
    return [{'uuid': r[0], 'nombre': r[1], 'lat': float(r[2]), 'lon': float(r[3])} for r in rows]


# ── Prefetch clima ────────────────────────────────────────────────────────────

def prefetch_weather_location(loc: dict, verbose: bool = True) -> dict:
    """
    Descarga y cachea clima histórico + pronóstico para una location.
    Retorna {'archivo': n_dias, 'forecast': n_dias}.
    """
    lat, lon = loc['lat'], loc['lon']
    hoy = date.today()

    # 1. Archivo histórico (datos confirmados, no cambian)
    arch_to   = hoy - timedelta(days=WEATHER_ARCHIVE_LAG)
    arch_from = WEATHER_HIST_FROM

    n_arch = 0
    if arch_from <= arch_to:
        df_arch = _fetch_weather(lat, lon, str(arch_from), str(arch_to))
        if not df_arch.empty:
            _cache_weather(loc['uuid'], df_arch, overwrite=False)
            n_arch = len(df_arch)

    # 2. Pronóstico (hoy-7d → hoy+16d, cambia diariamente → DO UPDATE)
    df_fore = _fetch_weather_forecast(lat, lon, past_days=WEATHER_ARCHIVE_LAG, forecast_days=WEATHER_FORECAST)
    n_fore = 0
    if not df_fore.empty:
        _cache_weather(loc['uuid'], df_fore, overwrite=True)
        n_fore = len(df_fore)

    if verbose:
        print(f"      clima archivo={n_arch}d  pronóstico={n_fore}d")

    return {'archivo': n_arch, 'forecast': n_fore}


# ── Prefetch eventos ──────────────────────────────────────────────────────────

def prefetch_events_location(loc: dict, verbose: bool = True) -> int:
    """
    Descarga y cachea eventos externos para una location.
    Fuerza re-descarga para capturar cambios de fechas/cancelaciones.
    Retorna número de días con al menos un evento.
    """
    n = prefetch_eventos(loc['uuid'], force=True)
    if verbose:
        print(f"      eventos={n}d con datos")
    return n


# ── Runner principal ──────────────────────────────────────────────────────────

def run(
    location_uuid: str | None = None,
    skip_weather: bool = False,
    skip_events: bool = False,
    verbose: bool = True,
) -> dict:
    """
    Ejecuta el prefetch completo.
    Retorna stats por location: {uuid: {'weather': {...}, 'events': n}}.
    """
    def log(msg: str) -> None:
        if verbose:
            print(msg)

    if location_uuid:
        row = get_conn().execute(
            "SELECT location_uuid, nombre, lat, lon FROM dim_ubicaciones WHERE location_uuid = ?",
            [location_uuid],
        ).fetchone()
        if not row or row[2] is None:
            log(f"[!] Location {location_uuid} no encontrada o sin coordenadas.")
            return {}
        locations = [{'uuid': row[0], 'nombre': row[1], 'lat': float(row[2]), 'lon': float(row[3])}]
    else:
        locations = _get_all_active_locations()

    log(f"\n{'─'*60}")
    log(f"  prefetch_features — {len(locations)} location(s)")
    log(f"  Clima:   {'OMITIDO' if skip_weather else f'archivo hasta hoy-{WEATHER_ARCHIVE_LAG}d + pronóstico +{WEATHER_FORECAST}d'}")
    log(f"  Eventos: {'OMITIDO' if skip_events  else f'forzado hasta hoy+{EVENTS_HORIZON}d'}")
    log(f"{'─'*60}")

    stats = {}
    t0 = time.time()

    for i, loc in enumerate(locations, 1):
        log(f"\n  [{i:02d}/{len(locations)}] {loc['nombre']} ({loc['uuid'][:8]}...)")
        entry: dict = {}

        if not skip_weather:
            try:
                entry['weather'] = prefetch_weather_location(loc, verbose)
            except Exception as e:
                log(f"      [!] clima ERROR: {e}")
                entry['weather'] = {'archivo': 0, 'forecast': 0}

        if not skip_events:
            try:
                entry['events'] = prefetch_events_location(loc, verbose)
            except Exception as e:
                log(f"      [!] eventos ERROR: {e}")
                entry['events'] = 0

        stats[loc['uuid']] = entry

    elapsed = time.time() - t0
    log(f"\n{'─'*60}")
    log(f"  Completado en {elapsed:.0f}s — {len(stats)} location(s) procesadas")
    log(f"{'─'*60}\n")

    return stats


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Prefetch features externas a PostgreSQL')
    parser.add_argument('--location',      metavar='UUID', help='Procesar solo esta location')
    parser.add_argument('--skip-weather',  action='store_true', help='No actualizar clima')
    parser.add_argument('--skip-events',   action='store_true', help='No actualizar eventos')
    parser.add_argument('--quiet',         action='store_true', help='Sin salida por pantalla')
    args = parser.parse_args()

    result = run(
        location_uuid=args.location,
        skip_weather=args.skip_weather,
        skip_events=args.skip_events,
        verbose=not args.quiet,
    )
    sys.exit(0 if result else 1)
