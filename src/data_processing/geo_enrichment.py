import pandas as pd

# ── Feature catalogue ─────────────────────────────────────────────────────────
#
# 7 señales de GeoEnrichment (isócronas + densidad + empleo + poder adquisitivo)
# + 5 scores calculados desde puntos_interes (entorno funcional).
# Diseñado para explicar variabilidad de flujos de personas, no perfil demográfico.

GEO_FEATURE_COLS = [
    # Isócronas peatonales
    "poblacion_5min",
    "poblacion_10min",
    "poblacion_15min",
    # Densidad e intensidad (GeoEnrichment 800m)
    "densidad_poblacion",
    "trabajadores_zona",
    "indice_poder_compra",
    "pob_15_29",
    # Edad — pirámide quinquenal (GeoEnrichment 800m)
    "pob_0_4",
    "pob_5_9",
    "pob_10_14",
    "pob_15_19",
    "pob_20_24",
    "pob_25_29",
    "pob_30_34",
    "pob_35_39",
    "pob_40_44",
    "pob_45_49",
    "pob_50_54",
    "pob_55_59",
    "pob_60_64",
    "pob_65_69",
    "pob_70_74",
    "pob_75_79",
    "pob_80_84",
    "pob_85_plus",
    # Renta y composición del hogar
    "renta_hogar_anual",
    "renta_per_capita",
    "n_hogares_total",
    "hogares_renta_alta",
    "hogares_renta_media_alta",
    "hogares_jovenes_solos",
    "hogares_parejas_jovenes",
    "hogares_familias_hijos",
    "en_riesgo_pobreza_pct",
    # Gasto de consumidor
    "gasto_cuidado_personal",
    "gasto_ocio_cultura",
    "gasto_vacaciones",
    "gasto_restaurantes",
    "gasto_alimentacion",
    "gasto_transporte",
    # Mercado laboral
    "tasa_desempleo",
    "tasa_desempleo_jovenes",
    # Canal online / omnicanalidad
    "pct_compras_online",
    "online_ropa_deporte_pct",
    "online_ultimo_mes_pct",
    # Entorno funcional (scores calculados desde puntos_interes)
    "n_nodos_transporte",
    "n_restauracion",
    "n_atracciones",
    "n_competidores",
    "n_anclas",
]

# ── Esri variable mapping ─────────────────────────────────────────────────────
# {feature_col: (collection.variable, radio)} — solo las señales de GeoEnrichment
# None → calculada desde puntos_interes
ESRI_VAR_MAP: dict = {
    "poblacion_5min": ("KeyFacts.TOTPOP_CY", "ring_400m"),
    "poblacion_10min": ("KeyFacts.TOTPOP_CY", "ring_800m"),
    "poblacion_15min": ("KeyFacts.TOTPOP_CY", "ring_1200m"),
    "densidad_poblacion": ("KeyFacts.POPDENS_CY", "circle_800m"),
    "trabajadores_zona": ("EmploymentTotalsAIS.TOTATC", "circle_800m"),
    "indice_poder_compra": ("KeyFacts.PPIDX_CY", "circle_800m"),
    "pob_15_29": ("KeyFacts.PAGE02_CY", "circle_800m"),
    "pob_0_4": ("5YearIncrementsAIS.POPAG00", "circle_800m"),
    "pob_5_9": ("5YearIncrementsAIS.POPAG05", "circle_800m"),
    "pob_10_14": ("5YearIncrementsAIS.POPAG10", "circle_800m"),
    "pob_15_19": ("5YearIncrementsAIS.POPAG15", "circle_800m"),
    "pob_20_24": ("5YearIncrementsAIS.POPAG20", "circle_800m"),
    "pob_25_29": ("5YearIncrementsAIS.POPAG25", "circle_800m"),
    "pob_30_34": ("5YearIncrementsAIS.POPAG30", "circle_800m"),
    "pob_35_39": ("5YearIncrementsAIS.POPAG35", "circle_800m"),
    "pob_40_44": ("5YearIncrementsAIS.POPAG40", "circle_800m"),
    "pob_45_49": ("5YearIncrementsAIS.POPAG45", "circle_800m"),
    "pob_50_54": ("5YearIncrementsAIS.POPAG50", "circle_800m"),
    "pob_55_59": ("5YearIncrementsAIS.POPAG55", "circle_800m"),
    "pob_60_64": ("5YearIncrementsAIS.POPAG60", "circle_800m"),
    "pob_65_69": ("5YearIncrementsAIS.POPAG65", "circle_800m"),
    "pob_70_74": ("5YearIncrementsAIS.POPAG70", "circle_800m"),
    "pob_75_79": ("5YearIncrementsAIS.POPAG75", "circle_800m"),
    "pob_80_84": ("5YearIncrementsAIS.POPAG80", "circle_800m"),
    "pob_85_plus": ("5YearIncrementsAIS.POPAG85", "circle_800m"),
    "renta_hogar_anual": ("IncomeTotalsAIS.NINCHA", "circle_800m"),
    "renta_per_capita": ("IncomeTotalsAIS.NINCCA", "circle_800m"),
    "n_hogares_total": ("HouseholdTotalsAIS.HHOLDS", "circle_800m"),
    "hogares_renta_alta": ("HouseholdsByIncomeAIS.THINC5M", "circle_800m"),
    "hogares_renta_media_alta": ("HouseholdsByIncomeAIS.THINC4M", "circle_800m"),
    "hogares_jovenes_solos": ("IncomeTotalsAIS.TOTYOSI", "circle_800m"),
    "hogares_parejas_jovenes": ("IncomeTotalsAIS.TOTYOCO", "circle_800m"),
    "hogares_familias_hijos": ("IncomeTotalsAIS.TOTFUSMA", "circle_800m"),
    "en_riesgo_pobreza_pct": ("HouseholdsByIncomeAIS.HORIPOYE", "circle_800m"),
    "gasto_cuidado_personal": ("SpendingTotalsAIS.SPPCARE", "circle_800m"),
    "gasto_ocio_cultura": ("EntertainmentAIS.SPLEISU", "circle_800m"),
    "gasto_vacaciones": ("EntertainmentAIS.SPLHOLI", "circle_800m"),
    "gasto_restaurantes": ("MiscellaneousAIS.SPHOTRE", "circle_800m"),
    "gasto_alimentacion": ("FoodAndDrinksAIS.SPFOODR", "circle_800m"),
    "gasto_transporte": ("TransportationAIS.SPTRANS", "circle_800m"),
    "tasa_desempleo": ("EmploymentTotalsAIS.UNERATE", "circle_800m"),
    "tasa_desempleo_jovenes": ("EmploymentTotalsAIS.UNERATE24", "circle_800m"),
    "pct_compras_online": ("OnlineShoppingAIS.PUTHINT", "circle_800m"),
    "online_ropa_deporte_pct": ("OnlineShoppingAIS.PROPURSPO", "circle_800m"),
    "online_ultimo_mes_pct": ("OnlineShoppingAIS.WHELAIN", "circle_800m"),
    "n_nodos_transporte": None,
    "n_restauracion": None,
    "n_atracciones": None,
    "n_competidores": None,
    "n_anclas": None,
}

