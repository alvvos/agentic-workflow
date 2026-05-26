"""
Tests de filtrar_dataframe_fechas — la función que recorta el DataFrame
según el selector de periodo del sidebar.
"""
import os, sys
import pandas as pd
import pytest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Importamos solo la función, sin arrancar Dash
from src.core.utils import filtrar_dataframe_fechas


def _df(start="2025-01-01", days=60):
    fechas = pd.date_range(start, periods=days, freq="D")
    return pd.DataFrame({"fecha": fechas, "value": range(days)})


def test_ayer_devuelve_un_dia():
    df = _df()
    ayer = date.today() - timedelta(days=1)
    df_test = pd.DataFrame({"fecha": pd.to_datetime([ayer]), "value": [1]})
    result, s, e = filtrar_dataframe_fechas(df_test, "ayer", None, None, None)
    assert result is not None
    assert len(result) == 1


def test_rango_valido_filtra_correctamente():
    df = _df("2025-01-01", 90)
    result, s, e = filtrar_dataframe_fechas(df, "rango", "2025-02-01", "2025-02-28", None)
    assert result is not None
    assert result["fecha"].min() >= pd.Timestamp("2025-02-01")
    assert result["fecha"].max() <= pd.Timestamp("2025-02-28")


def test_rango_sin_datos_devuelve_none():
    df = _df("2025-01-01", 10)
    result, msg = filtrar_dataframe_fechas(df, "rango", "2026-01-01", "2026-01-31", None)
    assert result is None


def test_tipo_invalido_devuelve_none():
    df = _df()
    result, msg = filtrar_dataframe_fechas(df, "rango", None, None, None)
    assert result is None


def test_dia_concreto():
    target = "2025-03-15"
    df = pd.DataFrame({
        "fecha": pd.to_datetime(["2025-03-14", "2025-03-15", "2025-03-16"]),
        "value": [1, 2, 3]
    })
    result, s, e = filtrar_dataframe_fechas(df, "dia", None, None, target)
    assert result is not None
    assert len(result) == 1
    assert result["fecha"].iloc[0] == pd.Timestamp(target)
