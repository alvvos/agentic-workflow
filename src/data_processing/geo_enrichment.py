import pandas as pd

# ── Feature catalogue ─────────────────────────────────────────────────────────
#
# Escenario rico (piloto Miniso, 2026-05-27):
#   Bloque 1 — Isócronas por radio de caminata (Esri GeoEnrichment, RingBuffer)
#   Bloque 2 — Renta y composición de hogar (Esri AIS España, radio 800m)
#   Bloque 3 — Gasto de consumidor retail (Esri AIS España, radio 800m)
#   Bloque 4 — Mercado laboral (Esri AIS España, radio 800m)
#   Bloque 5 — Entorno competitivo y accesibilidad (Esri Places+Routing, fase 2)

GEO_FEATURE_COLS = [
    # Bloque 1 — Isócronas peatonales (RingBuffer 400/800/1200 m ≈ 5/10/15 min)
    "poblacion_5min",  # PEOPLE @ 400 m
    "poblacion_10min",  # PEOPLE @ 800 m
    "poblacion_15min",  # PEOPLE @ 1 200 m
    # Bloque 2 — Demografía por edad (radio 800 m) — pirámide completa
    "pob_0_4",  # POPAG0  — primera infancia
    "pob_5_9",  # POPAG5  — infancia
    "pob_10_14",  # POPAG10 — preadolescentes
    "pob_15_19",  # POPAG15 — adolescentes        ← target Miniso
    "pob_20_24",  # POPAG20 — jóvenes adultos      ← target Miniso
    "pob_25_29",  # POPAG25 — peak gasto lifestyle ← target Miniso ★
    "pob_30_34",  # POPAG30 — familias jóvenes     ← target Miniso ★
    "pob_35_39",  # POPAG35 — adultos establecidos ← target Miniso
    "pob_40_44",  # POPAG40
    "pob_45_49",  # POPAG45
    "pob_50_54",  # POPAG50
    "pob_55_59",  # POPAG55
    "pob_60_64",  # POPAG60
    "pob_65_69",  # POPAG65
    "pob_70_74",  # POPAG70
    "pob_75_79",  # POPAG75
    "pob_80_84",  # POPAG80
    "pob_85_plus",  # POPAG85 — 85 y más
    # Bloque 3 — Renta y composición de hogar (radio 800 m)
    "renta_hogar_anual",  # NINCHA  — renta media anual del hogar (€)
    "renta_hogar_mensual",  # NINCHM  — renta media mensual del hogar (€)
    "renta_per_capita",  # NINCCA  — renta media anual per cápita (€)
    "n_hogares_total",  # HHOLDS  — total hogares (tamaño mercado)
    "tamanio_medio_hogar",  # PEOFAM  — personas por hogar
    "hogares_renta_alta",  # THINC5M — hogares >€2 589/mes
    "hogares_renta_media_alta",  # THINC4M — hogares €2 122–€2 589/mes (sweet spot Miniso)
    "hogares_jovenes_solos",  # TOTYOSI — solteros <35 años
    "hogares_parejas_jovenes",  # TOTYOCO — parejas <35 años
    "hogares_parejas_adultas",  # TOTADCO — parejas 35-64 años
    "hogares_familias_hijos",  # TOTFUSMA — familias con hijos <16 años
    "hogares_monoparentales",  # TOTSIFA — familias monoparentales
    # Bloque 4 — Salud financiera del hogar (radio 800 m)
    "puede_afrontar_imprevistos_pct",  # DOCAYE  — % hogares que pueden cubrir imprevistos
    "llega_mes_con_facilidad_pct",  # HOMAEASE — % hogares que llegan a fin de mes con facilidad
    "en_riesgo_pobreza_pct",  # HORIPOYE — % hogares en riesgo de pobreza
    # Bloque 5 — Gasto de consumidor en categorías retail (€/hogar/año, radio 800 m)
    "gasto_ropa_calzado",  # SPCLOFO — ropa + calzado (señal directa Miniso)
    "gasto_ropa",  # SPCLOTH — solo ropa
    "gasto_calzado",  # SPFOOTW — solo calzado
    "gasto_cuidado_personal",  # SPPCARE — belleza y aseo personal
    "gasto_ocio_cultura",  # SPLEISU — ocio, entretenimiento, cultura
    "gasto_vacaciones",  # SPLHOLI — vacaciones all-inclusive (renta disponible)
    "gasto_restaurantes",  # SPHOTRE — hoteles, cafés, restaurantes
    "gasto_alimentacion",  # SPFOODR — alimentación y bebidas no alcohólicas
    "gasto_transporte",  # SPTRANS — transporte (proxy movilidad)
    "gasto_comunicaciones",  # SPCOMM  — comunicaciones (proxy digital)
    # Bloque 6 — Mercado laboral (radio 800 m)
    "tasa_desempleo",  # UNERATE   — desempleo total
    "tasa_desempleo_jovenes",  # UNERATE24 — desempleo <24 años
    "empleados_por_hogar",  # TOTOCCME  — empleados por hogar
    "tasa_riesgo_pobreza",  # RISPORA   — tasa riesgo pobreza
    # Bloque 7 — Canal online (radio 800 m)
    "pct_compras_online",  # PUTHINT    — % población que compra online
    "online_ropa_deporte_pct",  # PROPURSPO  — % online en ropa/deporte
    "online_ultimo_mes_pct",  # WHELAIN    — compradores online activos (último mes)
    # Bloque 6 — Precio inmobiliario y poder de compra
    "precio_piso_alquiler",  # AVPRIRENP — precio medio alquiler piso (€/mes, proxy gentrificación)
    "indice_poder_compra",  # PPIDX_CY  — índice poder de compra (media nacional = 100)
    "poder_compra_pc",  # PPPC_CY   — poder de compra per cápita (€)
    # Bloque 9 — Entorno competitivo y accesibilidad (fase 2: Places + Routing)
    "densidad_comercial_score",
    "indice_movilidad_peatonal",
    "dist_transporte_min_m",
    "n_competidores_500m",
    "dist_competidor_cercano_m",
]

