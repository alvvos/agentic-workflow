"""
Validador del DataFrame de eventos del calendario (store_calendario_org).

Estructura estándar de cualquier consulta a store_calendario_org:
  fecha_inicio    date / datetime   — comienzo del evento
  fecha_fin       date / datetime   — fin del evento
  evento_key      object            — tipo de evento (ej. 'holiday', 'escala_crucero')
  fuente          object            — origen (ej. 'open_holidays', 'cruceros', 'manual')

Columnas opcionales:
  org_uuid, location_uuid, pais_codigo, metadata
"""

from __future__ import annotations

import pandas as pd

SECCION = "calendario"

_REQUERIDAS = {
    "fecha_inicio": "datetime_or_date",
    "fecha_fin": "datetime_or_date",
    "evento_key": "object",
    "fuente": "object",
}


def _es_fecha(serie: pd.Series) -> bool:
    return pd.api.types.is_datetime64_any_dtype(serie) or serie.dtype == object


def validar(df: pd.DataFrame) -> tuple[bool, list[str]]:
    """Valida que df tenga la estructura esperada para secciones de calendario."""
    errores: list[str] = []

    if df is None or not isinstance(df, pd.DataFrame):
        return False, ["el argumento no es un DataFrame"]
    if df.empty:
        return True, []

    for col, tipo in _REQUERIDAS.items():
        if col not in df.columns:
            errores.append(f"columna requerida ausente: '{col}'")
            continue
        if tipo == "datetime_or_date" and not _es_fecha(df[col]):
            errores.append(f"'{col}' debe ser fecha o datetime (es {df[col].dtype})")

    if "fecha_inicio" in df.columns and "fecha_fin" in df.columns:
        try:
            fi = pd.to_datetime(df["fecha_inicio"])
            ff = pd.to_datetime(df["fecha_fin"])
            if (ff < fi).any():
                errores.append("hay filas con fecha_fin anterior a fecha_inicio")
        except Exception:
            pass

    return len(errores) == 0, errores
