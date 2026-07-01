"""
Helpers compartidos para los ingestores mensuales.

Provee tres utilidades que todos los módulos de mensual/ necesitan:
  - get_configured_locations(source) — lee location_source_config
  - write_month_uniform(...)         — distribuye un total mensual en días
  - ensure_feature_registry(...)     — registra el feature_key si no existe
"""

from __future__ import annotations

import calendar
import json
from datetime import date

from src.db.store import get_conn


def get_configured_locations(source: str) -> list[tuple[str, dict]]:
    """
    Lee location_source_config para el source dado.
    Devuelve [(location_uuid, params_dict), ...] solo para filas activas.
    """
    rows = (
        get_conn()
        .execute(
            "SELECT location_uuid, params "
            "FROM location_source_config "
            "WHERE source = ? AND activo = TRUE",
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
    Distribuye un total mensual uniformemente entre todos los días del mes
    y hace upsert en store_features_ext.

    Solo escribe meses ya cerrados (último día < hoy). Idempotente.
    Devuelve el número de filas escritas (0 si mes en curso o total ≤ 0).
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
        "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT (fecha, location_uuid, feature_key) "
        "DO UPDATE SET value = excluded.value, ingested_at = NOW()",
        rows,
    )
    if verbose:
        print(f"  [{feature_key}] {month:02d}/{year}: {total:,.0f} → {val_per_day:.1f}/día")
    return len(rows)


def ensure_feature_registry(
    feature_key: str,
    source: str,
    categoria: str,
    notas: str = "",
) -> None:
    """Registra el feature_key en feature_registry si no existe. Usa columnas reales del schema."""
    get_conn().execute(
        "INSERT INTO feature_registry (feature_key, source, categoria, notas, status) "
        "VALUES (?,?,?,?,'con_cobertura') ON CONFLICT (feature_key) DO NOTHING",
        [feature_key, source, categoria, notas],
    )