# ── Esri variable mapping ─────────────────────────────────────────────────────
# {feature_col: (collection.variable, radio)}
# radio: "ring_400m" | "ring_800m" | "ring_1200m" | "circle_800m"
# None → no proviene de GeoEnrichment (fase 2, Places/Routing)
#
# NOTA: las poblaciones de isócrona son acumuladas (suma de bandas anulares).
# El resto de variables se obtienen en un círculo único de 800m.
ESRI_VAR_MAP: dict = {
    # Bloque 1 — Isócronas peatonales (ring buffer, acumulado)
    "poblacion_5min": ("KeyFacts.TOTPOP_CY", "ring_400m"),
    "poblacion_10min": ("KeyFacts.TOTPOP_CY", "ring_800m"),
    "poblacion_15min": ("KeyFacts.TOTPOP_CY", "ring_1200m"),
    # Bloque 2 — Edad 5 años (5YearIncrementsAIS, círculo 800m)
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
    # Bloque 3 — Renta y hogar
    "renta_hogar_anual": ("IncomeTotalsAIS.NINCHA", "circle_800m"),
    "renta_hogar_mensual": ("IncomeTotalsAIS.NINCHM", "circle_800m"),
    "renta_per_capita": ("IncomeTotalsAIS.NINCCA", "circle_800m"),
    "n_hogares_total": ("HouseholdTotalsAIS.HHOLDS", "circle_800m"),
    "tamanio_medio_hogar": ("HouseholdTotalsAIS.PEOFAM", "circle_800m"),
    "hogares_renta_alta": ("HouseholdsByIncomeAIS.THINC5M", "circle_800m"),
    "hogares_renta_media_alta": ("HouseholdsByIncomeAIS.THINC4M", "circle_800m"),
    "hogares_jovenes_solos": ("IncomeTotalsAIS.TOTYOSI", "circle_800m"),
    "hogares_parejas_jovenes": ("IncomeTotalsAIS.TOTYOCO", "circle_800m"),
    "hogares_parejas_adultas": ("IncomeTotalsAIS.TOTADCO", "circle_800m"),
    "hogares_familias_hijos": ("IncomeTotalsAIS.TOTFUSMA", "circle_800m"),
    "hogares_monoparentales": ("IncomeTotalsAIS.TOTSIFA", "circle_800m"),
    # Bloque 4 — Salud financiera
    "puede_afrontar_imprevistos_pct": ("HouseholdsByIncomeAIS.DOCAYE", "circle_800m"),
    "llega_mes_con_facilidad_pct": ("HouseholdsByIncomeAIS.HOMAEASE", "circle_800m"),
    "en_riesgo_pobreza_pct": ("HouseholdsByIncomeAIS.HORIPOYE", "circle_800m"),
    # Bloque 5 — Gasto retail
    "gasto_ropa_calzado": ("ClothingAIS.SPCLOFO", "circle_800m"),
    "gasto_ropa": ("ClothingAIS.SPCLOTH", "circle_800m"),
    "gasto_calzado": ("ClothingAIS.SPFOOTW", "circle_800m"),
    "gasto_cuidado_personal": ("SpendingTotalsAIS.SPPCARE", "circle_800m"),
    "gasto_ocio_cultura": ("EntertainmentAIS.SPLEISU", "circle_800m"),
    "gasto_vacaciones": ("EntertainmentAIS.SPLHOLI", "circle_800m"),
    "gasto_restaurantes": ("MiscellaneousAIS.SPHOTRE", "circle_800m"),
    "gasto_alimentacion": ("FoodAndDrinksAIS.SPFOODR", "circle_800m"),
    "gasto_transporte": ("TransportationAIS.SPTRANS", "circle_800m"),
    "gasto_comunicaciones": ("MiscellaneousAIS.SPCOMM", "circle_800m"),
    # Bloque 6 — Empleo
    "tasa_desempleo": ("EmploymentTotalsAIS.UNERATE", "circle_800m"),
    "tasa_desempleo_jovenes": ("EmploymentTotalsAIS.UNERATE24", "circle_800m"),
    "empleados_por_hogar": ("EmploymentTotalsAIS.TOTOCCME", "circle_800m"),
    "tasa_riesgo_pobreza": None,  # RISPORA no existe en la API; usar en_riesgo_pobreza_pct
    # Bloque 7 — Canal online
    "pct_compras_online": ("OnlineShoppingAIS.PUTHINT", "circle_800m"),
    "online_ropa_deporte_pct": ("OnlineShoppingAIS.PROPURSPO", "circle_800m"),
    "online_ultimo_mes_pct": ("OnlineShoppingAIS.WHELAIN", "circle_800m"),
    # Bloque 8 — Precio inmobiliario y poder de compra
    "precio_piso_alquiler": ("PropertyValueAIS.AVPRIRENP", "circle_800m"),
    "indice_poder_compra": ("KeyFacts.PPIDX_CY", "circle_800m"),
    "poder_compra_pc": ("KeyFacts.PPPC_CY", "circle_800m"),
    # Fase 2 — no vienen de GeoEnrichment
    "densidad_comercial_score": None,
    "indice_movilidad_peatonal": None,
    "dist_transporte_min_m": None,
    "n_competidores_500m": None,
    "dist_competidor_cercano_m": None,
}

