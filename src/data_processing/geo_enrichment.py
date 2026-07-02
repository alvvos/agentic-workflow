import pandas as pd

# ── Feature catalogue ─────────────────────────────────────────────────────────
#
# 7 señales de GeoEnrichment (isócronas + densidad + empleo + poder adquisitivo)
# + 5 scores calculados desde puntos_interes (entorno funcional).
# Diseñado para explicar variabilidad de flujos de personas, no perfil demográfico.

GEO_FEATURE_COLS = [
    # Isócronas peatonales (RingBuffer 400/800/1200 m ≈ 5/10/15 min)
    "poblacion_5min",
    "poblacion_10min",
    "poblacion_15min",
    # Intensidad de uso del área (círculo 800m, GeoEnrichment)
    "densidad_poblacion",  # KeyFacts.POPDENS_CY
    "trabajadores_zona",  # EmploymentTotalsAIS.TOTATC — proxy población diurna
    # Poder adquisitivo y perfil joven (círculo 800m, GeoEnrichment)
    "indice_poder_compra",  # KeyFacts.PPIDX_CY (100 = media nacional)
    "pob_15_29",  # KeyFacts.PAGE02_CY — target prime de tráfico juvenil
    # Entorno funcional (scores calculados desde puntos_interes)
    "n_nodos_transporte",  # metro + bus — accesibilidad
    "n_restauracion",  # restaurantes — atractor de permanencia
    "n_atracciones",  # monumentos + museos + salas — polo de destino
    "n_competidores",  # retail moda/accesorios — presión competitiva
    "n_anclas",  # supermercados + centros comerciales + hoteles — generadores de tráfico
]

# ── Esri variable mapping ─────────────────────────────────────────────────────
# {feature_col: (collection.variable, radio)} — solo las señales de GeoEnrichment
# None → calculada desde puntos_interes, no viene de GeoEnrichment
ESRI_VAR_MAP: dict = {
    "poblacion_5min": ("KeyFacts.TOTPOP_CY", "ring_400m"),
    "poblacion_10min": ("KeyFacts.TOTPOP_CY", "ring_800m"),
    "poblacion_15min": ("KeyFacts.TOTPOP_CY", "ring_1200m"),
    "densidad_poblacion": ("KeyFacts.POPDENS_CY", "circle_800m"),
    "trabajadores_zona": ("EmploymentTotalsAIS.TOTATC", "circle_800m"),
    "indice_poder_compra": ("KeyFacts.PPIDX_CY", "circle_800m"),
    "pob_15_29": ("KeyFacts.PAGE02_CY", "circle_800m"),
    "n_nodos_transporte": None,
    "n_restauracion": None,
    "n_atracciones": None,
    "n_competidores": None,
    "n_anclas": None,
}

# ── Clasificación backdatable / dinámica ──────────────────────────────────────
# Backdatable: cambio muy lento; el valor de 2026 aproxima honestamente 2024.
GEO_FEATURES_BACKDATABLE = [
    "poblacion_5min",
    "poblacion_10min",
    "poblacion_15min",
    "densidad_poblacion",
    "trabajadores_zona",
    "indice_poder_compra",
    "pob_15_29",
    "n_nodos_transporte",  # infraestructura de transporte: estable
    "n_atracciones",  # monumentos y museos: estables
]

# Dinámicas: entorno competitivo y de restauración (apertura/cierre frecuente).
GEO_FEATURES_DINAMICAS = [
    "n_restauracion",
    "n_competidores",
    "n_anclas",
]

# Cache en memoria invalidado por ubicación en cada ingesta Esri.
# Clave: (location_uuid, fecha_str | None)  →  {col: value}
_geo_cache: dict = {}


def invalidate_geo_cache(location_uuid: str = None) -> None:
    """Elimina entradas de caché. Sin argumento limpia todo."""
    if location_uuid is None:
        _geo_cache.clear()
    else:
        for k in [k for k in _geo_cache if k[0] == location_uuid]:
            del _geo_cache[k]


