"""
Read-side query layer.

Primary entry point for the ML pipeline:

    from src.db.queries import get_df_enriquecido
    df = get_df_enriquecido(location_uuid, session_id)
    # → same shape as enriquecer_datos_ubicacion() output:
    #   fecha, location_id, zone_uuid, total_visits,
    #   temp_max, temp_min, llueve, es_festivo

The function:
  1. Reads fact_visitas from DuckDB (falls back to session CSV if empty).
  2. Fetches weather from store_features_ext (calls Open-Meteo and caches on miss).
  3. Computes es_festivo using the org's pais_codigo (ES or MX).
  4. Returns a DataFrame ready for ejecutar_auditoria_predictiva().

Geo features are joined inside ml_predictivo.py via get_geo_snapshot_df().
"""
import os
import json
import requests
import pandas as pd
import numpy as np
import holidays as hol_lib
from datetime import date
from pathlib import Path
from typing import Optional

from src.db.store import get_conn

_DATA = Path(__file__).parent.parent / 'data'


# ── Org / location helpers ────────────────────────────────────────────────────

def get_org_info(location_uuid: str) -> dict:
    """Returns {org_uuid, pais_codigo, config_calendario} for a location."""
    conn = get_conn()
    row = conn.execute("""
        SELECT o.org_uuid, o.pais_codigo, o.config_calendario
        FROM dim_ubicaciones u
        JOIN dim_organizaciones o ON o.org_uuid = u.org_uuid
        WHERE u.location_uuid = ?
    """, [location_uuid]).fetchone()
    if row is None:
        return {'org_uuid': None, 'pais_codigo': 'ES', 'config_calendario': {}}
    cfg = row[2]
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}
    return {'org_uuid': row[0], 'pais_codigo': row[1], 'config_calendario': cfg or {}}


