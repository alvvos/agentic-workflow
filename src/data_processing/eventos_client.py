"""
Interfaz de lectura de eventos externos para el modelo ML.

La lógica de descarga/escritura vive en src/data_ingestion/diaria/.
Este módulo expone únicamente la interfaz de lectura usada en runtime:
  - get_eventos_features(fecha, location_uuid)  → dict con ev_* features
  - EVENTOS_FEATURE_COLS                        → lista de nombres de columna

Backward-compat:
  - prefetch_eventos(location_uuid, force, max_age_hours)  usado por ml_predictivo
  - prefetch_all_locations(force)                          usado por seed.py
"""

from typing import Optional

import pandas as pd

EVENTOS_FEATURE_COLS: list[str] = [
    "ev_vacaciones_escolares",
    "ev_festivo_regional",
    "ev_rank_deportivo",
    "ev_rank_concierto",
    "ev_rank_festival",
    "ev_rank_municipal",
    "ev_rank_total",
]

_ZERO_ROW: dict = {col: 0 for col in EVENTOS_FEATURE_COLS}

# ── Caché en memoria ──────────────────────────────────────────────────────────
# {location_uuid: {date_str: {col: value}}}
_mem: dict[str, dict] = {}
_prefetched: set[str] = set()


def _conn():
    from src.db.store import get_conn

    return get_conn()


def _load_from_db(location_uuid: str) -> dict[str, dict]:
    """Carga ev_* features de store_features_ext para una location → {date_str: {col: value}}."""
    try:
        rows = (
            _conn()
            .execute(
                """
            SELECT fecha, feature_key, value
            FROM   store_features_ext
            WHERE  location_uuid = ?
              AND  feature_key LIKE 'ev_%%'
        """,
                [location_uuid],
            )
            .fetchall()
        )
    except Exception:
        return {}

    result: dict[str, dict] = {}
    for fecha, key, value in rows:
        d = str(fecha)
        if d not in result:
            result[d] = dict(_ZERO_ROW)
        result[d][key] = value if value is not None else 0
    return result


# ── Interfaz pública de lectura ───────────────────────────────────────────────


def get_eventos_features(fecha, location_uuid: Optional[str] = None) -> dict:
    """
    Devuelve ev_* features para una fecha y location_uuid.
    Carga lazy desde DB en el primer acceso por location.
    Si no hay datos en DB, dispara un prefetch completo en segundo plano.
    """
    if not isinstance(fecha, pd.Timestamp):
        try:
            fecha = pd.to_datetime(fecha)
        except Exception:
            return dict(_ZERO_ROW)

    fecha_date = fecha.date() if hasattr(fecha, "date") else fecha

    if location_uuid:
        if location_uuid not in _mem:
            cached = _load_from_db(location_uuid)
            if cached:
                _mem[location_uuid] = cached
                _prefetched.add(location_uuid)
            else:
                # Sin datos en DB: prefetch en background (no bloquea el request)
                import threading

                threading.Thread(
                    target=prefetch_eventos,
                    args=(location_uuid,),
                    daemon=True,
                ).start()

        row = _mem.get(location_uuid, {}).get(str(fecha_date))
        if row:
            return dict(row)

    return dict(_ZERO_ROW)


# ── Backward-compat (usados por ml_predictivo y seed) ────────────────────────


def prefetch_eventos(
    location_uuid: str,
    force: bool = False,
    max_age_hours: float = 0,
) -> int:
    """
    Descarga y cachea eventos para una location.
    Delega a src.data_ingestion.diaria.run_all.
    Mantenido por compatibilidad con ml_predictivo.py y seed.py.
    """
    if not force and location_uuid in _prefetched:
        return 0

    from src.data_ingestion.sync_diaria import run_all as _run

    result = _run(
        location_uuid=location_uuid,
        max_age_hours=max_age_hours,
        verbose=False,
    )
    total = sum(v for src_stats in result.values() for v in src_stats.values())

    _mem[location_uuid] = _load_from_db(location_uuid)
    _prefetched.add(location_uuid)
    return total


def prefetch_all_locations(force: bool = False) -> dict:
    """
    Prefetch de todas las locations activas.
    Mantenido por compatibilidad con seed.py.
    """
    from src.data_ingestion.sync_diaria import run_all as _run

    return _run(max_age_hours=0 if force else 6, verbose=True)
