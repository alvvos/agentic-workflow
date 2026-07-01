"""
Validador del DataFrame de señales externas (store_features_ext).

Estructura estándar de cualquier consulta a store_features_ext:
  fecha           date / datetime   — fecha del valor
  location_uuid   object            — UUID de la ubicación
  feature_key     object            — clave de la señal (ej. 'n_pasajeros_crucero_oficial')
  value           float64           — valor de la señal ese día

Este validador aplica a todas las señales de contexto,
independientemente de cuántas fuentes de ingesta las produzcan.
"""

from __future__ import annotations

import pandas as pd

SECCION = "features_ext"

_REQUERIDAS = {
    "fecha": "datetime_or_date",
    "location_uuid": "object",
    "feature_key": "object",
    "value": "numeric",
}


def validar(df: pd.DataFrame) -> tuple[bool, list[str]]:
    """Valida que df tenga la estructura esperada para secciones de señales externas."""
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
            es_datetime = pd.api.types.is_datetime64_any_dtype(df[col])
            es_object = df[col].dtype == object  # podría ser strings de fecha
            if not (es_datetime or es_object):
                errores.append(f"'{col}' debe ser fecha o datetime (es {df[col].dtype})")
        if tipo == "numeric" and not pd.api.types.is_numeric_dtype(df[col]):
            errores.append(f"'{col}' debe ser numérica (es {df[col].dtype})")

    if "feature_key" in df.columns and df["feature_key"].isnull().all():
        errores.append("'feature_key' está completamente nula")

    return len(errores) == 0, errores
