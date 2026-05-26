"""
Tests de la lógica de detección de datos obsoletos del botón de sincronización.

El callback actualizar_alerta_sync calcula la fecha más atrasada entre las
ubicaciones seleccionadas (groupby location_id → max fecha → min entre locs).
Si esa fecha está más de 1 día por detrás de ayer, debe alertar.
"""
import pandas as pd
import pytest
from datetime import date, timedelta


def _fecha_mas_atrasada(df: pd.DataFrame, locs: list | None = None) -> date:
    """Extrae la lógica central del callback para poder testearla en aislamiento."""
    df = df.copy()
    df["fecha"] = pd.to_datetime(df["fecha"])
    if locs:
        df = df[df["location_id"].isin(locs)]
    return df.groupby("location_id")["fecha"].max().min().date()


def _df_multi(location_fechas: dict) -> pd.DataFrame:
    """Crea un DataFrame con varias ubicaciones y sus últimas fechas."""
    rows = []
    for loc_id, max_fecha in location_fechas.items():
        # Simulamos 7 días de datos para cada ubicación
        for d in range(7):
            rows.append({
                "location_id": loc_id,
                "fecha": pd.Timestamp(max_fecha) - timedelta(days=d),
            })
    return pd.DataFrame(rows)


# ── Lógica de fecha atrasada ──────────────────────────────────────────────────

def test_datos_frescos_no_generan_alerta():
    ayer = date.today() - timedelta(days=1)
    df = _df_multi({"loc1": ayer})
    fecha = _fecha_mas_atrasada(df)
    dias = (ayer - fecha).days
    assert dias <= 1


def test_datos_atrasados_generan_alerta():
    hace_4_dias = date.today() - timedelta(days=4)
    df = _df_multi({"loc1": hace_4_dias})
    ayer = date.today() - timedelta(days=1)
    dias = (ayer - _fecha_mas_atrasada(df)).days
    assert dias > 1


def test_la_ubicacion_mas_atrasada_determina_el_estado():
    ayer = date.today() - timedelta(days=1)
    hace_5 = date.today() - timedelta(days=5)
    df = _df_multi({"loc-fresca": ayer, "loc-vieja": hace_5})
    fecha = _fecha_mas_atrasada(df)
    # La fecha más atrasada debe ser la de loc-vieja
    assert fecha == hace_5


def test_filtro_por_locs_ignora_ubicaciones_no_seleccionadas():
    ayer = date.today() - timedelta(days=1)
    hace_10 = date.today() - timedelta(days=10)
    df = _df_multi({"loc-fresca": ayer, "loc-muy-vieja": hace_10})
    # Si solo seleccionamos loc-fresca, no debe alertar
    fecha = _fecha_mas_atrasada(df, locs=["loc-fresca"])
    dias = (ayer - fecha).days
    assert dias <= 1


def test_sin_filtro_locs_usa_todas():
    ayer = date.today() - timedelta(days=1)
    hace_6 = date.today() - timedelta(days=6)
    df = _df_multi({"loc1": ayer, "loc2": hace_6})
    fecha = _fecha_mas_atrasada(df, locs=None)
    assert fecha == hace_6


def test_una_sola_ubicacion_devuelve_su_fecha():
    hace_3 = date.today() - timedelta(days=3)
    df = _df_multi({"loc1": hace_3})
    assert _fecha_mas_atrasada(df) == hace_3
