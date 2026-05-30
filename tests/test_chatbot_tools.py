"""
Smoke tests for chatbot tools.

Each test verifies that a valid call returns a well-structured response
(no "error" key) and that invalid inputs fail gracefully (with "error" key,
no exceptions). Add a new class per tool when a new tool is introduced.

Run:
    pytest tests/test_chatbot_tools.py -v
"""
import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

# ── Synthetic dataset config ──────────────────────────────────────────────────

_DATA_DIR  = Path("src/data")
_SESSION   = "pytest_tools"
_CSV_PATH  = _DATA_DIR / f"dataset_{_SESSION}.csv"
_LOC_A     = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_LOC_B     = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_ZONE_A    = "cccccccc-cccc-cccc-cccc-cccccccccccc"
# Real location UUID that exists in todas_las_ubicaciones.json (for get_weather_holidays)
_REAL_LOC  = "3c73b012-fa57-4023-8d76-7b0e60cd6fbc"


def _hourly_json(peak_hour: int = 17) -> str:
    arr = [0] * 24
    for h in range(24):
        dist = abs(h - peak_hour)
        arr[h] = max(0, 100 - dist * 12)
    return json.dumps(arr)


@pytest.fixture(scope="module", autouse=True)
def synthetic_csv():
    """Creates a pre-enriched synthetic CSV; removes it after the session."""
    rng = np.random.default_rng(42)
    n_days = 120
    today = date.today()

    rows = []
    for i in range(n_days):
        d = today - timedelta(days=n_days - i)
        for loc, zone in [(_LOC_A, _ZONE_A), (_LOC_B, _ZONE_A)]:
            base = 400 + rng.integers(-120, 120)
            rows.append({
                "location_id":    loc,
                "zone_uuid":      zone,
                "fecha":          d.isoformat(),
                "total_visits":   int(base * 1.5),
                "unique_visitors": int(base),
                "new_visitors":   int(base * 0.3),
                "dwell_time":     float(rng.integers(120, 600)),
                "hourly_visits":  _hourly_json(peak_hour=int(rng.integers(14, 20))),
                # Enriched columns — avoids calling Open-Meteo during tests
                "es_festivo":     0,
                "llueve":         int(rng.random() < 0.2),
                "temp_max":       float(rng.integers(15, 35)),
                "temp_min":       float(rng.integers(5, 18)),
            })

    df = pd.DataFrame(rows)
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(_CSV_PATH, index=False)

    yield

    _CSV_PATH.unlink(missing_ok=True)


# ── Imports after fixture so module-level code runs with the right path ───────

from src.chatbot.tools import (  # noqa: E402
    get_pm_data,
    get_gis_data,
    get_weather_holidays,
    get_forecast,
    get_anomalies,
    get_hourly_breakdown,
    compare_locations,
)

_FECHA_INI = (date.today() - timedelta(days=30)).isoformat()
_FECHA_FIN = date.today().isoformat()


# ── get_pm_data ───────────────────────────────────────────────────────────────