def get_location_coords(location_uuid: str) -> Optional[tuple]:
    """Returns (lat, lon) for a location, or None."""
    conn = get_conn()
    row = conn.execute(
        "SELECT lat, lon FROM dim_ubicaciones WHERE location_uuid = ?",
        [location_uuid],
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
            if pais_codigo == 'MX':
                _HOL_CACHE[key] = hol_lib.Mexico(years=year)
            elif pais_codigo == 'ES':
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
        d = r.json()['daily']
        df = pd.DataFrame({
            'fecha': pd.to_datetime(d['time']).date,
            'temp_max': d['temperature_2m_max'],
            'temp_min': d['temperature_2m_min'],
            'llueve': [1 if (p or 0) > 0 else 0 for p in d['precipitation_sum']],
        })
        return df
    except Exception:
        return pd.DataFrame()


def _fetch_weather_forecast(lat: float, lon: float, past_days: int = 7, forecast_days: int = 16) -> pd.DataFrame:
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
        d = r.json()['daily']
        df = pd.DataFrame({
            'fecha': pd.to_datetime(d['time']).date,
            'temp_max': d['temperature_2m_max'],
            'temp_min': d['temperature_2m_min'],
            'llueve': [1 if (p or 0) > 0 else 0 for p in d['precipitation_sum']],
        })
        return df
    except Exception:
        return pd.DataFrame()


def _cache_weather(location_uuid: str, df_weather: pd.DataFrame, overwrite: bool = False) -> None:
    """
    Escribe filas de clima en store_features_ext.
    overwrite=True → DO UPDATE (usar para datos de pronóstico que cambian).
    overwrite=False → DO NOTHING (usar para histórico confirmado).
    """
    if df_weather.empty:
        return
    conn = get_conn()
    rows = []
    for _, row in df_weather.iterrows():
        fecha = str(row['fecha'])
        rows += [
            (fecha, location_uuid, 'temp_max', float(row['temp_max']) if pd.notna(row['temp_max']) else None),
            (fecha, location_uuid, 'temp_min', float(row['temp_min']) if pd.notna(row['temp_min']) else None),
            (fecha, location_uuid, 'llueve',   float(row['llueve'])),
        ]
    if overwrite:
        sql = (
            "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) "
            "VALUES (?,?,?,?) ON CONFLICT (fecha, location_uuid, feature_key) "
            "DO UPDATE SET value = excluded.value"
        )
    else:
        sql = (
            "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) "
            "VALUES (?,?,?,?) ON CONFLICT DO NOTHING"
        )
    conn.executemany(sql, rows)


def _get_weather(location_uuid: str, fechas: pd.Series) -> pd.DataFrame:
    """
    Returns weather DataFrame for the given dates.
    Reads from store_features_ext; fetches from Open-Meteo on miss and caches.
    """
    conn = get_conn()
    cached = conn.execute("""
        SELECT fecha,
            MAX(CASE WHEN feature_key='temp_max' THEN value END) AS temp_max,
            MAX(CASE WHEN feature_key='temp_min' THEN value END) AS temp_min,
            MAX(CASE WHEN feature_key='llueve'   THEN value END) AS llueve
        FROM store_features_ext
        WHERE location_uuid = ?
          AND feature_key IN ('temp_max','temp_min','llueve')
        GROUP BY fecha
    """, [location_uuid]).df()

    need = set(pd.to_datetime(fechas).dt.date)
    have = set(pd.to_datetime(cached['fecha']).dt.date) if not cached.empty else set()
    missing = sorted(need - have)

    if missing:
        coords = get_location_coords(location_uuid)
        if coords:
            lat, lon = coords
            new_weather = _fetch_weather(lat, lon, str(missing[0]), str(missing[-1]))
            if not new_weather.empty:
                _cache_weather(location_uuid, new_weather)
                cached = pd.concat([cached, new_weather.rename(columns={'fecha': 'fecha'})], ignore_index=True)

    return cached


# ── CSV fallback ──────────────────────────────────────────────────────────────

def _get_from_csv(location_uuid: str, session_id: str) -> pd.DataFrame:
    csv_path = _DATA / f'dataset_{session_id}.csv'
    if not csv_path.exists():
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    df['fecha'] = pd.to_datetime(df['fecha'])
    return df[df['location_id'] == location_uuid].copy()


# ── Main entry point ──────────────────────────────────────────────────────────

def get_df_enriquecido(location_uuid: str, session_id: Optional[str] = None) -> pd.DataFrame:
    """
    Returns an enriched DataFrame for ML training, shaped identically to
    enriquecer_datos_ubicacion() output:

        fecha (datetime), location_id, zone_uuid,
        total_visits, temp_max, temp_min, llueve, es_festivo

    Priority: DuckDB fact_visitas → session CSV fallback.
    Weather: store_features_ext cache → Open-Meteo API.
    Holidays: computed from org's pais_codigo.
    """
    conn = get_conn()
    org = get_org_info(location_uuid)
    pais = org['pais_codigo']

    # 1. Raw visit data
    n_db = conn.execute(
        "SELECT COUNT(*) FROM fact_visitas WHERE location_uuid = ?",
        [location_uuid],
    ).fetchone()[0]

    if n_db > 0:
        df = conn.execute("""
            SELECT fecha, location_uuid AS location_id, zone_uuid,
                   total_visits, unique_visitors, new_visitors
            FROM fact_visitas
            WHERE location_uuid = ?
            ORDER BY fecha
        """, [location_uuid]).df()
        df['fecha'] = pd.to_datetime(df['fecha'])
    elif session_id:
        df = _get_from_csv(location_uuid, session_id)
    else:
        return pd.DataFrame()

    if df.empty:
        return df

    # 2. Weather enrichment
    weather = _get_weather(location_uuid, df['fecha'])
    if not weather.empty:
        weather['fecha'] = pd.to_datetime(weather['fecha'])
        df = df.merge(weather, on='fecha', how='left')
    else:
        df['temp_max'] = 22.0
        df['temp_min'] = 15.0
        df['llueve'] = 0

    df['temp_max'] = df.get('temp_max', pd.Series(22.0, index=df.index)).fillna(22.0)
    df['temp_min'] = df.get('temp_min', pd.Series(15.0, index=df.index)).fillna(15.0)
    df['llueve']   = df.get('llueve',   pd.Series(0,    index=df.index)).fillna(0).astype(int)

    # 3. Holidays (country-aware)
    region_code = conn.execute(
        "SELECT region_code FROM dim_ubicaciones WHERE location_uuid = ?",
        [location_uuid],
    ).fetchone()
    region = region_code[0] if region_code else None

    df['es_festivo'] = df['fecha'].apply(
        lambda d: _es_festivo(d.date() if hasattr(d, 'date') else d, pais, region)
    )

    df['region_code'] = region or ''
    return df


def get_df_visitas(location_uuids) -> pd.DataFrame:
    """
    Datos crudos de visitas para múltiples locations desde fact_visitas.
    Equivalent to reading the old dataset_{session}.csv filtered by location.
    Alias dwell_time_min → dwell_time para compatibilidad con callbacks.
    Acepta un UUID como string o lista de UUIDs.
    """
    if not location_uuids:
        return pd.DataFrame()
    conn = get_conn()
    placeholders = ','.join(['?' for _ in location_uuids])
    df = conn.execute(f"""
        SELECT fecha,
               location_uuid   AS location_id,
               zone_uuid,
               total_visits,
               unique_visitors,
               new_visitors,
               uv_7d, uv_28d, uv_month, uv_year,
               freq_7d, freq_28d, freq_month, freq_year,
               dwell_time_min  AS dwell_time,
               dwell_hist,
               hourly_visits
        FROM fact_visitas
        WHERE location_uuid IN ({placeholders})
        ORDER BY fecha
    """, location_uuids).df()
    if not df.empty:
        df['fecha'] = pd.to_datetime(df['fecha'])
    return df


def get_ultima_fecha_por_location() -> dict:
    """Devuelve {location_uuid: fecha_max} con la última fecha en fact_visitas."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT location_uuid, MAX(fecha) AS ultima_fecha
        FROM fact_visitas
        GROUP BY location_uuid
    """).fetchall()
    return {r[0]: r[1] for r in rows}


