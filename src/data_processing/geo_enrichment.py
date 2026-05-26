import json
import pandas as pd
from pathlib import Path

_GEO_PATH = Path(__file__).parent.parent / "data" / "geo_features.json"

# Fuente única de verdad para los nombres de features geoespaciales.
# Orden refleja los 3 bloques de la propuesta:
#   Bloque 1 — Isócronas peatonales (Esri Network Analysis)
#   Bloque 2 — Densidad comercial y movilidad (Esri Business Analyst / Heat Map)
#   Bloque 3 — POIs y transporte (Esri routing + POI layer)
#   Macro    — Sociodemográfico por CP (spatial join punto-en-polígono censal)
GEO_FEATURE_COLS = [
    "poblacion_5min",
    "poblacion_10min",
    "poblacion_15min",
    "densidad_comercial_score",
    "indice_movilidad_peatonal",
    "dist_transporte_min_m",
    "n_competidores_500m",
    "dist_competidor_cercano_m",
    "renta_media_cp",
    "poblacion_cp",
]

# Features estructurales: cambian despacio (censo anual INE/INEGI, infraestructura urbana).
# En la primera entrega de Esri se back-datean hasta el inicio del histórico de training.
# El modelo puede aprender la correlación entre contexto de fondo y tráfico a lo largo
# de todo el periodo disponible, maximizando la señal.
GEO_FEATURES_BACKDATABLE = [
    "poblacion_5min",
    "poblacion_10min",
    "poblacion_15min",
    "dist_transporte_min_m",
    "renta_media_cp",
    "poblacion_cp",
]

# Features dinámicas: cambian con el entorno competitivo y de movilidad.
# Un competidor que abrió en 2026 no existía en 2024 — back-datear estos valores
# introduciría sesgo al decirle al modelo que el pasado tenía el mismo contexto que hoy.
# Solo se registran desde la fecha real de entrega de Esri.
GEO_FEATURES_DINAMICAS = [
    "densidad_comercial_score",
    "indice_movilidad_peatonal",
    "n_competidores_500m",
    "dist_competidor_cercano_m",
]

# Cache con invalidación por mtime — evita releer el JSON en cada llamada durante training
_store_cache: dict = {}
_store_mtime: float = 0.0


def _cargar_store() -> dict:
    global _store_cache, _store_mtime
    if not _GEO_PATH.exists():
        return {}
    mtime = _GEO_PATH.stat().st_mtime
    if not _store_cache or _store_mtime != mtime:
        with open(_GEO_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _store_cache = {k: v for k, v in data.items() if not k.startswith("_")}
        _store_mtime = mtime
    return _store_cache


def get_geo_vals(location_uuid: str, fecha=None) -> dict:
    """
    Devuelve el snapshot geoespacial de una ubicación en un momento dado.

    - fecha=None → snapshot activo más reciente (para predicción de fechas futuras).
    - fecha=<date> → snapshot cuyo intervalo [valid_from, valid_to] contiene esa fecha
      (para training: evita data leakage de datos futuros en filas históricas).

    Si no hay snapshot aplicable devuelve None en todos los campos, lo que hace que
    get_geo_features_activos() devuelva lista vacía y el modelo ignore las geo features.
    """
    store = _cargar_store()
    snapshots = store.get(location_uuid, [])
    if not snapshots:
        return {col: None for col in GEO_FEATURE_COLS}

    # Snapshots ordenados cronológicamente (por si el JSON no lo está)
    snapshots_ord = sorted(snapshots, key=lambda s: s.get("valid_from", ""))

    if fecha is None:
        # Snapshot activo: valid_to=null, o el más reciente si todos tienen cierre
        activo = next((s for s in reversed(snapshots_ord) if s.get("valid_to") is None), None)
        target = activo or snapshots_ord[-1]
    else:
        ts = pd.Timestamp(fecha)
        target = None
        for s in snapshots_ord:
            vf = pd.Timestamp(s.get("valid_from", "1900-01-01"))
            vt = pd.Timestamp(s["valid_to"]) if s.get("valid_to") else pd.Timestamp.max
            if vf <= ts <= vt:
                target = s
                break
        if target is None:
            return {col: None for col in GEO_FEATURE_COLS}

    return {col: target.get(col) for col in GEO_FEATURE_COLS}


def get_geo_features_activos(location_uuid: str, fecha=None) -> list:
    """Devuelve los nombres de features con valor no nulo en el snapshot aplicable."""
    vals = get_geo_vals(location_uuid, fecha)
    return [col for col, v in vals.items() if v is not None]


def enriquecer_con_geo(df: pd.DataFrame, col_location_id: str = "location_id", col_fecha: str = "fecha") -> pd.DataFrame:
    """
    Join temporal geoespacial sobre un DataFrame multi-ubicación.

    Para cada fila, busca el snapshot válido en su fecha (o el activo si no hay col_fecha).
    Solo añade columnas que tengan al menos un valor no nulo en el resultado.
    No-op si el store está vacío o todos los valores son null.
    """
    store = _cargar_store()
    if not store:
        return df

    usa_fecha = col_fecha in df.columns

    def _lookup(row):
        fecha = row[col_fecha] if usa_fecha else None
        return get_geo_vals(row[col_location_id], fecha)

    if col_location_id not in df.columns:
        return df

    geo_df = df[[col_location_id] + ([col_fecha] if usa_fecha else [])].apply(_lookup, axis=1, result_type="expand")

    cols_con_dato = [c for c in GEO_FEATURE_COLS if c in geo_df.columns and geo_df[c].notna().any()]
    if not cols_con_dato:
        return df

    for col in cols_con_dato:
        df = df.copy()
        df[col] = geo_df[col].values

    return df


def get_geo_snapshot_date(location_uuid: str) -> str | None:
    """Returns the valid_from date of the active geo snapshot, or None if no data."""
    store = _cargar_store()
    snapshots = store.get(location_uuid, [])
    if not snapshots:
        return None
    snapshots_ord = sorted(snapshots, key=lambda s: s.get("valid_from", ""))
    activo = next((s for s in reversed(snapshots_ord) if s.get("valid_to") is None), None)
    target = activo or snapshots_ord[-1]
    return target.get("valid_from")
