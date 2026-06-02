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
    "poblacion_5min",                   # PEOPLE @ 400 m
    "poblacion_10min",                  # PEOPLE @ 800 m
    "poblacion_15min",                  # PEOPLE @ 1 200 m
    # Bloque 2 — Demografía por edad (radio 800 m) — pirámide completa
    "pob_0_4",                          # POPAG0  — primera infancia
    "pob_5_9",                          # POPAG5  — infancia
    "pob_10_14",                        # POPAG10 — preadolescentes
    "pob_15_19",                        # POPAG15 — adolescentes        ← target Miniso
    "pob_20_24",                        # POPAG20 — jóvenes adultos      ← target Miniso
    "pob_25_29",                        # POPAG25 — peak gasto lifestyle ← target Miniso ★
    "pob_30_34",                        # POPAG30 — familias jóvenes     ← target Miniso ★
    "pob_35_39",                        # POPAG35 — adultos establecidos ← target Miniso
    "pob_40_44",                        # POPAG40
    "pob_45_49",                        # POPAG45
    "pob_50_54",                        # POPAG50
    "pob_55_59",                        # POPAG55
    "pob_60_64",                        # POPAG60
    "pob_65_69",                        # POPAG65
    "pob_70_74",                        # POPAG70
    "pob_75_79",                        # POPAG75
    "pob_80_84",                        # POPAG80
    "pob_85_plus",                      # POPAG85 — 85 y más
    # Bloque 3 — Renta y composición de hogar (radio 800 m)
    "renta_hogar_anual",                # NINCHA  — renta media anual del hogar (€)
    "renta_hogar_mensual",              # NINCHM  — renta media mensual del hogar (€)
    "renta_per_capita",                 # NINCCA  — renta media anual per cápita (€)
    "n_hogares_total",                  # HHOLDS  — total hogares (tamaño mercado)
    "tamanio_medio_hogar",              # PEOFAM  — personas por hogar
    "hogares_renta_alta",               # THINC5M — hogares >€2 589/mes
    "hogares_renta_media_alta",         # THINC4M — hogares €2 122–€2 589/mes (sweet spot Miniso)
    "hogares_jovenes_solos",            # TOTYOSI — solteros <35 años
    "hogares_parejas_jovenes",          # TOTYOCO — parejas <35 años
    "hogares_parejas_adultas",          # TOTADCO — parejas 35-64 años
    "hogares_familias_hijos",           # TOTFUSMA — familias con hijos <16 años
    "hogares_monoparentales",           # TOTSIFA — familias monoparentales
    # Bloque 4 — Salud financiera del hogar (radio 800 m)
    "puede_afrontar_imprevistos_pct",   # DOCAYE  — % hogares que pueden cubrir imprevistos
    "llega_mes_con_facilidad_pct",      # HOMAEASE — % hogares que llegan a fin de mes con facilidad
    "en_riesgo_pobreza_pct",            # HORIPOYE — % hogares en riesgo de pobreza
    # Bloque 5 — Gasto de consumidor en categorías retail (€/hogar/año, radio 800 m)
    "gasto_ropa_calzado",               # SPCLOFO — ropa + calzado (señal directa Miniso)
    "gasto_ropa",                       # SPCLOTH — solo ropa
    "gasto_calzado",                    # SPFOOTW — solo calzado
    "gasto_cuidado_personal",           # SPPCARE — belleza y aseo personal
    "gasto_ocio_cultura",               # SPLEISU — ocio, entretenimiento, cultura
    "gasto_vacaciones",                 # SPLHOLI — vacaciones all-inclusive (renta disponible)
    "gasto_restaurantes",               # SPHOTRE — hoteles, cafés, restaurantes
    "gasto_alimentacion",               # SPFOODR — alimentación y bebidas no alcohólicas
    "gasto_transporte",                 # SPTRANS — transporte (proxy movilidad)
    "gasto_comunicaciones",             # SPCOMM  — comunicaciones (proxy digital)
    # Bloque 6 — Mercado laboral (radio 800 m)
    "tasa_desempleo",                   # UNERATE   — desempleo total
    "tasa_desempleo_jovenes",           # UNERATE24 — desempleo <24 años
    "empleados_por_hogar",              # TOTOCCME  — empleados por hogar
    "tasa_riesgo_pobreza",              # RISPORA   — tasa riesgo pobreza
    # Bloque 7 — Canal online (radio 800 m)
    "pct_compras_online",               # PUTHINT    — % población que compra online
    "online_ropa_deporte_pct",          # PROPURSPO  — % online en ropa/deporte
    "online_ultimo_mes_pct",            # WHELAIN    — compradores online activos (último mes)
    # Bloque 9 — Entorno competitivo y accesibilidad (fase 2: Places + Routing)
    "densidad_comercial_score",
    "indice_movilidad_peatonal",
    "dist_transporte_min_m",
    "n_competidores_500m",
    "dist_competidor_cercano_m",
]

