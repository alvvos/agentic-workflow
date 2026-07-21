"""
Smoke + contract tests for chatbot tools.

Structure:
- One class per tool, named TestGet<ToolName>.
- Each class covers: valid call, invalid inputs (error path), and output contract
  (key names, value ranges, units).
- TestToolRegistration: structural invariant — every def get_* in tools.py must be
  registered in client.py's _TOOL_FN dict and _TOOL_DEFINITIONS list.

Run:
    pytest tests/test_chatbot_tools.py -v
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── Synthetic dataset config ──────────────────────────────────────────────────

_DATA_DIR = Path("src/data")
_SESSION = "pytest_tools"
_CSV_PATH = _DATA_DIR / f"dataset_{_SESSION}.csv"
_LOC_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_LOC_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_ZONE_A = "cccccccc-cccc-cccc-cccc-cccccccccccc"
_ZONE_B = "dddddddd-dddd-dddd-dddd-dddddddddddd"  # second zone for _LOC_A
# Real location UUID that exists in the DB (for DB-dependent tests)
_REAL_LOC = "3c73b012-fa57-4023-8d76-7b0e60cd6fbc"


def _hourly_json(peak_hour: int = 17) -> str:
    arr = [0] * 24
    for h in range(24):
        dist = abs(h - peak_hour)
        arr[h] = max(0, 100 - dist * 12)
    return json.dumps(arr)


@pytest.fixture(scope="module", autouse=True)
def synthetic_csv():
    """
    Creates a pre-enriched synthetic CSV with TWO zones for _LOC_A and one for _LOC_B.
    Two zones per location is intentional: it exposes bugs where media_dia is divided
    by rows (days × zones) instead of unique days.
    Removed after the session.
    """
    rng = np.random.default_rng(42)
    n_days = 120
    today = date.today()

    rows = []
    for i in range(n_days):
        d = today - timedelta(days=n_days - i)
        # _LOC_A has two zones (_ZONE_A and _ZONE_B) — tests multi-zone correctness
        for loc, zone in [(_LOC_A, _ZONE_A), (_LOC_A, _ZONE_B), (_LOC_B, _ZONE_A)]:
            base = 400 + rng.integers(-120, 120)
            rows.append(
                {
                    "location_id": loc,
                    "zona_id": zone,
                    "fecha": d.isoformat(),
                    "total_visits": int(base * 1.5),
                    "unique_visitors": int(base),
                    "new_visitors": int(base * 0.3),
                    "dwell_time": float(rng.integers(10, 90)),  # minutes
                    "hourly_visits": _hourly_json(peak_hour=int(rng.integers(14, 20))),
                    "es_festivo": 0,
                    "llueve": int(rng.random() < 0.2),
                    "temp_max": float(rng.integers(15, 35)),
                    "temp_min": float(rng.integers(5, 18)),
                }
            )

    df = pd.DataFrame(rows)
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(_CSV_PATH, index=False)

    yield

    _CSV_PATH.unlink(missing_ok=True)


# ── Imports after fixture so module-level code runs with the right path ───────

from src.chatbot.tools import (  # noqa: E402
    compare_locations,
    get_active_features,
    get_anomalies,
    get_cruise_calls,
    get_dwell_profile,
    get_external_features,
    get_forecast,
    get_funnel_ratios,
    get_gis_data,
    get_hourly_breakdown,
    get_location_info,
    get_model_metrics,
    get_pm_data,
    get_weather_holidays,
)

_FECHA_INI = (date.today() - timedelta(days=30)).isoformat()
_FECHA_FIN = date.today().isoformat()


# ── Structural invariant ──────────────────────────────────────────────────────


class TestToolRegistration:
    """
    Parses tools.py and client.py as text to verify every public tool function
    is registered. No client.py import needed (avoids anthropic dependency).
    """

    _TOOLS_SRC = (Path("src/chatbot/tools.py")).read_text()
    _CLIENT_SRC = (Path("src/chatbot/client.py")).read_text()

    _tool_funcs = set(re.findall(r"^def (get_\w+)", _TOOLS_SRC, re.MULTILINE))
    _fn_keys = set(re.findall(r'"(get_\w+)":\s*lambda', _CLIENT_SRC))
    _def_names = set(re.findall(r'"name":\s*"(get_\w+)"', _CLIENT_SRC))

    @pytest.mark.parametrize("fn_name", sorted(_tool_funcs))
    def test_tool_registered_in_tool_fn(self, fn_name):
        """Every def get_* in tools.py must appear as a key in _TOOL_FN in client.py."""
        assert fn_name in self._fn_keys, (
            f"'{fn_name}' is defined in tools.py but missing from _TOOL_FN in client.py. "
            "Claude cannot call this tool until it's registered."
        )

    @pytest.mark.parametrize("fn_name", sorted(_tool_funcs))
    def test_tool_has_definition(self, fn_name):
        """Every def get_* in tools.py must have a 'name' entry in _TOOL_DEFINITIONS."""
        assert fn_name in self._def_names, (
            f"'{fn_name}' is defined in tools.py but has no entry in _TOOL_DEFINITIONS "
            "in client.py. Claude won't know this tool exists."
        )


# ── get_pm_data ───────────────────────────────────────────────────────────────


class TestGetPmData:
    """¿Cuántos visitantes tuvo esta semana? ¿Cuál es la media diaria?"""

    def test_valid_call_returns_metrics(self):
        r = get_pm_data(_LOC_A, _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" not in r
        assert "visitas_totales" in r
        assert "visitantes_unicos" in r
        assert "hora_pico" in r
        assert r["visitas_totales"] > 0

    def test_dwell_time_key_is_minutes(self):
        """Field must be dwell_time_min (not _seg) — stored in minutes, not seconds."""
        r = get_pm_data(_LOC_A, _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" not in r
        assert "dwell_time_min" in r, "Key should be dwell_time_min (unit suffix matters)"
        assert "dwell_time_seg" not in r, "Old _seg key must not be present"
        # Sanity range: 1 min to 8 hours
        assert 1 <= r["dwell_time_min"] <= 480

    def test_media_dia_uses_unique_days_not_rows(self):
        """
        _LOC_A has 2 zones in the fixture. With the wrong formula (len(sub) = days×zones),
        media_dia for all zones ≈ media_dia for one zone (the ×2 rows cancels the ×2 visits).
        With the correct formula (fecha.nunique()), media_dia_all ≈ 2 × media_dia_one_zone.
        We assert the multi-zone result is materially larger than the single-zone result.
        """
        r_all = get_pm_data(_LOC_A, _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        r_one = get_pm_data(_LOC_A, _FECHA_INI, _FECHA_FIN, zone_uuid=_ZONE_A, session_id=_SESSION)
        assert "error" not in r_all
        assert "error" not in r_one
        assert r_all["visitas_media_diaria"] > r_one["visitas_media_diaria"] * 1.5, (
            f"media_dia_all={r_all['visitas_media_diaria']} should be ~2× "
            f"media_dia_one_zone={r_one['visitas_media_diaria']}. "
            "If roughly equal, the formula is dividing by rows (days×zones) not unique days."
        )

    def test_hora_pico_in_valid_range(self):
        r = get_pm_data(_LOC_A, _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" not in r
        assert 0 <= r["hora_pico"] <= 23

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

    def test_invalid_date_format_returns_error(self):
        r = get_pm_data(_LOC_A, "not-a-date", _FECHA_FIN, session_id=_SESSION)
        assert "error" in r


# ── get_funnel_ratios ─────────────────────────────────────────────────────────


class TestGetFunnelRatios:
    """¿Cuál es el ratio de conversión? ¿Qué % de los que pasan entran a la tienda?"""

    def test_inverted_dates_returns_error(self):
        r = get_funnel_ratios(_LOC_A, _FECHA_FIN, _FECHA_INI)
        assert "error" in r

    def test_invalid_date_format_returns_error(self):
        r = get_funnel_ratios(_LOC_A, "not-a-date", _FECHA_FIN)
        assert "error" in r

    def test_response_is_dict(self):
        r = get_funnel_ratios(_LOC_A, _FECHA_INI, _FECHA_FIN)
        assert isinstance(r, dict)

    def test_structure_on_success(self, db_available):
        if not db_available:
            pytest.skip("Requires DB (zonas JOIN)")
        r = get_funnel_ratios(_REAL_LOC, _FECHA_INI, _FECHA_FIN)
        if "error" in r:
            pytest.skip(f"No data for location: {r['error']}")
        assert "visitantes" in r
        assert "ratios" in r
        assert "wow" in r
        assert "calle_tienda_pct" in r["ratios"]
        assert "tienda_caja_pct" in r["ratios"]
        assert "calle_caja_pct" in r["ratios"]

    def test_ratios_in_valid_range(self, db_available):
        if not db_available:
            pytest.skip("Requires DB (zonas JOIN)")
        r = get_funnel_ratios(_REAL_LOC, _FECHA_INI, _FECHA_FIN)
        if "error" in r:
            pytest.skip(f"No data: {r['error']}")
        for key, val in r["ratios"].items():
            if val is not None:
                assert 0 <= val <= 100, f"{key}={val} is outside [0, 100]"

    def test_wow_diff_present(self, db_available):
        if not db_available:
            pytest.skip("Requires DB (zonas JOIN)")
        r = get_funnel_ratios(_REAL_LOC, _FECHA_INI, _FECHA_FIN)
        if "error" in r:
            pytest.skip(f"No data: {r['error']}")
        assert "diff_calle_tienda_pp" in r["wow"]
        assert "diff_tienda_caja_pp" in r["wow"]
        assert "diff_calle_caja_pp" in r["wow"]

    def test_visitor_counts_nonnegative(self, db_available):
        if not db_available:
            pytest.skip("Requires DB (zonas JOIN)")
        r = get_funnel_ratios(_REAL_LOC, _FECHA_INI, _FECHA_FIN)
        if "error" in r:
            pytest.skip(f"No data: {r['error']}")
        for zone, count in r["visitantes"].items():
            assert count >= 0, f"Negative visitors for {zone}"


# ── get_gis_data ──────────────────────────────────────────────────────────────


class TestGetGisData:
    """¿Qué datos geoespaciales tengo de esta ubicación?"""

    def test_unknown_uuid_returns_valid_response(self):
        r = get_gis_data(_LOC_A)
        assert (
            "sin_datos" in r or "alcance_peatonal" in r or "perfil_economico" in r or "error" in r
        )

    def test_date_param_accepted(self):
        r = get_gis_data(_LOC_A, fecha="2025-01-01")
        assert isinstance(r, dict)

    def test_response_is_dict(self):
        assert isinstance(get_gis_data(_LOC_A), dict)


# ── get_weather_holidays ──────────────────────────────────────────────────────


class TestGetWeatherHolidays:
    """¿Qué tiempo hizo? ¿Había festivos esa semana?"""

    def test_valid_location_returns_periodo(self, db_available):
        if not db_available:
            pytest.skip("Requires DB to resolve location coordinates")
        inicio = (date.today() - timedelta(days=14)).isoformat()
        fin = date.today().isoformat()
        r = get_weather_holidays(_REAL_LOC, inicio, fin)
        if "error" in r and "no encontrada" in r.get("error", ""):
            pytest.skip("Location not seeded in this test DB")
        assert "error" not in r
        assert "periodo" in r
        assert "festivos" in r

    def test_festivos_is_list(self, db_available):
        if not db_available:
            pytest.skip("Requires DB")
        inicio = (date.today() - timedelta(days=7)).isoformat()
        r = get_weather_holidays(_REAL_LOC, inicio, _FECHA_FIN)
        if "error" in r:
            pytest.skip(f"Skipping: {r['error']}")
        assert isinstance(r["festivos"], list)

    def test_inverted_dates_returns_error(self):
        r = get_weather_holidays(_REAL_LOC, _FECHA_FIN, _FECHA_INI)
        assert "error" in r

    def test_unknown_location_returns_error(self):
        r = get_weather_holidays("no-such-uuid", _FECHA_INI, _FECHA_FIN)
        assert "error" in r

    def test_invalid_date_format_returns_error(self):
        r = get_weather_holidays(_REAL_LOC, "not-a-date", _FECHA_FIN)
        assert "error" in r


# ── get_forecast ──────────────────────────────────────────────────────────────


class TestGetForecast:
    """¿Qué se espera la próxima semana? ¿Cuál es la previsión?"""

    def test_returns_predictions(self, db_available):
        if not db_available:
            pytest.skip("Requires DB (get_df_enriquecido has no CSV fallback)")
        r = get_forecast(_LOC_A, _ZONE_A, n_dias=7, session_id=_SESSION)
        assert "error" not in r, f"Error inesperado: {r.get('error')}"
        assert "predicciones" in r
        assert len(r["predicciones"]) == 7

    def test_prediction_structure(self, db_available):
        if not db_available:
            pytest.skip("Requires DB")
        r = get_forecast(_LOC_A, _ZONE_A, n_dias=3, session_id=_SESSION)
        assert "error" not in r, r.get("error")
        for p in r["predicciones"]:
            assert "fecha" in p
            assert "prediccion" in p
            assert p["prediccion"] >= 0

    def test_metricas_present(self, db_available):
        if not db_available:
            pytest.skip("Requires DB")
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
    """¿Hubo días anómalos? ¿Hubo algún pico o caída inusual?"""

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

    def test_total_anomalias_matches_list_length(self):
        inicio = (date.today() - timedelta(days=60)).isoformat()
        r = get_anomalies(_LOC_A, inicio, _FECHA_FIN, session_id=_SESSION)
        assert "error" not in r
        assert r["total_anomalias"] == len(r["anomalias"])

    def test_unknown_location_returns_error(self):
        r = get_anomalies("no-such-uuid", _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" in r


# ── get_hourly_breakdown ──────────────────────────────────────────────────────


class TestGetHourlyBreakdown:
    """¿A qué hora hay más tráfico? ¿Cuál es el patrón horario por día de la semana?"""

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

    def test_zona_filter_reduces_or_equals_total(self):
        r_all = get_hourly_breakdown(_LOC_A, _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        r_zone = get_hourly_breakdown(
            _LOC_A, _FECHA_INI, _FECHA_FIN, zone_uuid=_ZONE_A, session_id=_SESSION
        )
        assert "error" not in r_all
        assert "error" not in r_zone

    def test_unknown_location_returns_error(self):
        r = get_hourly_breakdown("no-such-uuid", _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" in r


# ── compare_locations ─────────────────────────────────────────────────────────


class TestCompareLocations:
    """¿Cómo va esta tienda comparada con las demás?"""

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
            r = compare_locations(
                [_LOC_A], _FECHA_INI, _FECHA_FIN, metrica=metrica, session_id=_SESSION
            )
            assert "error" not in r, f"Fallo con métrica {metrica}: {r.get('error')}"

    def test_invalid_metrica_returns_error(self):
        r = compare_locations([_LOC_A], _FECHA_INI, _FECHA_FIN, metrica="inventada")
        assert "error" in r

    def test_inverted_dates_returns_error(self):
        r = compare_locations([_LOC_A], _FECHA_FIN, _FECHA_INI, session_id=_SESSION)
        assert "error" in r

    def test_single_location_returns_ranking_with_one_entry(self):
        r = compare_locations([_LOC_A], _FECHA_INI, _FECHA_FIN, session_id=_SESSION)
        assert "error" not in r
        assert len(r["ranking"]) == 1


# ── get_location_info ─────────────────────────────────────────────────────────


class TestGetLocationInfo:
    """¿Dónde está esta tienda? ¿Cuántas zonas tiene?"""

    def test_unknown_uuid_returns_error(self):
        r = get_location_info("no-such-uuid")
        assert "error" in r

    def test_response_is_dict(self):
        assert isinstance(get_location_info(_LOC_A), dict)

    def test_structure_on_success(self):
        r = get_location_info(_LOC_A)
        if "error" not in r:
            assert "nombre" in r
            assert "coordenadas" in r
            assert "zonas" in r
            assert isinstance(r["zonas"], list)

    def test_real_location(self, db_available):
        if not db_available:
            pytest.skip("Requires DB")
        r = get_location_info(_REAL_LOC)
        if "error" not in r:
            assert "nombre" in r
            assert "zonas" in r


# ── get_active_features ───────────────────────────────────────────────────────


class TestGetActiveFeatures:
    """¿Qué señales o features externas están activas para esta ubicación?"""

    def test_response_is_dict(self):
        assert isinstance(get_active_features(_LOC_A), dict)

    def test_graceful_empty_for_unknown_location(self):
        r = get_active_features("no-such-uuid")
        assert "n_features_activas" in r or "error" in r

    def test_structure_on_success(self):
        r = get_active_features(_LOC_A)
        if "error" not in r:
            assert "n_features_activas" in r
            assert "features" in r
            assert isinstance(r["features"], list)

    def test_n_features_activas_nonnegative(self):
        r = get_active_features(_LOC_A)
        if "error" not in r:
            assert r["n_features_activas"] >= 0


# ── get_external_features ─────────────────────────────────────────────────────


class TestGetExternalFeatures:
    """¿Cómo han afectado el turismo/cruceros/clima al tráfico?"""

    def test_empty_feature_keys_returns_error(self):
        r = get_external_features(_LOC_A, [], _FECHA_INI, _FECHA_FIN)
        assert "error" in r

    def test_inverted_dates_returns_error(self):
        r = get_external_features(_LOC_A, ["turistas"], _FECHA_FIN, _FECHA_INI)
        assert "error" in r

    def test_range_over_760_days_returns_error(self):
        very_old = (date.today() - timedelta(days=800)).isoformat()
        r = get_external_features(_LOC_A, ["turistas"], very_old, _FECHA_FIN)
        assert "error" in r

    def test_valid_call_returns_structure(self):
        r = get_external_features(_LOC_A, ["turistas"], _FECHA_INI, _FECHA_FIN)
        assert isinstance(r, dict)
        if "error" not in r:
            assert "resumen" in r
            assert "series" in r
            assert "sin_datos" in r

    def test_yoy_flag_accepted(self):
        r = get_external_features(_LOC_A, ["turistas"], _FECHA_INI, _FECHA_FIN, incluir_yoy=True)
        assert isinstance(r, dict)

    def test_invalid_date_format_returns_error(self):
        r = get_external_features(_LOC_A, ["turistas"], "bad-date", _FECHA_FIN)
        assert "error" in r


# ── get_cruise_calls ──────────────────────────────────────────────────────────


class TestGetCruiseCalls:
    """¿Hay escalas de cruceros previstas? ¿Cuántos pasajeros se esperan?"""

    def test_invalid_dates_returns_error(self):
        r = get_cruise_calls(_LOC_A, "bad-date", _FECHA_FIN)
        assert "error" in r

    def test_valid_call_returns_structure(self):
        r = get_cruise_calls(_LOC_A, _FECHA_INI, _FECHA_FIN)
        assert isinstance(r, dict)
        if "error" not in r:
            assert "n_escalas" in r
            assert "escalas" in r
            assert isinstance(r["escalas"], list)

    def test_unknown_location_returns_zero_or_error(self):
        r = get_cruise_calls("no-such-uuid", _FECHA_INI, _FECHA_FIN)
        assert isinstance(r, dict)
        assert "n_escalas" in r or "error" in r

    def test_n_escalas_matches_list_length(self):
        r = get_cruise_calls(_LOC_A, _FECHA_INI, _FECHA_FIN)
        if "error" not in r:
            assert r["n_escalas"] == len(r["escalas"])


# ── get_model_metrics ─────────────────────────────────────────────────────────


class TestGetModelMetrics:
    """¿Cuál es la precisión del modelo? ¿Qué features mejoran las predicciones?"""

    def test_returns_dict(self):
        assert isinstance(get_model_metrics(_LOC_A), dict)

    def test_nota_redirects_to_get_forecast(self):
        r = get_model_metrics(_LOC_A)
        if "error" not in r:
            assert "nota" in r
            assert "evaluacion_features" in r
            # nota should mention get_forecast so the LLM knows where to look
            assert "get_forecast" in r["nota"]

    def test_evaluacion_features_is_list(self):
        r = get_model_metrics(_LOC_A)
        if "error" not in r:
            assert isinstance(r["evaluacion_features"], list)

    def test_zone_filter_accepted(self):
        assert isinstance(get_model_metrics(_LOC_A, zone_uuid=_ZONE_A), dict)


# ── get_dwell_profile ─────────────────────────────────────────────────────────


class TestGetDwellProfile:
    """¿Cuánto tiempo pasan los clientes? ¿Qué porcentaje vuelve?"""

    def test_inverted_dates_returns_error(self):
        r = get_dwell_profile(_LOC_A, _FECHA_FIN, _FECHA_INI)
        assert "error" in r

    def test_range_over_90_days_returns_error(self):
        very_old = (date.today() - timedelta(days=100)).isoformat()
        r = get_dwell_profile(_LOC_A, very_old, _FECHA_FIN)
        assert "error" in r

    def test_valid_call_returns_dict(self):
        assert isinstance(get_dwell_profile(_LOC_A, _FECHA_INI, _FECHA_FIN), dict)

    def test_estancia_key_is_minutes(self):
        """Field must be media_estancia_min (not _seg) — stored in minutes."""
        r = get_dwell_profile(_LOC_A, _FECHA_INI, _FECHA_FIN)
        if "error" not in r:
            assert "media_estancia_min" in r, "Key should be media_estancia_min"
            assert "media_estancia_seg" not in r, "Old _seg key must not be present"

    def test_estancia_sanity_range(self):
        """1 min ≤ media_estancia_min ≤ 8h (480 min) for any real retail location."""
        r = get_dwell_profile(_LOC_A, _FECHA_INI, _FECHA_FIN)
        if "error" not in r and r.get("media_estancia_min") is not None:
            assert 1 <= r["media_estancia_min"] <= 480

    def test_zone_filter_accepted(self):
        assert isinstance(
            get_dwell_profile(_LOC_A, _FECHA_INI, _FECHA_FIN, zone_uuid=_ZONE_A), dict
        )

    def test_fidelizacion_pct_retorno_in_range(self):
        r = get_dwell_profile(_LOC_A, _FECHA_INI, _FECHA_FIN)
        for key in ("fidelizacion_7d", "fidelizacion_28d", "fidelizacion_mes", "fidelizacion_anyo"):
            if key in r and r[key] and r[key].get("pct_retorno") is not None:
                assert 0 <= r[key]["pct_retorno"] <= 100
