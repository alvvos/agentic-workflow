"""
Validador del DataFrame de visitas (fact_visitas → get_df_visitas).

Columnas garantizadas por get_df_visitas():
  fecha           datetime64     — fecha del registro
  location_id     object         — UUID de la ubicación (alias de location_uuid)
  zone_uuid       object         — UUID de la zona
  total_visits    int64          — visitas totales del día
  unique_visitors int64          — visitantes únicos
  new_visitors    int64          — visitantes nuevos

Columnas opcionales:
  uv_7d, uv_28d, uv_month, uv_year,
  freq_7d, freq_28d, freq_month, freq_year,
  dwell_time, dwell_hist, hourly_visits
"""

from __future__ import annotations

import pandas as pd

SECCION = "visitas"

_REQUERIDAS = {
    "fecha": "datetime64",
    "location_id": "object",
    "zone_uuid": "object",
    "total_visits": "numeric",
    "unique_visitors": "numeric",
}


def validar(df: pd.DataFrame) -> tuple[bool, list[str]]:
    """Valida que df tenga la estructura esperada para el panel de visitas."""
    errores: list[str] = []

    if df is None or not isinstance(df, pd.DataFrame):
        return False, ["el argumento no es un DataFrame"]
    if df.empty:
        return True, []  # vacío es válido — el panel lo gestiona

    for col, tipo in _REQUERIDAS.items():
        if col not in df.columns:
            errores.append(f"columna requerida ausente: '{col}'")
            continue
        if tipo == "datetime64" and not pd.api.types.is_datetime64_any_dtype(df[col]):
            errores.append(f"'{col}' debe ser datetime (es {df[col].dtype})")
        if tipo == "numeric" and not pd.api.types.is_numeric_dtype(df[col]):
            errores.append(f"'{col}' debe ser numérica (es {df[col].dtype})")

    return len(errores) == 0, errores
