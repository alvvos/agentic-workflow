"""
Validador del DataFrame de previsión ML (salida de ml_predictivo).

Estructura esperada:
  fecha              date / datetime   — día de la predicción (siempre futuro)
  predicted_visits   float64           — número de visitas previstas
  zone_uuid          object            — zona a la que aplica la predicción

Columnas opcionales:
  lower_bound, upper_bound   — intervalo de confianza
  model_id                   — identificador del modelo usado
"""

from __future__ import annotations

import pandas as pd

SECCION = "prevision"

_REQUERIDAS = {
    "fecha": "datetime_or_date",
    "predicted_visits": "numeric",
    "zone_uuid": "object",
}


def validar(df: pd.DataFrame) -> tuple[bool, list[str]]:
    """Valida que df tenga la estructura esperada para el panel de previsión."""
    errores: list[str] = []

    if df is None or not isinstance(df, pd.DataFrame):
        return False, ["el argumento no es un DataFrame"]
    if df.empty:
        return True, []

    for col, tipo in _REQUERIDAS.items():
        if col not in df.columns:
            errores.append(f"columna requerida ausente: '{col}'")
            continue
        if tipo == "datetime_or_date":
            if not (pd.api.types.is_datetime64_any_dtype(df[col]) or df[col].dtype == object):
                errores.append(f"'{col}' debe ser fecha o datetime (es {df[col].dtype})")
        if tipo == "numeric" and not pd.api.types.is_numeric_dtype(df[col]):
            errores.append(f"'{col}' debe ser numérica (es {df[col].dtype})")

    if "predicted_visits" in df.columns and (df["predicted_visits"] < 0).any():
        errores.append("'predicted_visits' contiene valores negativos")

    return len(errores) == 0, errores