# ── Clasificación backdatable / dinámica ──────────────────────────────────────
# Backdatable: datos de censo AIS (~2 años ciclo de actualización).
# El valor de 2026 es una aproximación honesta del valor en 2024.
GEO_FEATURES_BACKDATABLE = [
    # Isócronas
    "poblacion_5min",
    "poblacion_10min",
    "poblacion_15min",
    # Edad — pirámide completa
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
    # Renta y hogar — datos AIS 2023, valor honesto como aproximación de 2024
    "renta_hogar_anual",
    "renta_hogar_mensual",
    "renta_per_capita",
    "n_hogares_total",
    "tamanio_medio_hogar",
    "hogares_renta_alta",
    "hogares_renta_media_alta",
    "hogares_jovenes_solos",
    "hogares_parejas_jovenes",
    "hogares_parejas_adultas",
    "hogares_familias_hijos",
    "hogares_monoparentales",
    # Salud financiera
    "puede_afrontar_imprevistos_pct",
    "llega_mes_con_facilidad_pct",
    "en_riesgo_pobreza_pct",
    # Gasto retail
    "gasto_ropa_calzado",
    "gasto_ropa",
    "gasto_calzado",
    "gasto_cuidado_personal",
    "gasto_ocio_cultura",
    "gasto_vacaciones",
    "gasto_restaurantes",
    "gasto_alimentacion",
    "gasto_transporte",
    "gasto_comunicaciones",
    # Empleo y pobreza
    "tasa_desempleo",
    "tasa_desempleo_jovenes",
    "empleados_por_hogar",
    "tasa_riesgo_pobreza",
    # Canal online
    "pct_compras_online",
    "online_ropa_deporte_pct",
    "online_ultimo_mes_pct",
    # Infraestructura urbana (evolución muy lenta)
    "dist_transporte_min_m",
    # Precio inmobiliario y poder de compra
    "precio_piso_alquiler",
    "indice_poder_compra",
    "poder_compra_pc",
]

# Dinámicas: entorno competitivo y de movilidad.
# Un competidor que abrió en 2026 no existía en 2024.
GEO_FEATURES_DINAMICAS = [
    "densidad_comercial_score",
    "indice_movilidad_peatonal",
    "n_competidores_500m",
    "dist_competidor_cercano_m",
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
