"""
Conector de meteorología — Open-Meteo (archivo histórico + previsión).

Interfaz pública:
    TIPO = "meteorologia"
    sync(ubicacion, cfg, verbose) -> int
"""

from __future__ import annotations

from datetime import date, timedelta

from src.data_ingestion._common import WEATHER_ARCHIVE_LAG, WEATHER_FORECAST

TIPO = "meteorologia"


def sync(ubicacion: dict, cfg: dict, verbose: bool = True) -> int:  # noqa: ARG001
    """
    Descarga y cachea datos meteorológicos para una ubicación.

    ubicacion: {ubicacion_id, nombre, lat, lon, pais_codigo, codigo_region, city}
    cfg: config efectiva de la fuente (resultado de get_source_config).
    No llama a is_fresh() ni write_sync_marker() — los gestiona el orquestador.
    Devuelve el número de filas escritas.
    """
    from src.db.queries import _cache_weather, _fetch_weather, _fetch_weather_forecast

    ubicacion_id = ubicacion["ubicacion_id"]
    lat, lon = ubicacion["lat"], ubicacion["lon"]
    nombre = ubicacion.get("nombre", ubicacion_id)
    hoy = date.today()

    arch_to = hoy - timedelta(days=WEATHER_ARCHIVE_LAG)
    arch_from = date(2024, 1, 1)
    n_arch = 0
    if arch_from <= arch_to:
        df = _fetch_weather(lat, lon, str(arch_from), str(arch_to))
        if not df.empty:
            _cache_weather(ubicacion_id, df, overwrite=False)
            n_arch = len(df)

    df_fore = _fetch_weather_forecast(
        lat, lon, past_days=WEATHER_ARCHIVE_LAG, forecast_days=WEATHER_FORECAST
    )
    n_fore = 0
    if not df_fore.empty:
        _cache_weather(ubicacion_id, df_fore, overwrite=True)
        n_fore = len(df_fore)

    if verbose:
        print(f"  [meteorologia] {nombre}: archivo={n_arch}d  pronostico={n_fore}d")
    return n_arch + n_fore
