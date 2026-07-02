"""
Helpers compartidos para todos los ingestores diarios y mensuales.

Merge de diaria/_common.py + mensual/_common.py.

Cada source usa un sync marker (_sync_{source}) para rastrear su ultima ejecucion
de forma univoca — sin depender del nombre de columna ML (que es compartido entre sources).
"""

from __future__ import annotations

import calendar
import json
from datetime import date

import pandas as pd

from src.db.store import get_conn

# ── Barrera de clientes activos ──────────────────────────────────────────────
# TODO: levantar cuando entren nuevos clientes — quitar el set y la cláusula AND.
ALLOWED_ORG_IDS: frozenset[str] = frozenset(
    {"5c13b57d-782d-4458-911b-64cd40eebb55"}
)  # Miniso España

# ── Ventanas de tiempo ────────────────────────────────────────────────────────

EVENTS_DATE_FROM = date(2024, 1, 1)
EVENTS_HORIZON = 90  # dias adelante para eventos
WEATHER_ARCHIVE_LAG = 7  # dias de retraso del archivo Open-Meteo
WEATHER_FORECAST = 16  # dias de pronostico (limite free tier)

# ── Feature columns ───────────────────────────────────────────────────────────
# Definidas aqui para que eventos_client.py las importe sin dependencia circular.

EVENTOS_FEATURE_COLS: list[str] = [
    "ev_vacaciones_escolares",
    "ev_festivo_regional",
    "ev_rank_deportivo",
    "ev_rank_concierto",
    "ev_rank_festival",
    "ev_rank_municipal",
    "ev_rank_total",
]


# ── Locations ─────────────────────────────────────────────────────────────────


def get_active_locations(location_uuid: str | None = None) -> list[dict]:
    """Devuelve lista de dicts con {uuid, nombre, lat, lon, pais_codigo, region_code, city}."""
    _org_placeholders = ",".join(["%s"] * len(ALLOWED_ORG_IDS))
    _org_args = list(ALLOWED_ORG_IDS)

    if location_uuid:
        row = (
            get_conn()
            .execute(
                f"""SELECT ubicacion_id, nombre, lat, lon, pais_codigo, region_code, ciudad
               FROM   ubicaciones
               WHERE  ubicacion_id = %s AND activa = TRUE
                 AND  org_id IN ({_org_placeholders})""",
                [location_uuid] + _org_args,
            )
            .fetchone()
        )
        return [_to_loc(row)] if row and row[2] is not None else []

    rows = (
        get_conn()
        .execute(
            f"""SELECT ubicacion_id, nombre, lat, lon, pais_codigo, region_code, ciudad
           FROM   ubicaciones
           WHERE  activa = TRUE AND lat IS NOT NULL AND lon IS NOT NULL
             AND  org_id IN ({_org_placeholders})""",
            _org_args,
        )
        .fetchall()
    )
    return [_to_loc(r) for r in rows]


def _to_loc(r) -> dict:
    return {
        "uuid": r[0],
        "ubicacion_id": r[0],
        "nombre": r[1],
        "lat": float(r[2]),
        "lon": float(r[3]),
        "pais_codigo": r[4] or "ES",
        "region_code": r[5],
        "city": r[6] or "",
    }


# ── Freshness (sync markers) ──────────────────────────────────────────────────


def is_fresh(location_uuid: str, source_name: str, max_age_hours: float) -> bool:
    """
    True si el sync marker de este source fue escrito hace menos de max_age_hours.
    Marker: feature_key = '_sync_{source_name}', value = 1.0, fecha = hoy.
    """
    if max_age_hours <= 0:
        return False
    try:
        row = (
            get_conn()
            .execute(
                "SELECT MAX(ingested_at) FROM valores_señales "
                "WHERE  ubicacion_id = ? AND señal_id = ?",
                [location_uuid, f"_sync_{source_name}"],
            )
            .fetchone()
        )
        if row and row[0]:
            age_h = (pd.Timestamp.now() - pd.Timestamp(row[0])).total_seconds() / 3600
            return age_h < max_age_hours
    except Exception:
        pass
    return False


