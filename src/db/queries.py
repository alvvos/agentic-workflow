"""
Read-side query layer.

Primary entry point for the ML pipeline:

    from src.db.queries import get_df_enriquecido
    df = get_df_enriquecido(ubicacion_id, session_id)
    # → same shape as enriquecer_datos_ubicacion() output:
    #   fecha, location_id, zona_id, total_visits,
    #   temp_max, temp_min, llueve, es_festivo

The function:
  1. Reads visitas from PostgreSQL (falls back to session CSV if empty).
  2. Fetches weather from valores_señales (calls Open-Meteo and caches on miss).
  3. Computes es_festivo using the org's pais_codigo (ES or MX).
  4. Returns a DataFrame ready for ejecutar_auditoria_predictiva().

Geo features are joined inside ml_predictivo.py via get_geo_snapshot_df().
"""

import json
from datetime import date
from pathlib import Path
from typing import Optional

import holidays as hol_lib
import pandas as pd
import requests

from src.db.store import get_conn

_DATA = Path(__file__).parent.parent / "data"


# ── Org / location helpers ────────────────────────────────────────────────────


def get_org_info(ubicacion_id: str) -> dict:
    """Returns {org_id, pais_codigo, config_calendario} for a location."""
    conn = get_conn()
    row = conn.execute(
        """
        SELECT o.org_id, o.pais_codigo, o.config_calendario
        FROM ubicaciones u
        JOIN organizaciones o ON o.org_id = u.org_id
        WHERE u.ubicacion_id = ?
    """,
        [ubicacion_id],
    ).fetchone()
    if row is None:
        return {"org_id": None, "pais_codigo": "ES", "config_calendario": {}}
    cfg = row[2]
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}
    return {"org_id": row[0], "pais_codigo": row[1], "config_calendario": cfg or {}}


def get_location_coords(ubicacion_id: str) -> Optional[tuple]:
    """Returns (lat, lon) for a location, or None."""
    conn = get_conn()
    row = conn.execute(
        "SELECT lat, lon FROM ubicaciones WHERE ubicacion_id = ?",
        [ubicacion_id],
    ).fetchone()
    if row and row[0] is not None and row[1] is not None:
        return (float(row[0]), float(row[1]))
    return None


# ── Holiday helper ────────────────────────────────────────────────────────────

_HOL_CACHE: dict = {}


def _es_festivo(fecha: date, pais_codigo: str, region_code: Optional[str] = None) -> int:
    year = fecha.year
    key = (pais_codigo, region_code, year)
    if key not in _HOL_CACHE:
        try:
            if pais_codigo == "MX":
                _HOL_CACHE[key] = hol_lib.Mexico(years=year)
            elif pais_codigo == "ES":
                if region_code:
                    _HOL_CACHE[key] = hol_lib.Spain(subdiv=region_code, years=year)
                else:
                    _HOL_CACHE[key] = hol_lib.Spain(years=year)
            else:
                _HOL_CACHE[key] = {}
        except Exception:
            _HOL_CACHE[key] = {}
    return 1 if fecha in _HOL_CACHE[key] else 0


# ── Weather ───────────────────────────────────────────────────────────────────


def _fetch_weather(lat: float, lon: float, fecha_min: str, fecha_max: str) -> pd.DataFrame:
    """Open-Meteo archive API (datos históricos confirmados)."""
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={fecha_min}&end_date={fecha_max}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
        f"&timezone=auto"
    )
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        d = r.json()["daily"]
        df = pd.DataFrame(
            {
                "fecha": pd.to_datetime(d["time"]).date,
                "temp_max": d["temperature_2m_max"],
                "temp_min": d["temperature_2m_min"],
                "llueve": [1 if (p or 0) > 0 else 0 for p in d["precipitation_sum"]],
            }
        )
        return df
    except Exception:
        return pd.DataFrame()


