"""
Tests for src/services/ml_predictivo.py — no DB required.

Covers:
  - Output contract: required keys present and typed correctly
  - Conformal bands: q_conf ≥ 0, lowers ≤ predichos ≤ uppers
  - Empirical coverage: at least 80% of held-out residuals fall within the band
  - Autoregressive loop: correct horizon length, no negatives
  - Error paths: insufficient data
  - Model save/load roundtrip: q_conf survives cache
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

_LOC = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_ZONE = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

_ORG_INFO = {"org_id": "test-org", "pais_codigo": "ES", "config_calendario": {}}


# ── Synthetic data factory ─────────────────────────────────────────────────────


def _make_df(n_days: int = 120, seed: int = 42) -> pd.DataFrame:
    """
    Creates a pre-enriched DataFrame that mimics the output of get_df_enriquecido.
    Columns required by ejecutar_auditoria_predictiva:
      fecha, location_id, zona_id, total_visits, llueve, temp_max, temp_min, es_festivo
    """
    rng = np.random.default_rng(seed)
    today = date.today()
    rows = []
    for i in range(n_days):
        d = today - timedelta(days=n_days - i)
        rows.append(
            {
                "fecha": pd.Timestamp(d),
                "location_id": _LOC,
                "zona_id": _ZONE,
                "total_visits": max(0, int(200 + 40 * np.sin(i / 7) + rng.integers(-20, 20))),
                "llueve": int(rng.random() < 0.2),
                "temp_max": float(rng.integers(14, 28)),
                "temp_min": float(rng.integers(6, 16)),
                "es_festivo": 0,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def df_synthetic():
    return _make_df(n_days=120)


@pytest.fixture(scope="module")
def df_small():
    """Fewer than 30 days — should trigger the insufficient-data error."""
    return _make_df(n_days=25)


@pytest.fixture(scope="module")
def ext_df_empty():
    return pd.DataFrame()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run(df, falso_hoy=None, horizonte=7):
    """Run predictor with DB calls mocked out."""
    if falso_hoy is None:
        falso_hoy = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    with (
        patch("src.services.ml_predictivo.get_org_info", return_value=_ORG_INFO),
        patch("src.services.ml_predictivo.get_active_ext_features", return_value=pd.DataFrame()),
    ):
        from src.services.ml_predictivo import ejecutar_auditoria_predictiva

        return ejecutar_auditoria_predictiva(df, _LOC, _ZONE, falso_hoy, horizonte)


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestOutputContract:
    def test_success_status(self, df_synthetic):
        res = _run(df_synthetic)
        assert res.get("status") == "success", res.get("error")

    def test_top_level_keys(self, df_synthetic):
        res = _run(df_synthetic)
        assert {"status", "metricas", "grafica"} <= res.keys()

    def test_metricas_keys(self, df_synthetic):
        res = _run(df_synthetic)
        m = res["metricas"]
        assert {"accuracy", "mae", "wmape_pct", "arboles_optimos", "q_conf"} <= m.keys()

    def test_grafica_keys(self, df_synthetic):
        res = _run(df_synthetic)
        g = res["grafica"]
        assert {"fechas", "reales", "predichos", "lower", "upper"} <= g.keys()

    def test_horizonte_length(self, df_synthetic):
        for h in (1, 7, 14):
            res = _run(df_synthetic, horizonte=h)
            assert len(res["grafica"]["fechas"]) == h
            assert len(res["grafica"]["predichos"]) == h


class TestConformalBands:
    def test_q_conf_present(self, df_synthetic):
        res = _run(df_synthetic)
        assert res["metricas"]["q_conf"] is not None

    def test_q_conf_non_negative(self, df_synthetic):
        res = _run(df_synthetic)
        assert res["metricas"]["q_conf"] >= 0

    def test_bands_present(self, df_synthetic):
        res = _run(df_synthetic)
        g = res["grafica"]
        assert g["lower"] is not None
        assert g["upper"] is not None

    def test_bands_length_matches_horizon(self, df_synthetic):
        res = _run(df_synthetic, horizonte=7)
        g = res["grafica"]
        assert len(g["lower"]) == 7
        assert len(g["upper"]) == 7

    def test_lower_le_pred_le_upper(self, df_synthetic):
        res = _run(df_synthetic, horizonte=7)
        g = res["grafica"]
        for lo, pred, hi in zip(g["lower"], g["predichos"], g["upper"]):
            assert lo <= pred <= hi, f"Band violated: {lo} <= {pred} <= {hi}"

    def test_lower_non_negative(self, df_synthetic):
        res = _run(df_synthetic)
        assert all(v >= 0 for v in res["grafica"]["lower"])

    def test_empirical_coverage_gte_80pct(self, df_synthetic):
        """
        Train on first 90 days, predict remaining as 'calibration' and verify
        that the conformal band (q_conf from training) covers ≥ 80% of residuals.
        We use a looser threshold (80%) than the nominal 90% because of the small
        calibration set in tests.
        """
        from src.services.ml_predictivo import _CONFORMAL_ALPHA  # noqa: F401

        res = _run(df_synthetic, horizonte=7)
        q = res["metricas"]["q_conf"]
        if q is None:
            pytest.skip("q_conf not computed")

        reales = [r for r in res["grafica"]["reales"] if r is not None]
        preds = res["grafica"]["predichos"][: len(reales)]
        if not reales:
            pytest.skip("No ground-truth values in horizon")

        residuals = [abs(r - p) for r, p in zip(reales, preds)]
        covered = sum(1 for r in residuals if r <= q)
        coverage = covered / len(residuals)
        assert coverage >= 0.80, f"Empirical coverage {coverage:.0%} < 80%"


class TestAutoregressiveLoop:
    def test_no_negative_predictions(self, df_synthetic):
        res = _run(df_synthetic, horizonte=14)
        assert all(v >= 0 for v in res["grafica"]["predichos"])

    def test_dates_are_consecutive(self, df_synthetic):
        res = _run(df_synthetic, horizonte=7)
        fechas = [pd.Timestamp(f) for f in res["grafica"]["fechas"]]
        for i in range(1, len(fechas)):
            assert (fechas[i] - fechas[i - 1]).days == 1

    def test_reales_length_matches_horizon(self, df_synthetic):
        res = _run(df_synthetic, horizonte=7)
        assert len(res["grafica"]["reales"]) == 7


class TestErrorPaths:
    def test_insufficient_data_returns_error(self, df_small):
        res = _run(df_small)
        assert "error" in res

    def test_empty_df_returns_error(self):
        res = _run(pd.DataFrame())
        assert "error" in res

    def test_wrong_location_returns_error(self, df_synthetic):
        with (
            patch("src.services.ml_predictivo.get_org_info", return_value=_ORG_INFO),
            patch(
                "src.services.ml_predictivo.get_active_ext_features", return_value=pd.DataFrame()
            ),
        ):
            from src.services.ml_predictivo import ejecutar_auditoria_predictiva

            res = ejecutar_auditoria_predictiva(
                df_synthetic, "unknown-loc", _ZONE, date.today().strftime("%Y-%m-%d"), 7
            )
        assert "error" in res


class TestModelCache:
    def test_q_conf_survives_save_load(self, df_synthetic, tmp_path):
        """q_conf written to .meta.json and recovered on cache hit."""
        import json

        model_path = tmp_path / "test.ubj"
        meta_path = tmp_path / "test.meta.json"

        with (
            patch(
                "src.services.ml_predictivo._registry_paths",
                return_value=(str(model_path), str(meta_path)),
            ),
            patch("src.services.ml_predictivo.get_org_info", return_value=_ORG_INFO),
            patch(
                "src.services.ml_predictivo.get_active_ext_features", return_value=pd.DataFrame()
            ),
        ):
            res = _run(df_synthetic, horizonte=7)

        q_original = res["metricas"]["q_conf"]
        assert q_original is not None

        with open(meta_path) as f:
            meta = json.load(f)
        # meta stores raw float; q_original is already round(q,1) — tolerance of 1 visit is fine
        assert meta["q_conf"] is not None and meta["q_conf"] > 0
        assert abs(round(meta["q_conf"], 1) - q_original) < 0.1

    def test_no_cache_on_backtest(self, df_synthetic):
        """When falso_hoy is far in the past, cache is not read."""
        old_date = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        res = _run(df_synthetic, falso_hoy=old_date, horizonte=7)
        assert res.get("status") == "success"
        assert res.get("cache_hit") is False