# Cache en memoria por ubicacion_id (se invalida en cada ingesta)
_geo_cache: dict[str, dict] = {}


def invalidate_geo_cache(location_uuid: str | None = None) -> None:
    if location_uuid is None:
        _geo_cache.clear()
    else:
        _geo_cache.pop(location_uuid, None)


def get_geo_vals(location_uuid: str, fecha=None) -> dict:  # fecha ignorado — modelo plano
    """
    Devuelve el snapshot geoespacial actual de una ubicación.
    Si no hay datos devuelve None en todos los campos (graceful degradation).
    """
    if location_uuid in _geo_cache:
        return _geo_cache[location_uuid]

    from src.db.store import get_conn

    rows = (
        get_conn()
        .execute(
            "SELECT señal_id, valor FROM snapshots_geo WHERE ubicacion_id = ?",
            [location_uuid],
        )
        .fetchall()
    )

    raw = {k: v for k, v in rows}
    result = {col: raw.get(col) for col in GEO_FEATURE_COLS}
    _geo_cache[location_uuid] = result
    return result


def get_geo_features_activos(location_uuid: str, fecha=None) -> list:
    """Devuelve los nombres de features con valor no nulo en el snapshot actual."""
    return [col for col, v in get_geo_vals(location_uuid).items() if v is not None]


def ingestar_snapshot(location_uuid: str, valores: dict) -> int:
    """
    Reemplaza el snapshot geo de una ubicación. Borra lo anterior y escribe lo nuevo.
    valores: {señal_id: valor_numérico}
    Devuelve el número de features insertadas.
    """
    from src.db.store import get_conn

    conn = get_conn()
    conn.execute("DELETE FROM snapshots_geo WHERE ubicacion_id = ?", [location_uuid])
    datos = [
        (location_uuid, k, float(v))
        for k, v in valores.items()
        if v is not None and k in GEO_FEATURE_COLS
    ]
    if datos:
        conn.executemany(
            "INSERT INTO snapshots_geo (ubicacion_id, señal_id, valor) VALUES (?, ?, ?)",
            datos,
        )
    invalidate_geo_cache(location_uuid)
    return len(datos)


def enriquecer_con_geo(
    df: pd.DataFrame, col_location_id: str = "location_id", col_fecha: str = "fecha"
) -> pd.DataFrame:
    """
    Añade columnas geo al DataFrame. Un snapshot por ubicación (sin join temporal).
    No-op si el store está vacío o todos los valores son null.
    """
    if col_location_id not in df.columns:
        return df

    geo_rows = []
    for loc_id in df[col_location_id].unique():
        vals = get_geo_vals(loc_id)
        vals[col_location_id] = loc_id
        geo_rows.append(vals)

    if not geo_rows:
        return df

    geo_df = pd.DataFrame(geo_rows).set_index(col_location_id)
    cols_con_dato = [c for c in GEO_FEATURE_COLS if c in geo_df.columns and geo_df[c].notna().any()]
    if not cols_con_dato:
        return df

    df = df.copy()
    for col in cols_con_dato:
        df[col] = df[col_location_id].map(geo_df[col])
    return df


def get_catchment_rings(location_uuid: str):
    """Retorna geometría de isócronas peatonales almacenada en ubicaciones."""
    import json

    from src.db.store import get_conn

    row = (
        get_conn()
        .execute(
            "SELECT anillos_captacion FROM ubicaciones WHERE ubicacion_id = ?",
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
    """Fecha de la última actualización del snapshot geo, o None si no hay datos."""
    from src.db.store import get_conn

    row = (
        get_conn()
        .execute(
            "SELECT MAX(actualizado_en) FROM snapshots_geo WHERE ubicacion_id = ?",
            [location_uuid],
        )
        .fetchone()
    )
    return str(row[0])[:10] if row and row[0] else None