def write_sync_marker(location_uuid: str, source_name: str) -> None:
    """Escribe/actualiza el sync marker del source para este location."""
    try:
        get_conn().execute(
            "INSERT INTO valores_señales (fecha, ubicacion_id, señal_id, valor) "
            "VALUES (CURRENT_DATE, ?, ?, 1.0) "
            "ON CONFLICT (fecha, ubicacion_id, señal_id) "
            "DO UPDATE SET valor = 1.0, ingested_at = NOW()",
            [location_uuid, f"_sync_{source_name}"],
        )
    except Exception:
        pass


# ── DB writes ─────────────────────────────────────────────────────────────────


def write_ev_features(location_uuid: str, daily: dict[date, dict]) -> None:
    """Upsert scores diarios de eventos en valores_señales."""
    rows = []
    for d, scores in daily.items():
        for key, value in scores.items():
            if key in EVENTOS_FEATURE_COLS:
                rows.append((str(d), location_uuid, key, float(value)))
    if not rows:
        return
    try:
        get_conn().executemany(
            "INSERT INTO valores_señales (fecha, ubicacion_id, señal_id, valor) "
            "VALUES (?,?,?,?) ON CONFLICT (fecha, ubicacion_id, señal_id) "
            "DO UPDATE SET valor = GREATEST(valores_señales.valor, excluded.valor), ingested_at = NOW()",
            rows,
        )
    except Exception:
        pass


def write_calendario_org(location_uuid: str, events: list[dict], pais_codigo: str) -> None:
    """Upsert eventos crudos en eventos."""
    rows = [
        (
            None,
            location_uuid,
            pais_codigo,
            ev["evento_key"],
            str(ev["fecha_inicio"]),
            str(ev.get("fecha_fin", ev["fecha_inicio"])),
            json.dumps(ev.get("metadata", {}), ensure_ascii=False),
            ev.get("fuente", "desconocido"),
            ev.get("source_key"),
        )
        for ev in events
        if ev.get("source_key")
    ]
    if not rows:
        return
    try:
        get_conn().executemany(
            """INSERT INTO eventos
               (org_id, ubicacion_id, pais_codigo, evento_key,
                fecha_inicio, fecha_fin, metadata, fuente, source_key)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT (source_key) DO NOTHING""",
            rows,
        )
    except Exception:
        pass


def update_ev_rank_total(location_uuid: str, date_from: date, date_to: date) -> None:
    """
    Recalcula ev_rank_total = max(deportivo, concierto, festival, municipal) por dia.
    Debe llamarse despues de que todos los sources de eventos hayan escrito sus datos.
    """
    try:
        get_conn().execute(
            """
            INSERT INTO valores_señales (fecha, ubicacion_id, señal_id, valor)
            SELECT
                fecha,
                ?,
                'ev_rank_total',
                LEAST(100, GREATEST(
                    COALESCE(MAX(CASE WHEN señal_id = 'ev_rank_deportivo'  THEN valor END), 0),
                    COALESCE(MAX(CASE WHEN señal_id = 'ev_rank_concierto'  THEN valor END), 0),
                    COALESCE(MAX(CASE WHEN señal_id = 'ev_rank_festival'   THEN valor END), 0),
                    COALESCE(MAX(CASE WHEN señal_id = 'ev_rank_municipal'  THEN valor END), 0),
                ))
            FROM   valores_señales
            WHERE  ubicacion_id = ?
              AND  señal_id IN ('ev_rank_deportivo','ev_rank_concierto','ev_rank_festival','ev_rank_municipal')
              AND  fecha BETWEEN ? AND ?
            GROUP  BY fecha
            ON CONFLICT (fecha, ubicacion_id, señal_id)
            DO UPDATE SET valor = excluded.valor, ingested_at = NOW()
            """,
            [location_uuid, location_uuid, str(date_from), str(date_to)],
        )
    except Exception:
        pass


