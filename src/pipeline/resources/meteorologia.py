"""
Recurso meteorología — Open-Meteo (archivo histórico + previsión).

La API devuelve arrays paralelos, no array de objetos:
  {"daily": {"time": [...], "temperature_2m_max": [...], ...}}

Configuración en fuentes.config:
  variables:    [str]   variables daily de Open-Meteo a descargar
  señales_map:  dict    {variable_open_meteo: señal_id}
  lag_dias:     int     días de lag del archivo (default 5)
  forecast_dias: int    días de previsión (default 7)

Interfaz pública: source(ubicaciones, cfg, date_from, date_to) -> dlt.Source
"""

from __future__ import annotations

from datetime import date, timedelta

import dlt
import requests

_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
_FORECAST = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 15


def _fetch(
    url: str, lat: float, lon: float, date_from: date, date_to: date, variables: list[str]
) -> dict:
    try:
        r = requests.get(
            url,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": date_from.isoformat(),
                "end_date": date_to.isoformat(),
                "daily": ",".join(variables),
                "timezone": "Europe/Madrid",
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("daily", {})
    except Exception:
        return {}


@dlt.resource(
    name="señal", write_disposition="merge", primary_key=["fecha", "ubicacion_id", "señal_id"]
)
def _resource(ubicaciones: list[dict], cfg: dict, date_from: date, date_to: date):
    variables: list[str] = cfg.get(
        "variables", ["temperature_2m_max", "temperature_2m_min", "precipitation_sum"]
    )
    señales_map: dict = cfg.get(
        "señales_map",
        {
            "temperature_2m_max": "tmax",
            "temperature_2m_min": "tmin",
            "precipitation_sum": "precip",
        },
    )
    lag = int(cfg.get("lag_dias", 5))
    forecast = int(cfg.get("forecast_dias", 7))
    hoy = date.today()

    for ubi in ubicaciones:
        lat, lon = ubi["lat"], ubi["lon"]
        ubi_id = ubi["ubicacion_id"]

        # Archivo histórico
        arch_to = hoy - timedelta(days=lag)
        if date_from <= arch_to:
            daily = _fetch(_ARCHIVE, lat, lon, date_from, arch_to, variables)
            yield from _emit(daily, señales_map, ubi_id, date_from, arch_to)

        # Previsión (sobreescribe los últimos lag_dias + forecast_dias)
        fore_from = hoy - timedelta(days=lag)
        fore_to = hoy + timedelta(days=forecast)
        daily = _fetch_forecast(lat, lon, lag, forecast, variables)
        yield from _emit(daily, señales_map, ubi_id, fore_from, fore_to)


def _fetch_forecast(
    lat: float, lon: float, past_days: int, forecast_days: int, variables: list[str]
) -> dict:
    try:
        r = requests.get(
            _FORECAST,
            params={
                "latitude": lat,
                "longitude": lon,
                "past_days": past_days,
                "forecast_days": forecast_days,
                "daily": ",".join(variables),
                "timezone": "Europe/Madrid",
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("daily", {})
    except Exception:
        return {}


def _emit(daily: dict, señales_map: dict, ubi_id: str, d_from: date, d_to: date):
    fechas = daily.get("time", [])
    for i, fecha_str in enumerate(fechas):
        try:
            fecha = date.fromisoformat(fecha_str)
        except Exception:
            continue
        if not (d_from <= fecha <= d_to):
            continue
        for variable, señal_id in señales_map.items():
            col = daily.get(variable, [])
            if i < len(col) and col[i] is not None:
                yield {
                    "fecha": fecha_str,
                    "ubicacion_id": ubi_id,
                    "señal_id": señal_id,
                    "valor": float(col[i]),
                }


@dlt.source
def source(ubicaciones: list[dict], cfg: dict, date_from: date, date_to: date):
    yield _resource(ubicaciones, cfg, date_from, date_to)