def _fetch_snapshot_features(location_uuid: str, fecha=None) -> dict:
    """
    Consulta snapshots_geo y devuelve {feature_key: value} del snapshot aplicable.
    Retorna dict vacío si no hay datos para esta ubicación.
    """
    from src.db.store import get_conn

    conn = get_conn()

    if fecha is None:
        row = conn.execute(
            """
            SELECT DISTINCT vigente_desde FROM snapshots_geo
            WHERE ubicacion_id = ? AND vigente_hasta IS NULL
            ORDER BY vigente_desde DESC LIMIT 1
        """,
            [location_uuid],
        ).fetchone()
        if not row:
            row = conn.execute(
                """
                SELECT DISTINCT vigente_desde FROM snapshots_geo
                WHERE ubicacion_id = ? ORDER BY vigente_desde DESC LIMIT 1
            """,
                [location_uuid],
            ).fetchone()
    else:
        fecha_str = str(fecha)[:10]
        row = conn.execute(
            """
            SELECT DISTINCT vigente_desde FROM snapshots_geo
            WHERE ubicacion_id = ?
              AND vigente_desde <= ?
              AND (vigente_hasta IS NULL OR vigente_hasta >= ?)
            ORDER BY vigente_desde DESC LIMIT 1
        """,
            [location_uuid, fecha_str, fecha_str],
        ).fetchone()

    if not row:
        return {}

    vigente_desde = row[0]
    rows = conn.execute(
        """
        SELECT señal_id, valor FROM snapshots_geo
        WHERE ubicacion_id = ? AND vigente_desde = ?
    """,
        [location_uuid, vigente_desde],
    ).fetchall()
    return {k: v for k, v in rows}


def get_geo_vals(location_uuid: str, fecha=None) -> dict:
    """
    Devuelve el snapshot geoespacial de una ubicación en un momento dado.

    - fecha=None → snapshot activo más reciente (para predicción de fechas futuras).
    - fecha=<date> → snapshot cuyo intervalo [vigente_desde, vigente_hasta] contiene esa fecha
      (para training: evita data leakage de datos futuros en filas históricas).

    Si no hay snapshot aplicable devuelve None en todos los campos, lo que hace que
    get_geo_features_activos() devuelva lista vacía y el modelo ignore las geo features.
    """
    cache_key = (location_uuid, str(fecha)[:10] if fecha is not None else None)
    if cache_key in _geo_cache:
        return _geo_cache[cache_key]

    raw = _fetch_snapshot_features(location_uuid, fecha)
    result = {col: raw.get(col) for col in GEO_FEATURE_COLS}
    _geo_cache[cache_key] = result
    return result


def get_geo_features_activos(location_uuid: str, fecha=None) -> list:
    """Devuelve los nombres de features con valor no nulo en el snapshot aplicable."""
    vals = get_geo_vals(location_uuid, fecha)
    return [col for col, v in vals.items() if v is not None]


def enriquecer_con_geo(
    df: pd.DataFrame, col_location_id: str = "location_id", col_fecha: str = "fecha"
) -> pd.DataFrame:
    """
    Join temporal geoespacial sobre un DataFrame multi-ubicación.

    Para cada fila, busca el snapshot válido en su fecha (o el activo si no hay col_fecha).
    Solo añade columnas que tengan al menos un valor no nulo en el resultado.
    No-op si el store está vacío o todos los valores son null.
    """
    if col_location_id not in df.columns:
        return df

    usa_fecha = col_fecha in df.columns

    def _lookup(row):
        fecha = row[col_fecha] if usa_fecha else None
        return get_geo_vals(row[col_location_id], fecha)

    geo_df = df[[col_location_id] + ([col_fecha] if usa_fecha else [])].apply(
        _lookup, axis=1, result_type="expand"
    )

    cols_con_dato = [c for c in GEO_FEATURE_COLS if c in geo_df.columns and geo_df[c].notna().any()]
    if not cols_con_dato:
        return df

    for col in cols_con_dato:
        df = df.copy()
        df[col] = geo_df[col].values

    return df


def get_catchment_rings(location_uuid: str):
    """Retorna geometría de isócronas peatonales almacenada en ubicaciones."""
    import json

    from src.db.store import get_conn

    row = (
        get_conn()
        .execute(
            "SELECT catchment_rings_json FROM ubicaciones WHERE ubicacion_id = ?",
            [location_uuid],
        )
        .fetchone()
    )
    if row and row[0]:
        try:
            return json.loads(row[0])
        except Exception:
            return None
    return None


def get_geo_snapshot_date(location_uuid: str) -> str | None:
    """Returns the vigente_desde date of the active geo snapshot, or None if no data."""
    from src.db.store import get_conn

    row = (
        get_conn()
        .execute(
            """
        SELECT vigente_desde FROM snapshots_geo
        WHERE ubicacion_id = ? AND vigente_hasta IS NULL
        ORDER BY vigente_desde DESC LIMIT 1
    """,
            [location_uuid],
        )
        .fetchone()
    )
    if row:
        return str(row[0])
    row = (
        get_conn()
        .execute(
            """
        SELECT vigente_desde FROM snapshots_geo
        WHERE ubicacion_id = ? ORDER BY vigente_desde DESC LIMIT 1
    """,
            [location_uuid],
        )
        .fetchone()
    )
    return str(row[0]) if row else None