# ── Esri variable mapping ─────────────────────────────────────────────────────
# {feature_col: (var_id, radius_index)}
# radius_index → 0=400m(≈5min), 1=800m(≈10min), 2=1200m(≈15min)
# None → feature no proviene de GeoEnrichment (fase 2, Places/Routing)
ESRI_VAR_MAP: dict = {
    # Bloque 1 — Isócronas
    "poblacion_5min":                  ("PEOPLE",    0),
    "poblacion_10min":                 ("PEOPLE",    1),
    "poblacion_15min":                 ("PEOPLE",    2),
    # Bloque 2 — Edad (800 m) — pirámide completa
    "pob_0_4":                         ("POPAG0",    1),
    "pob_5_9":                         ("POPAG5",    1),
    "pob_10_14":                       ("POPAG10",   1),
    "pob_15_19":                       ("POPAG15",   1),
    "pob_20_24":                       ("POPAG20",   1),
    "pob_25_29":                       ("POPAG25",   1),
    "pob_30_34":                       ("POPAG30",   1),
    "pob_35_39":                       ("POPAG35",   1),
    "pob_40_44":                       ("POPAG40",   1),
    "pob_45_49":                       ("POPAG45",   1),
    "pob_50_54":                       ("POPAG50",   1),
    "pob_55_59":                       ("POPAG55",   1),
    "pob_60_64":                       ("POPAG60",   1),
    "pob_65_69":                       ("POPAG65",   1),
    "pob_70_74":                       ("POPAG70",   1),
    "pob_75_79":                       ("POPAG75",   1),
    "pob_80_84":                       ("POPAG80",   1),
    "pob_85_plus":                     ("POPAG85",   1),
    # Bloque 3 — Renta y hogar
    "renta_hogar_anual":               ("NINCHA",    1),
    "renta_hogar_mensual":             ("NINCHM",    1),
    "renta_per_capita":                ("NINCCA",    1),
    "n_hogares_total":                 ("HHOLDS",    1),
    "tamanio_medio_hogar":             ("PEOFAM",    1),
    "hogares_renta_alta":              ("THINC5M",   1),
    "hogares_renta_media_alta":        ("THINC4M",   1),
    "hogares_jovenes_solos":           ("TOTYOSI",   1),
    "hogares_parejas_jovenes":         ("TOTYOCO",   1),
    "hogares_parejas_adultas":         ("TOTADCO",   1),
    "hogares_familias_hijos":          ("TOTFUSMA",  1),
    "hogares_monoparentales":          ("TOTSIFA",   1),
    # Bloque 4 — Salud financiera
    "puede_afrontar_imprevistos_pct":  ("DOCAYE",    1),
    "llega_mes_con_facilidad_pct":     ("HOMAEASE",  1),
    "en_riesgo_pobreza_pct":           ("HORIPOYE",  1),
    # Bloque 5 — Gasto retail
    "gasto_ropa_calzado":              ("SPCLOFO",   1),
    "gasto_ropa":                      ("SPCLOTH",   1),
    "gasto_calzado":                   ("SPFOOTW",   1),
    "gasto_cuidado_personal":          ("SPPCARE",   1),
    "gasto_ocio_cultura":              ("SPLEISU",   1),
    "gasto_vacaciones":                ("SPLHOLI",   1),
    "gasto_restaurantes":              ("SPHOTRE",   1),
    "gasto_alimentacion":              ("SPFOODR",   1),
    "gasto_transporte":                ("SPTRANS",   1),
    "gasto_comunicaciones":            ("SPCOMM",    1),
    # Bloque 6 — Empleo y pobreza
    "tasa_desempleo":                  ("UNERATE",   1),
    "tasa_desempleo_jovenes":          ("UNERATE24", 1),
    "empleados_por_hogar":             ("TOTOCCME",  1),
    "tasa_riesgo_pobreza":             ("RISPORA",   1),
    # Bloque 7 — Canal online
    "pct_compras_online":              ("PUTHINT",   1),
    "online_ropa_deporte_pct":         ("PROPURSPO", 1),
    "online_ultimo_mes_pct":           ("WHELAIN",   1),
    # Fase 2 — no vienen de GeoEnrichment
    "densidad_comercial_score":        None,
    "indice_movilidad_peatonal":       None,
    "dist_transporte_min_m":           None,
    "n_competidores_500m":             None,
    "dist_competidor_cercano_m":       None,
}