# ── Geo feature temporal join ─────────────────────────────────────────────────

def get_geo_snapshot_df(location_uuid: str, fechas: pd.Series) -> pd.DataFrame:
    """
    Returns a DataFrame with one row per date in fechas, columns = geo feature keys.
    Each row gets the Esri snapshot that was valid at that date.
    Returns an empty DataFrame (no rows, no columns) if no geo data exists.

    Used by ml_predictivo.py to add geo context to the training set.
    """
    conn = get_conn()

    # Load all snapshots for this location
    snaps = conn.execute("""
        SELECT feature_key, value, valid_from, valid_to
        FROM store_geo_snapshots
        WHERE location_uuid = ?
        ORDER BY feature_key, valid_from
    """, [location_uuid]).df()

    if snaps.empty:
        return pd.DataFrame()

    snaps['valid_from'] = pd.to_datetime(snaps['valid_from'])
    snaps['valid_to']   = pd.to_datetime(snaps['valid_to']).fillna(pd.Timestamp('2099-12-31'))

    dates = pd.to_datetime(fechas).rename('fecha')
    geo_cols = snaps['feature_key'].unique()
    result = pd.DataFrame({'fecha': dates})

    for col in geo_cols:
        col_snaps = snaps[snaps['feature_key'] == col].sort_values('valid_from')
        # For each date, find the snapshot valid at that date
        result[col] = result['fecha'].apply(
            lambda d: _snap_value(col_snaps, d)
        )

    result = result.drop(columns=['fecha'])
    return result


# ── Dimension helpers (reemplazan lecturas directas de todas_las_ubicaciones.json) ──

def get_all_orgs() -> list[dict]:
    """[{org_uuid, nombre, pais_codigo}, ...]"""
    return [
        {'org_uuid': r[0], 'nombre': r[1], 'pais_codigo': r[2]}
        for r in get_conn().execute(
            "SELECT org_uuid, nombre, pais_codigo FROM dim_organizaciones ORDER BY nombre"
        ).fetchall()
    ]


def get_locs_for_org(org_uuid: str) -> list[dict]:
    """[{location_uuid, nombre}, ...] para una org."""
    return [
        {'location_uuid': r[0], 'nombre': r[1]}
        for r in get_conn().execute(
            "SELECT location_uuid, nombre FROM dim_ubicaciones WHERE org_uuid = ? AND activa = TRUE ORDER BY nombre",
            [org_uuid],
        ).fetchall()
    ]


def get_zones_for_loc(location_uuid: str) -> list[dict]:
    """[{zone_uuid, nombre, zone_type, hidden, parent_zone_uuid}, ...] para una ubicación."""
    return [
        {'zone_uuid': r[0], 'nombre': r[1], 'zone_type': r[2] or '', 'hidden': r[3], 'parent_zone_uuid': r[4]}
        for r in get_conn().execute(
            "SELECT zone_uuid, nombre, zone_type, hidden, parent_zone_uuid"
            " FROM dim_zonas WHERE location_uuid = ? ORDER BY nombre",
            [location_uuid],
        ).fetchall()
    ]


