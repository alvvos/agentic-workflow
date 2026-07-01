"""
Helpers compartidos para todos los ingestores diarios y mensuales.

Cada source usa un sync marker (_sync_{source}) para rastrear su última ejecución
de forma unívoca — sin depender del nombre de columna ML (que es compartido entre sources).
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from src.db.store import get_conn

# ── Ventanas de tiempo ────────────────────────────────────────────────────────

EVENTS_DATE_FROM = date(2024, 1, 1)
EVENTS_HORIZON = 90  # días adelante para eventos
WEATHER_ARCHIVE_LAG = 7  # días de retraso del archivo Open-Meteo
WEATHER_FORECAST = 16  # días de pronóstico (límite free tier)

# ── Feature columns ───────────────────────────────────────────────────────────
# Definidas aquí para que eventos_client.py las importe sin dependencia circular.

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
    if location_uuid:
        row = (
            get_conn()
            .execute(
                """SELECT location_uuid, nombre, lat, lon, pais_codigo, region_code, ciudad
               FROM   dim_ubicaciones
               WHERE  location_uuid = ? AND activa = TRUE""",
                [location_uuid],
            )
            .fetchone()
        )
        return [_to_loc(row)] if row and row[2] is not None else []

    rows = (
        get_conn()
        .execute(
            """SELECT location_uuid, nombre, lat, lon, pais_codigo, region_code, ciudad
           FROM   dim_ubicaciones
           WHERE  activa = TRUE AND lat IS NOT NULL AND lon IS NOT NULL"""
        )
        .fetchall()
    )
    return [_to_loc(r) for r in rows]


def _to_loc(r) -> dict:
    return {
        "uuid": r[0],
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
                "SELECT MAX(ingested_at) FROM store_features_ext "
                "WHERE  location_uuid = ? AND feature_key = ?",
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
            "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) "
            "VALUES (CURRENT_DATE, ?, ?, 1.0) "
            "ON CONFLICT (fecha, location_uuid, feature_key) "
            "DO UPDATE SET value = 1.0, ingested_at = NOW()",
            [location_uuid, f"_sync_{source_name}"],
        )
    except Exception:
        pass


# ── DB writes ─────────────────────────────────────────────────────────────────


def write_ev_features(location_uuid: str, daily: dict[date, dict]) -> None:
    """Upsert scores diarios de eventos en store_features_ext."""
    rows = []
    for d, scores in daily.items():
        for key, value in scores.items():
            if key in EVENTOS_FEATURE_COLS:
                rows.append((str(d), location_uuid, key, float(value)))
    if not rows:
        return
    try:
        get_conn().executemany(
            "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) "
            "VALUES (?,?,?,?) ON CONFLICT (fecha, location_uuid, feature_key) "
            "DO UPDATE SET value = GREATEST(store_features_ext.value, excluded.value), ingested_at = NOW()",
            rows,
        )
    except Exception:
        pass


def write_calendario_org(location_uuid: str, events: list[dict], pais_codigo: str) -> None:
    """Upsert eventos crudos en store_calendario_org."""
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
            """INSERT INTO store_calendario_org
               (org_uuid, location_uuid, pais_codigo, evento_key,
                fecha_inicio, fecha_fin, metadata, fuente, source_key)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT (source_key) DO NOTHING""",
            rows,
        )
    except Exception:
        pass


def update_ev_rank_total(location_uuid: str, date_from: date, date_to: date) -> None:
    """
    Recalcula ev_rank_total = max(deportivo, concierto, festival, municipal) por día.
    Debe llamarse después de que todos los sources de eventos hayan escrito sus datos.
    """
    try:
        get_conn().execute(
            """
            INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value)
            SELECT
                fecha,
                ?,
                'ev_rank_total',
                LEAST(100, GREATEST(
                    COALESCE(MAX(CASE WHEN feature_key = 'ev_rank_deportivo'  THEN value END), 0),
                    COALESCE(MAX(CASE WHEN feature_key = 'ev_rank_concierto'  THEN value END), 0),
                    COALESCE(MAX(CASE WHEN feature_key = 'ev_rank_festival'   THEN value END), 0),
                    COALESCE(MAX(CASE WHEN feature_key = 'ev_rank_municipal'  THEN value END), 0),
                ))
            FROM   store_features_ext
            WHERE  location_uuid = ?
              AND  feature_key IN ('ev_rank_deportivo','ev_rank_concierto','ev_rank_festival','ev_rank_municipal')
              AND  fecha BETWEEN ? AND ?
            GROUP  BY fecha
            ON CONFLICT (fecha, location_uuid, feature_key)
            DO UPDATE SET value = excluded.value, ingested_at = NOW()
            """,
            [location_uuid, location_uuid, str(date_from), str(date_to)],
        )
    except Exception:
        pass


# ── CLI helpers ───────────────────────────────────────────────────────────────


def make_parser(source_desc: str):
    """Crea un ArgumentParser estándar para los scripts de prefetch."""
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