# Colección AIS a la que pertenece cada variable Esri
ESRI_COLLECTION_MAP: dict = {
    # PopulationTotalsAIS
    "PEOPLE":    "PopulationTotalsAIS",
    "RISPORA":   "PopulationTotalsAIS",
    # 5YearIncrementsAIS
    "POPAG0":    "5YearIncrementsAIS",
    "POPAG5":    "5YearIncrementsAIS",
    "POPAG10":   "5YearIncrementsAIS",
    "POPAG15":   "5YearIncrementsAIS",
    "POPAG20":   "5YearIncrementsAIS",
    "POPAG25":   "5YearIncrementsAIS",
    "POPAG30":   "5YearIncrementsAIS",
    "POPAG35":   "5YearIncrementsAIS",
    "POPAG40":   "5YearIncrementsAIS",
    "POPAG45":   "5YearIncrementsAIS",
    "POPAG50":   "5YearIncrementsAIS",
    "POPAG55":   "5YearIncrementsAIS",
    "POPAG60":   "5YearIncrementsAIS",
    "POPAG65":   "5YearIncrementsAIS",
    "POPAG70":   "5YearIncrementsAIS",
    "POPAG75":   "5YearIncrementsAIS",
    "POPAG80":   "5YearIncrementsAIS",
    "POPAG85":   "5YearIncrementsAIS",
    # IncomeTotalsAIS
    "NINCHA":    "IncomeTotalsAIS",
    "NINCHM":    "IncomeTotalsAIS",
    "NINCCA":    "IncomeTotalsAIS",
    "TOTYOSI":   "IncomeTotalsAIS",
    "TOTYOCO":   "IncomeTotalsAIS",
    "TOTADCO":   "IncomeTotalsAIS",
    "TOTFUSMA":  "IncomeTotalsAIS",
    "TOTSIFA":   "IncomeTotalsAIS",
    # HouseholdTotalsAIS
    "HHOLDS":    "HouseholdTotalsAIS",
    "PEOFAM":    "HouseholdTotalsAIS",
    # HouseholdsByIncomeAIS
    "THINC5M":   "HouseholdsByIncomeAIS",
    "THINC4M":   "HouseholdsByIncomeAIS",
    "DOCAYE":    "HouseholdsByIncomeAIS",
    "HOMAEASE":  "HouseholdsByIncomeAIS",
    "HORIPOYE":  "HouseholdsByIncomeAIS",
    # ClothingAIS
    "SPCLOFO":   "ClothingAIS",
    "SPCLOTH":   "ClothingAIS",
    "SPFOOTW":   "ClothingAIS",
    # SpendingTotalsAIS
    "SPPCARE":   "SpendingTotalsAIS",
    # EntertainmentAIS
    "SPLEISU":   "EntertainmentAIS",
    "SPLHOLI":   "EntertainmentAIS",
    # MiscellaneousAIS
    "SPHOTRE":   "MiscellaneousAIS",
    "SPCOMM":    "MiscellaneousAIS",
    # FoodAndDrinksAIS
    "SPFOODR":   "FoodAndDrinksAIS",
    # TransportationAIS
    "SPTRANS":   "TransportationAIS",
    # EmploymentTotalsAIS
    "UNERATE":   "EmploymentTotalsAIS",
    "UNERATE24": "EmploymentTotalsAIS",
    "TOTOCCME":  "EmploymentTotalsAIS",
    # PropertyValueAIS
    "AVREAPRI":  "PropertyValueAIS",
    "AVPRIRENP": "PropertyValueAIS",
    # OnlineShoppingAIS
    "PUTHINT":   "OnlineShoppingAIS",
    "PROPURSPO": "OnlineShoppingAIS",
    "WHELAIN":   "OnlineShoppingAIS",
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
    Consulta store_geo_snapshots y devuelve {feature_key: value} del snapshot aplicable.
    Retorna dict vacío si no hay datos para esta ubicación.
    """
    from src.db.store import get_conn
    conn = get_conn()

    if fecha is None:
        row = conn.execute("""
            SELECT DISTINCT valid_from FROM store_geo_snapshots
            WHERE location_uuid = ? AND valid_to IS NULL
            ORDER BY valid_from DESC LIMIT 1
        """, [location_uuid]).fetchone()
        if not row:
            row = conn.execute("""
                SELECT DISTINCT valid_from FROM store_geo_snapshots
                WHERE location_uuid = ? ORDER BY valid_from DESC LIMIT 1
            """, [location_uuid]).fetchone()
    else:
        fecha_str = str(fecha)[:10]
        row = conn.execute("""
            SELECT DISTINCT valid_from FROM store_geo_snapshots
            WHERE location_uuid = ?
              AND valid_from <= ?
              AND (valid_to IS NULL OR valid_to >= ?)
            ORDER BY valid_from DESC LIMIT 1
        """, [location_uuid, fecha_str, fecha_str]).fetchone()

    if not row:
        return {}

    valid_from = row[0]
    rows = conn.execute("""
        SELECT feature_key, value FROM store_geo_snapshots
        WHERE location_uuid = ? AND valid_from = ?
    """, [location_uuid, valid_from]).fetchall()
    return {k: v for k, v in rows}


def get_geo_vals(location_uuid: str, fecha=None) -> dict:
    """
    Devuelve el snapshot geoespacial de una ubicación en un momento dado.

    - fecha=None → snapshot activo más reciente (para predicción de fechas futuras).
    - fecha=<date> → snapshot cuyo intervalo [valid_from, valid_to] contiene esa fecha
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


def enriquecer_con_geo(df: pd.DataFrame, col_location_id: str = "location_id", col_fecha: str = "fecha") -> pd.DataFrame:
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

    geo_df = df[[col_location_id] + ([col_fecha] if usa_fecha else [])].apply(_lookup, axis=1, result_type="expand")

    cols_con_dato = [c for c in GEO_FEATURE_COLS if c in geo_df.columns and geo_df[c].notna().any()]
    if not cols_con_dato:
        return df

    for col in cols_con_dato:
        df = df.copy()
        df[col] = geo_df[col].values

    return df


def get_catchment_rings(location_uuid: str):
    """Retorna geometría de isócronas peatonales almacenada en dim_ubicaciones."""
    import json
    from src.db.store import get_conn
    row = get_conn().execute(
        "SELECT catchment_rings_json FROM dim_ubicaciones WHERE location_uuid = ?",
        [location_uuid],
    ).fetchone()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except Exception:
            return None
    return None


def get_geo_snapshot_date(location_uuid: str) -> str | None:
    """Returns the valid_from date of the active geo snapshot, or None if no data."""
    from src.db.store import get_conn
    row = get_conn().execute("""
        SELECT valid_from FROM store_geo_snapshots
        WHERE location_uuid = ? AND valid_to IS NULL
        ORDER BY valid_from DESC LIMIT 1
    """, [location_uuid]).fetchone()
    if row:
        return str(row[0])
    row = get_conn().execute("""
        SELECT valid_from FROM store_geo_snapshots
        WHERE location_uuid = ? ORDER BY valid_from DESC LIMIT 1
    """, [location_uuid]).fetchone()
    return str(row[0]) if row else None