def get_location_by_uuid(location_uuid: str) -> Optional[dict]:
    """Devuelve dict completo de ubicación + org_nombre, o None."""
    row = get_conn().execute("""
        SELECT u.location_uuid, u.nombre, u.lat, u.lon, u.ciudad, u.provincia,
               u.pais_codigo, u.region_code, u.codigo_postal, u.direccion,
               o.nombre AS org_nombre, o.org_uuid
        FROM dim_ubicaciones u
        JOIN dim_organizaciones o ON o.org_uuid = u.org_uuid
        WHERE u.location_uuid = ?
    """, [location_uuid]).fetchone()
    if row is None:
        return None
    return {
        'uuid': row[0], 'name': row[1], 'lat': row[2], 'lon': row[3],
        'city': row[4], 'province': row[5], 'pais_codigo': row[6],
        'region_code': row[7], 'codigo_postal': row[8], 'direccion': row[9],
        'org': row[10], 'org_uuid': row[11],
    }


def get_location_by_name(nombre: str) -> Optional[dict]:
    """Búsqueda por nombre (insensible a mayúsculas). Devuelve primera coincidencia."""
    row = get_conn().execute(
        "SELECT location_uuid, lat, lon, region_code FROM dim_ubicaciones WHERE lower(nombre) = lower(?) LIMIT 1",
        [nombre],
    ).fetchone()
    if row is None:
        return None
    return {'location_uuid': row[0], 'lat': row[1], 'lon': row[2], 'region_code': row[3]}


def get_locations_with_coords() -> list[str]:
    """UUIDs de ubicaciones que tienen lat/lon y postal_code (para sincronizador)."""
    return [
        r[0] for r in get_conn().execute(
            "SELECT location_uuid FROM dim_ubicaciones WHERE lat IS NOT NULL AND lon IS NOT NULL AND codigo_postal IS NOT NULL AND activa = TRUE"
        ).fetchall()
    ]


def get_all_zones_flat() -> list[dict]:
    """[{zone_uuid, location_uuid, nombre, zone_type}, ...] para todas las zonas visibles."""
    return [
        {'zone_uuid': r[0], 'location_uuid': r[1], 'nombre': r[2], 'zone_type': r[3] or ''}
        for r in get_conn().execute(
            "SELECT zone_uuid, location_uuid, nombre, zone_type FROM dim_zonas WHERE hidden = FALSE ORDER BY nombre"
        ).fetchall()
    ]


def get_active_ext_features(
    location_uuid: str,
    fecha_min: pd.Timestamp,
    fecha_max: pd.Timestamp,
) -> pd.DataFrame:
    """
    Devuelve un DataFrame (índice DatetimeIndex diario) con una columna por cada
    feature activa en feature_flags para esta location.

    Forward-fill diario aplicado: features mensuales (ICM) se propagan al resto del mes.
    """
    from src.db.store import get_conn
    conn = get_conn()

    rows = conn.execute("""
        SELECT feature_key
        FROM   feature_flags
        WHERE  location_uuid = ?
          AND  status = 'active'
        ORDER  BY feature_key
    """, [location_uuid]).fetchall()

    feature_keys = [r[0] for r in rows]
    if not feature_keys:
        return pd.DataFrame(index=pd.date_range(fecha_min, fecha_max, freq='D'))

    full_idx = pd.date_range(fecha_min, fecha_max, freq='D')
    result   = pd.DataFrame(index=full_idx)

    for fk in feature_keys:
        df = conn.execute("""
            SELECT fecha, value::double precision AS value
            FROM   store_features_ext
            WHERE  location_uuid = ?
              AND  feature_key   = ?
              AND  fecha BETWEEN ? AND ?
            ORDER  BY fecha
        """, [location_uuid, fk, fecha_min.date(), fecha_max.date()]).df()

        if df.empty:
            continue
        df['fecha'] = pd.to_datetime(df['fecha'])
        serie = df.set_index('fecha')['value'].reindex(full_idx).fillna(0.0)
        result[fk] = serie.values

    return result


def _snap_value(col_snaps: pd.DataFrame, fecha: pd.Timestamp) -> Optional[float]:
    mask = (col_snaps['valid_from'] <= fecha) & (col_snaps['valid_to'] >= fecha)
    rows = col_snaps[mask]
    if rows.empty:
        return None
    return rows.iloc[-1]['value']  # latest valid snapshot if overlapping