def _fetch_weather_forecast(
    lat: float, lon: float, past_days: int = 7, forecast_days: int = 16
) -> pd.DataFrame:
    """Open-Meteo forecast API — cubre últimos past_days y próximos forecast_days (máx 16)."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
        f"&timezone=auto"
        f"&past_days={past_days}&forecast_days={forecast_days}"
    )
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        d = r.json()["daily"]
        df = pd.DataFrame(
            {
                "fecha": pd.to_datetime(d["time"]).date,
                "temp_max": d["temperature_2m_max"],
                "temp_min": d["temperature_2m_min"],
                "llueve": [1 if (p or 0) > 0 else 0 for p in d["precipitation_sum"]],
            }
        )
        return df
    except Exception:
        return pd.DataFrame()


def _cache_weather(ubicacion_id: str, df_weather: pd.DataFrame, overwrite: bool = False) -> None:
    """
    Escribe filas de clima en valores_señales.
    overwrite=True → DO UPDATE (usar para datos de pronóstico que cambian).
    overwrite=False → DO NOTHING (usar para histórico confirmado).
    """
    if df_weather.empty:
        return
    conn = get_conn()
    rows = []
    for _, row in df_weather.iterrows():
        fecha = str(row["fecha"])
        rows += [
            (
                fecha,
                ubicacion_id,
                "temp_max",
                float(row["temp_max"]) if pd.notna(row["temp_max"]) else None,
            ),
            (
                fecha,
                ubicacion_id,
                "temp_min",
                float(row["temp_min"]) if pd.notna(row["temp_min"]) else None,
            ),
            (fecha, ubicacion_id, "llueve", float(row["llueve"])),
        ]
    if overwrite:
        sql = (
            "INSERT INTO valores_señales (fecha, ubicacion_id, señal_id, valor) "
            "VALUES (?,?,?,?) ON CONFLICT (fecha, ubicacion_id, señal_id) "
            "DO UPDATE SET valor = excluded.valor"
        )
    else:
        sql = (
            "INSERT INTO valores_señales (fecha, ubicacion_id, señal_id, valor) "
            "VALUES (?,?,?,?) ON CONFLICT DO NOTHING"
        )
    conn.executemany(sql, rows)


def _get_weather(ubicacion_id: str, fechas: pd.Series) -> pd.DataFrame:
    """
    Returns weather DataFrame for the given dates.
    Reads from valores_señales; fetches from Open-Meteo on miss and caches.
    """
    conn = get_conn()
    cached = conn.execute(
        """
        SELECT fecha,
            MAX(CASE WHEN señal_id='temp_max' THEN valor END) AS temp_max,
            MAX(CASE WHEN señal_id='temp_min' THEN valor END) AS temp_min,
            MAX(CASE WHEN señal_id='llueve'   THEN valor END) AS llueve
        FROM valores_señales
        WHERE ubicacion_id = ?
          AND señal_id IN ('temp_max','temp_min','llueve')
        GROUP BY fecha
    """,
        [ubicacion_id],
    ).df()

    need = set(pd.to_datetime(fechas).dt.date)
    have = set(pd.to_datetime(cached["fecha"]).dt.date) if not cached.empty else set()
    missing = sorted(need - have)

    if missing:
        coords = get_location_coords(ubicacion_id)
        if coords:
            lat, lon = coords
            new_weather = _fetch_weather(lat, lon, str(missing[0]), str(missing[-1]))
            if not new_weather.empty:
                _cache_weather(ubicacion_id, new_weather)
                cached = pd.concat(
                    [cached, new_weather.rename(columns={"fecha": "fecha"})], ignore_index=True
                )

    return cached


# ── CSV fallback ──────────────────────────────────────────────────────────────


def _get_from_csv(ubicacion_id: str, session_id: str) -> pd.DataFrame:
    csv_path = _DATA / f"dataset_{session_id}.csv"
    if not csv_path.exists():
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df[df["location_id"] == ubicacion_id].copy()


# ── Main entry point ──────────────────────────────────────────────────────────


def get_df_enriquecido(ubicacion_id: str, session_id: Optional[str] = None) -> pd.DataFrame:
    """
    Returns an enriched DataFrame for ML training, shaped identically to
    enriquecer_datos_ubicacion() output:

        fecha (datetime), location_id, zona_id,
        total_visits, temp_max, temp_min, llueve, es_festivo

    Priority: PostgreSQL visitas → session CSV fallback.
    Weather: valores_señales cache → Open-Meteo API.
    Holidays: computed from org's pais_codigo.
    """
    conn = get_conn()
    org = get_org_info(ubicacion_id)
    pais = org["pais_codigo"]

    # 1. Raw visit data
    n_db = conn.execute(
        "SELECT COUNT(*) FROM visitas WHERE ubicacion_id = ?",
        [ubicacion_id],
    ).fetchone()[0]

    if n_db > 0:
        df = conn.execute(
            """
            SELECT fecha, ubicacion_id AS location_id, zona_id,
                   total_visits, unique_visitors, new_visitors
            FROM visitas
            WHERE ubicacion_id = ?
            ORDER BY fecha
        """,
            [ubicacion_id],
        ).df()
        df["fecha"] = pd.to_datetime(df["fecha"])
    elif session_id:
        df = _get_from_csv(ubicacion_id, session_id)
    else:
        return pd.DataFrame()

    if df.empty:
        return df

    # 2. Weather enrichment
    weather = _get_weather(ubicacion_id, df["fecha"])
    if not weather.empty:
        weather["fecha"] = pd.to_datetime(weather["fecha"])
        df = df.merge(weather, on="fecha", how="left")
    else:
        df["temp_max"] = 22.0
        df["temp_min"] = 15.0
        df["llueve"] = 0

    df["temp_max"] = df.get("temp_max", pd.Series(22.0, index=df.index)).fillna(22.0)
    df["temp_min"] = df.get("temp_min", pd.Series(15.0, index=df.index)).fillna(15.0)
    df["llueve"] = df.get("llueve", pd.Series(0, index=df.index)).fillna(0).astype(int)

    # 3. Holidays (country-aware)
    region_code = conn.execute(
        "SELECT region_code FROM ubicaciones WHERE ubicacion_id = ?",
        [ubicacion_id],
    ).fetchone()
    region = region_code[0] if region_code else None

    df["es_festivo"] = df["fecha"].apply(
        lambda d: _es_festivo(d.date() if hasattr(d, "date") else d, pais, region)
    )

    df["region_code"] = region or ""
    return df


def get_df_visitas(ubicacion_ids) -> pd.DataFrame:
    """
    Datos crudos de visitas para múltiples ubicaciones desde visitas.
    Alias dwell_time_min → dwell_time para compatibilidad con callbacks.
    Acepta un UUID como string o lista de UUIDs.
    """
    if not ubicacion_ids:
        return pd.DataFrame()
    conn = get_conn()
    placeholders = ",".join(["?" for _ in ubicacion_ids])
    df = conn.execute(
        f"""
        SELECT fecha,
               ubicacion_id   AS location_id,
               zona_id,
               total_visits,
               unique_visitors,
               new_visitors,
               uv_7d, uv_28d, uv_month, uv_year,
               freq_7d, freq_28d, freq_month, freq_year,
               dwell_time_min  AS dwell_time,
               dwell_hist,
               hourly_visits
        FROM visitas
        WHERE ubicacion_id IN ({placeholders})
        ORDER BY fecha
    """,
        ubicacion_ids,
    ).df()
    if not df.empty:
        df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def get_ultima_fecha_por_location() -> dict:
    """Devuelve {ubicacion_id: fecha_max} con la última fecha en visitas."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT ubicacion_id, MAX(fecha) AS ultima_fecha
        FROM visitas
        GROUP BY ubicacion_id
    """
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ── Geo feature temporal join ─────────────────────────────────────────────────


def get_geo_snapshot_df(ubicacion_id: str, fechas: pd.Series) -> pd.DataFrame:
    """
    Returns a DataFrame with one row per date in fechas, columns = geo feature keys.
    Each row gets the Esri snapshot that was valid at that date.
    Returns an empty DataFrame (no rows, no columns) if no geo data exists.

    Used by ml_predictivo.py to add geo context to the training set.
    """
    conn = get_conn()

    # Load all snapshots for this location
    snaps = conn.execute(
        """
        SELECT señal_id, valor, vigente_desde, vigente_hasta
        FROM snapshots_geo
        WHERE ubicacion_id = ?
        ORDER BY señal_id, vigente_desde
    """,
        [ubicacion_id],
    ).df()

    if snaps.empty:
        return pd.DataFrame()

    snaps["vigente_desde"] = pd.to_datetime(snaps["vigente_desde"])
    snaps["vigente_hasta"] = pd.to_datetime(snaps["vigente_hasta"]).fillna(
        pd.Timestamp("2099-12-31")
    )

    dates = pd.to_datetime(fechas).rename("fecha")
    geo_cols = snaps["señal_id"].unique()
    result = pd.DataFrame({"fecha": dates})

    for col in geo_cols:
        col_snaps = snaps[snaps["señal_id"] == col].sort_values("vigente_desde")
        # For each date, find the snapshot valid at that date
        result[col] = result["fecha"].apply(lambda d: _snap_value(col_snaps, d))

    result = result.drop(columns=["fecha"])
    return result


# ── Dimension helpers (reemplazan lecturas directas de todas_las_ubicaciones.json) ──


def get_all_orgs() -> list[dict]:
    """[{org_id, nombre, pais_codigo}, ...]"""
    return [
        {"org_id": r[0], "nombre": r[1], "pais_codigo": r[2]}
        for r in get_conn()
        .execute("SELECT org_id, nombre, pais_codigo FROM organizaciones ORDER BY nombre")
        .fetchall()
    ]


def get_locs_for_org(org_id: str) -> list[dict]:
    """[{ubicacion_id, nombre}, ...] para una org."""
    return [
        {"ubicacion_id": r[0], "nombre": r[1]}
        for r in get_conn()
        .execute(
            "SELECT ubicacion_id, nombre FROM ubicaciones WHERE org_id = ? AND activa = TRUE ORDER BY nombre",
            [org_id],
        )
        .fetchall()
    ]


def get_zones_for_loc(ubicacion_id: str) -> list[dict]:
    """[{zona_id, nombre, zone_type, hidden, parent_zona_id}, ...] para una ubicación."""
    return [
        {
            "zona_id": r[0],
            "nombre": r[1],
            "zone_type": r[2] or "",
            "hidden": r[3],
            "parent_zona_id": r[4],
        }
        for r in get_conn()
        .execute(
            "SELECT zona_id, nombre, zone_type, hidden, parent_zona_id"
            " FROM zonas WHERE ubicacion_id = ? ORDER BY nombre",
            [ubicacion_id],
        )
        .fetchall()
    ]


def get_location_by_uuid(ubicacion_id: str) -> Optional[dict]:
    """Devuelve dict completo de ubicación + org_nombre, o None."""
    row = (
        get_conn()
        .execute(
            """
        SELECT u.ubicacion_id, u.nombre, u.lat, u.lon, u.ciudad, u.provincia,
               u.pais_codigo, u.region_code, u.codigo_postal, u.direccion,
               o.nombre AS org_nombre, o.org_id
        FROM ubicaciones u
        JOIN organizaciones o ON o.org_id = u.org_id
        WHERE u.ubicacion_id = ?
    """,
            [ubicacion_id],
        )
        .fetchone()
    )
    if row is None:
        return None
    return {
        "uuid": row[0],
        "name": row[1],
        "lat": row[2],
        "lon": row[3],
        "city": row[4],
        "province": row[5],
        "pais_codigo": row[6],
        "region_code": row[7],
        "codigo_postal": row[8],
        "direccion": row[9],
        "org": row[10],
        "org_id": row[11],
    }


def get_location_by_name(nombre: str) -> Optional[dict]:
    """Búsqueda por nombre (insensible a mayúsculas). Devuelve primera coincidencia."""
    row = (
        get_conn()
        .execute(
            "SELECT ubicacion_id, lat, lon, region_code FROM ubicaciones WHERE lower(nombre) = lower(?) LIMIT 1",
            [nombre],
        )
        .fetchone()
    )
    if row is None:
        return None
    return {"ubicacion_id": row[0], "lat": row[1], "lon": row[2], "region_code": row[3]}


def get_locations_with_coords() -> list[str]:
    """UUIDs de ubicaciones que tienen lat/lon y postal_code (para sincronizador)."""
    return [
        r[0]
        for r in get_conn()
        .execute(
            "SELECT ubicacion_id FROM ubicaciones WHERE lat IS NOT NULL AND lon IS NOT NULL AND codigo_postal IS NOT NULL AND activa = TRUE"
        )
        .fetchall()
    ]


def get_all_zones_flat() -> list[dict]:
    """[{zona_id, ubicacion_id, nombre, zone_type}, ...] para todas las zonas visibles."""
    return [
        {
            "zona_id": r[0],
            "ubicacion_id": r[1],
            "nombre": r[2],
            "zone_type": r[3] or "",
        }
        for r in get_conn()
        .execute(
            "SELECT zona_id, ubicacion_id, nombre, zone_type FROM zonas WHERE hidden = FALSE ORDER BY nombre"
        )
        .fetchall()
    ]


def get_active_ext_features(
    ubicacion_id: str,
    fecha_min: pd.Timestamp,
    fecha_max: pd.Timestamp,
) -> pd.DataFrame:
    """
    Devuelve un DataFrame (índice DatetimeIndex diario) con una columna por cada
    señal activa en activacion_señales para esta ubicación.

    Forward-fill diario aplicado: señales mensuales (ICM) se propagan al resto del mes.
    """
    from src.db.store import get_conn

    conn = get_conn()

    rows = conn.execute(
        """
        SELECT señal_id
        FROM   activacion_señales
        WHERE  ubicacion_id = ?
          AND  status = 'active'
        ORDER  BY señal_id
    """,
        [ubicacion_id],
    ).fetchall()

    señal_ids = [r[0] for r in rows]
    if not señal_ids:
        return pd.DataFrame(index=pd.date_range(fecha_min, fecha_max, freq="D"))

    full_idx = pd.date_range(fecha_min, fecha_max, freq="D")
    result = pd.DataFrame(index=full_idx)

    for fk in señal_ids:
        df = conn.execute(
            """
            SELECT fecha, valor::double precision AS valor
            FROM   valores_señales
            WHERE  ubicacion_id = ?
              AND  señal_id   = ?
              AND  fecha BETWEEN ? AND ?
            ORDER  BY fecha
        """,
            [ubicacion_id, fk, fecha_min.date(), fecha_max.date()],
        ).df()

        if df.empty:
            continue
        df["fecha"] = pd.to_datetime(df["fecha"])
        serie = df.set_index("fecha")["valor"].reindex(full_idx).fillna(0.0)
        result[fk] = serie.values

    return result


def get_pois_for_location(ubicacion_id: str) -> list[dict]:
    """Returns all active POIs for a location, ordered by category and relevance."""
    rows = (
        get_conn()
        .execute(
            """SELECT nombre, lat, lon, categoria, valor_relativo, detalle,
                  radio_m, isocrona_minutos, isocrona_geojson::text
           FROM puntos_interes
           WHERE ubicacion_id = ? AND activo = TRUE
           ORDER BY categoria, valor_relativo DESC""",
            [ubicacion_id],
        )
        .fetchall()
    )
    keys = [
        "nombre",
        "lat",
        "lon",
        "categoria",
        "valor_relativo",
        "detalle",
        "radio_m",
        "isocrona_minutos",
        "isocrona_geojson",
    ]
    return [dict(zip(keys, r)) for r in rows]


def upsert_poi(
    ubicacion_id: str,
    org_id: str,
    nombre: str,
    lat: float,
    lon: float,
    categoria: str,
    valor_relativo: float = 0.5,
    detalle: str | None = None,
    radio_m: int | None = None,
    isocrona_minutos: int | None = None,
    isocrona_geojson: str | None = None,
    fuente: str = "manual",
) -> None:
    """Insert or update a POI for a location."""
    get_conn().execute(
        """INSERT INTO puntos_interes
           (ubicacion_id, org_id, nombre, lat, lon, categoria,
            valor_relativo, detalle, radio_m, isocrona_minutos,
            isocrona_geojson, fuente)
           VALUES (?,?,?,?,?,?,?,?,?,?,?::jsonb,?)
           ON CONFLICT (ubicacion_id, nombre, categoria)
           DO UPDATE SET lat = excluded.lat, lon = excluded.lon,
               valor_relativo = excluded.valor_relativo,
               detalle = excluded.detalle, radio_m = excluded.radio_m,
               isocrona_minutos = excluded.isocrona_minutos,
               isocrona_geojson = excluded.isocrona_geojson,
               fuente = excluded.fuente, activo = TRUE""",
        [
            ubicacion_id,
            org_id,
            nombre,
            lat,
            lon,
            categoria,
            valor_relativo,
            detalle,
            radio_m,
            isocrona_minutos,
            isocrona_geojson,
            fuente,
        ],
    )


def _snap_value(col_snaps: pd.DataFrame, fecha: pd.Timestamp) -> Optional[float]:
    mask = (col_snaps["vigente_desde"] <= fecha) & (col_snaps["vigente_hasta"] >= fecha)
    rows = col_snaps[mask]
    if rows.empty:
        return None
    return rows.iloc[-1]["valor"]  # latest valid snapshot if overlapping