# ── Mensual helpers ───────────────────────────────────────────────────────────


def get_configured_locations(source: str) -> list[tuple[str, dict]]:
    """
    Lee config_fuentes para el source dado.
    Devuelve [(ubicacion_id, params_dict), ...] solo para filas activas.
    """
    rows = (
        get_conn()
        .execute(
            "SELECT ubicacion_id, params "
            "FROM config_fuentes "
            "WHERE fuente = ? AND activo = TRUE",
            [source],
        )
        .fetchall()
    )
    result = []
    for loc_uuid, params_raw in rows:
        params = params_raw if isinstance(params_raw, dict) else json.loads(params_raw or "{}")
        result.append((loc_uuid, params))
    return result


def write_month_uniform(
    year: int,
    month: int,
    total: float,
    location_uuid: str,
    feature_key: str,
    verbose: bool = False,
) -> int:
    """
    Distribuye un total mensual uniformemente entre todos los dias del mes
    y hace upsert en store_features_ext.

    Solo escribe meses ya cerrados (ultimo dia < hoy). Idempotente.
    Devuelve el numero de filas escritas (0 si mes en curso o total <= 0).
    """
    if total <= 0:
        return 0
    today = date.today()
    last_day = calendar.monthrange(year, month)[1]
    if date(year, month, last_day) >= today:
        return 0

    val_per_day = total / last_day
    rows = [
        (str(date(year, month, d)), location_uuid, feature_key, val_per_day)
        for d in range(1, last_day + 1)
    ]
    get_conn().executemany(
        "INSERT INTO valores_señales (fecha, ubicacion_id, señal_id, valor) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT (fecha, ubicacion_id, señal_id) "
        "DO UPDATE SET valor = excluded.valor, ingested_at = NOW()",
        rows,
    )
    if verbose:
        print(f"  [{feature_key}] {month:02d}/{year}: {total:,.0f} → {val_per_day:.1f}/dia")
    return len(rows)


def ensure_feature_registry(
    feature_key: str,
    source: str,
    categoria: str,
    notas: str = "",
) -> None:
    """Registra el señal_id en señales si no existe. Usa columnas reales del schema."""
    get_conn().execute(
        "INSERT INTO señales (señal_id, fuente, categoria, notas, status) "
        "VALUES (?,?,?,?,'con_cobertura') ON CONFLICT (señal_id) DO NOTHING",
        [feature_key, source, categoria, notas],
    )


# ── Source registry ───────────────────────────────────────────────────────────


def get_source_config(source: str, loc_params: dict | None = None) -> dict:
    """
    Devuelve config efectiva para un source: defaults de fuentes
    fusionados con los params de la location (los params de location tienen precedencia).
    """
    row = (
        get_conn()
        .execute(
            "SELECT config FROM fuentes WHERE fuente = %s",
            [source],
        )
        .fetchone()
    )
    defaults: dict = row[0] if row and row[0] else {}
    return {**defaults, **(loc_params or {})}


# ── CLI helpers ───────────────────────────────────────────────────────────────


def make_parser(source_desc: str):
    """Crea un ArgumentParser estandar para los scripts de prefetch."""
    import argparse

    p = argparse.ArgumentParser(description=f"Prefetch {source_desc}")
    p.add_argument("--location", metavar="UUID", help="Procesar solo esta location")
    p.add_argument(
        "--max-age",
        type=float,
        default=6,
        metavar="HORAS",
        help="Omite si los datos tienen menos de N horas (default: 6). 0 = siempre descargar",
    )
    p.add_argument("--force", action="store_true", help="Fuerza descarga (equivale a --max-age 0)")
    p.add_argument("--quiet", action="store_true", help="Sin salida por pantalla")
    return p