class TestGetPmData:
    def test_valid_call_returns_metrics(self):
        r = get_pm_data(_LOC_A, _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" not in r
        assert "visitas_totales" in r
        assert "visitantes_unicos" in r
        assert "hora_pico" in r
        assert r["visitas_totales"] > 0

    def test_zone_filter(self):
        r = get_pm_data(_LOC_A, _FECHA_INI, _FECHA_FIN, zone_uuid=_ZONE_A, session_id=_SESSION)
        assert "error" not in r

    def test_inverted_dates_returns_error(self):
        r = get_pm_data(_LOC_A, _FECHA_FIN, _FECHA_INI, session_id=_SESSION)
        assert "error" in r

    def test_unknown_location_returns_error(self):
        r = get_pm_data("no-such-uuid", _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" in r

    def test_range_over_90_days_returns_error(self):
        inicio = (date.today() - timedelta(days=100)).isoformat()
        r = get_pm_data(_LOC_A, inicio, _FECHA_FIN, session_id=_SESSION)
        assert "error" in r


# ── get_gis_data ──────────────────────────────────────────────────────────────

class TestGetGisData:
    def test_unknown_uuid_returns_sin_datos_not_exception(self):
        r = get_gis_data(_LOC_A)
        # Valid responses: either has geospatial data or signals no data
        assert "sin_datos" in r or "alcance_peatonal" in r or "perfil_economico" in r

    def test_date_param_accepted(self):
        r = get_gis_data(_LOC_A, fecha="2025-01-01")
        assert "error" not in r or "sin_datos" in r


# ── get_weather_holidays ──────────────────────────────────────────────────────

class TestGetWeatherHolidays:
    def test_valid_location_returns_periodo(self):
        inicio = (date.today() - timedelta(days=14)).isoformat()
        fin = date.today().isoformat()
        r = get_weather_holidays(_REAL_LOC, inicio, fin)
        assert "error" not in r
        assert "periodo" in r
        assert "festivos" in r

    def test_inverted_dates_returns_error(self):
        r = get_weather_holidays(_REAL_LOC, _FECHA_FIN, _FECHA_INI)
        assert "error" in r

    def test_unknown_location_returns_error(self):
        r = get_weather_holidays("no-such-uuid", _FECHA_INI, _FECHA_FIN)
        assert "error" in r


# ── get_forecast ──────────────────────────────────────────────────────────────

class TestGetForecast:
    def test_returns_predictions(self):
        r = get_forecast(_LOC_A, _ZONE_A, n_dias=7, session_id=_SESSION)
        assert "error" not in r, f"Error inesperado: {r.get('error')}"
        assert "predicciones" in r
        assert len(r["predicciones"]) == 7

    def test_prediction_structure(self):
        r = get_forecast(_LOC_A, _ZONE_A, n_dias=3, session_id=_SESSION)
        assert "error" not in r, r.get("error")
        for p in r["predicciones"]:
            assert "fecha" in p
            assert "prediccion" in p
            assert p["prediccion"] >= 0

    def test_metricas_present(self):
        r = get_forecast(_LOC_A, _ZONE_A, n_dias=3, session_id=_SESSION)
        assert "error" not in r, r.get("error")
        assert "metricas" in r

    def test_n_dias_zero_returns_error(self):
        r = get_forecast(_LOC_A, _ZONE_A, n_dias=0, session_id=_SESSION)
        assert "error" in r

    def test_n_dias_over_90_returns_error(self):
        r = get_forecast(_LOC_A, _ZONE_A, n_dias=91, session_id=_SESSION)
        assert "error" in r


# ── get_anomalies ─────────────────────────────────────────────────────────────

class TestGetAnomalies:
    def test_returns_valid_structure(self):
        inicio = (date.today() - timedelta(days=60)).isoformat()
        r = get_anomalies(_LOC_A, inicio, _FECHA_FIN, session_id=_SESSION)
        assert "error" not in r, r.get("error")
        assert "total_anomalias" in r
        assert "anomalias" in r
        assert isinstance(r["anomalias"], list)

    def test_anomalies_sorted_by_magnitude(self):
        inicio = (date.today() - timedelta(days=60)).isoformat()
        r = get_anomalies(_LOC_A, inicio, _FECHA_FIN, session_id=_SESSION)
        if r.get("anomalias"):
            z_scores = [abs(a["z_score"]) for a in r["anomalias"]]
            assert z_scores == sorted(z_scores, reverse=True)

    def test_anomaly_tipo_values(self):
        inicio = (date.today() - timedelta(days=60)).isoformat()
        r = get_anomalies(_LOC_A, inicio, _FECHA_FIN, session_id=_SESSION)
        for a in r.get("anomalias", []):
            assert a["tipo"] in ("pico", "caída")

    def test_unknown_location_returns_error(self):
        r = get_anomalies("no-such-uuid", _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" in r


# ── get_hourly_breakdown ──────────────────────────────────────────────────────

class TestGetHourlyBreakdown:
    def test_returns_valid_structure(self):
        r = get_hourly_breakdown(_LOC_A, _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" not in r, r.get("error")
        assert "hora_pico_global" in r
        assert "hora_pico_global_label" in r
        assert "por_dia_semana" in r

    def test_hora_pico_in_valid_range(self):
        r = get_hourly_breakdown(_LOC_A, _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" not in r, r.get("error")
        assert 0 <= r["hora_pico_global"] <= 23

    def test_dia_semana_structure(self):
        r = get_hourly_breakdown(_LOC_A, _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" not in r, r.get("error")
        for dia, data in r["por_dia_semana"].items():
            assert "hora_pico" in data
            assert "visitas_hora_pico" in data
            assert "total_medio_dia" in data
            assert 0 <= data["hora_pico"] <= 23

    def test_zone_filter(self):
        r = get_hourly_breakdown(_LOC_A, _FECHA_INI, _FECHA_FIN, zone_uuid=_ZONE_A, session_id=_SESSION)
        assert "error" not in r, r.get("error")

    def test_unknown_location_returns_error(self):
        r = get_hourly_breakdown("no-such-uuid", _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" in r


# ── compare_locations ─────────────────────────────────────────────────────────

class TestCompareLocations:
    def test_returns_valid_structure(self):
        r = compare_locations([_LOC_A, _LOC_B], _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" not in r, r.get("error")
        assert "ranking" in r
        assert "ubicaciones" in r
        assert len(r["ubicaciones"]) == 2

    def test_ranking_length_matches_locations_with_data(self):
        r = compare_locations([_LOC_A, _LOC_B], _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" not in r, r.get("error")
        con_datos = [u for u in r["ubicaciones"] if not u.get("sin_datos")]
        assert len(r["ranking"]) == len(con_datos)

    def test_all_valid_metricas(self):
        for metrica in ("total_visits", "unique_visitors", "new_visitors", "dwell_time"):
            r = compare_locations([_LOC_A], _FECHA_INI, _FECHA_FIN, metrica=metrica, session_id=_SESSION)
            assert "error" not in r, f"Fallo con métrica {metrica}: {r.get('error')}"

    def test_invalid_metrica_returns_error(self):
        r = compare_locations([_LOC_A], _FECHA_INI, _FECHA_FIN, metrica="inventada")
        assert "error" in r

    def test_inverted_dates_returns_error(self):
        r = compare_locations([_LOC_A], _FECHA_FIN, _FECHA_INI, session_id=_SESSION)
        assert "error" in r
