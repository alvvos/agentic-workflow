"""
Agregador de features de eventos externos para el modelo ML.

Fuentes integradas:
  - Open Holidays API  → vacaciones escolares + festivos regionales (sin key)
  - Ticketmaster       → conciertos, deportes, festivales (key opcional en .env)
  - TheSportsDB        → partidos deportivos por ciudad (sin key)
  - Agenda municipal   → datos.gob.es / ayuntamientos ES (sin key, cobertura parcial)

Storage dual (cada prefetch escribe en ambas tablas):
  - store_calendario_org  → eventos crudos con metadata completa
  - store_features_ext    → scores diarios ev_* para el modelo ML
"""
import json
import os
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from src.data_processing.fuentes_eventos.open_holidays import (
    get_school_holidays,
    get_public_holidays_detail,
    expand_periods,
)
from src.data_processing.fuentes_eventos.ticketmaster import (
    fetch_events_raw,
    events_to_daily_scores,
    events_to_raw_rows,
)
from src.data_processing.fuentes_eventos.thesportsdb import get_events_for_city
from src.data_processing.fuentes_eventos.agenda_es import fetch_agenda_ciudad

# ── Columnas de features ──────────────────────────────────────────────────────

EVENTOS_FEATURE_COLS = [
    'ev_vacaciones_escolares',  # 0/1 — período vacacional escolar
    'ev_festivo_regional',      # 0/1 — festivo regional/local (además del nacional)
    'ev_rank_deportivo',        # 0-100 — carga de eventos deportivos
    'ev_rank_concierto',        # 0-100 — carga de conciertos/música
    'ev_rank_festival',         # 0-100 — carga de festivales/cultura
    'ev_rank_municipal',        # 0-100 — eventos agenda municipal
    'ev_rank_total',            # 0-100 — carga total de eventos
]

_ZERO_ROW: dict = {col: 0 for col in EVENTOS_FEATURE_COLS}

# ── Caché en memoria ─────────────────────────────────────────────────────────
# {location_uuid: {date_str: {col: value}}}  — cargado por location desde DuckDB
_mem: dict[str, dict] = {}

# Locations ya prefetchadas en esta sesión
_prefetched: set[str] = set()


# ── Helpers DuckDB ────────────────────────────────────────────────────────────

def _conn():
    from src.db.store import get_conn
    return get_conn()


def _load_from_db(location_uuid: str) -> dict[str, dict]:
    """
    Carga TODOS los ev_* features de store_features_ext para una location.
    Retorna {date_str: {col: value}}.
    """
    try:
        rows = _conn().execute("""
            SELECT fecha, feature_key, value
            FROM store_features_ext
            WHERE location_uuid = ?
              AND feature_key LIKE 'ev_%'
        """, [location_uuid]).fetchall()
    except Exception:
        return {}

    result: dict[str, dict] = {}
    for fecha, key, value in rows:
        d = str(fecha)
        if d not in result:
            result[d] = dict(_ZERO_ROW)
        result[d][key] = value if value is not None else 0
    return result


def _write_features_ext(location_uuid: str, daily: dict[date, dict]) -> None:
    """Upsert scores diarios → store_features_ext."""
    rows = []
    for d, scores in daily.items():
        for key, value in scores.items():
            if key in EVENTOS_FEATURE_COLS:
                rows.append((str(d), location_uuid, key, float(value)))
    if not rows:
        return
    try:
        _conn().executemany(
            "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) "
            "VALUES (?,?,?,?) ON CONFLICT (fecha, location_uuid, feature_key) "
            "DO UPDATE SET value = excluded.value",
            rows,
        )
    except Exception:
        pass


def _write_calendario_org(location_uuid: str, events: list[dict], pais_codigo: str) -> None:
    """Upsert eventos crudos → store_calendario_org."""
    rows = []
    for ev in events:
        rows.append((
            None,                               # org_uuid
            location_uuid,
            pais_codigo,
            ev['evento_key'],
            str(ev['fecha_inicio']),
            str(ev.get('fecha_fin', ev['fecha_inicio'])),
            json.dumps(ev.get('metadata', {}), ensure_ascii=False),
            ev.get('fuente', 'desconocido'),
            ev.get('source_key'),
        ))
    if not rows:
        return
    try:
        _conn().executemany(
            """INSERT INTO store_calendario_org
               (org_uuid, location_uuid, pais_codigo, evento_key,
                fecha_inicio, fecha_fin, metadata, fuente, source_key)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT (source_key) DO NOTHING""",
            [r for r in rows if r[8] is not None],  # solo filas con source_key
        )
    except Exception:
        pass


# ── Prefetch ──────────────────────────────────────────────────────────────────

def prefetch_eventos(location_uuid: str, force: bool = False) -> int:
    """
    Descarga y cachea en DuckDB todos los eventos externos para una location.
    Cubre desde 2024-01-01 hasta hoy + 90 días.
    Retorna el nº de días con al menos un feature escrito.
    """
    if not force and location_uuid in _prefetched:
        return 0

    from src.db.queries import get_location_by_uuid
    loc = get_location_by_uuid(location_uuid)
    if loc is None:
        _prefetched.add(location_uuid)
        return 0

    lat          = loc.get('lat')
    lon          = loc.get('lon')
    pais_codigo  = loc.get('pais_codigo', 'ES')
    region_code  = loc.get('region_code')
    ciudad       = loc.get('city') or ''

    date_from = date(2024, 1, 1)
    date_to   = date.today() + timedelta(days=90)

    # Accumulate daily scores across all sources
    daily: dict[date, dict] = {}

    def _ensure(d: date) -> dict:
        if d not in daily:
            daily[d] = {
                'ev_vacaciones_escolares': 0,
                'ev_festivo_regional':     0,
                'ev_rank_deportivo':       0,
                'ev_rank_concierto':       0,
                'ev_rank_festival':        0,
                'ev_rank_municipal':       0,
                'ev_rank_total':           0,
            }
        return daily[d]

    raw_calendar_rows: list[dict] = []

    # ── 1. Open Holidays: vacaciones escolares ────────────────────────────────
    years = list(range(date_from.year, date_to.year + 1))
    for year in years:
        periods = get_school_holidays(pais_codigo, year, region_code)
        for d in expand_periods(periods):
            if date_from <= d <= date_to:
                _ensure(d)['ev_vacaciones_escolares'] = 1
                raw_calendar_rows.append({
                    'evento_key':  'vacaciones_escolares',
                    'fecha_inicio': d,
                    'fecha_fin':    d,
                    'fuente':       'open_holidays',
                    'source_key':   f"oh_school:{pais_codigo}:{region_code or ''}:{d}",
                    'metadata':     {'pais': pais_codigo, 'region': region_code},
                })

    # ── 2. Open Holidays: festivos regionales ────────────────────────────────
    for year in years:
        for fh in get_public_holidays_detail(pais_codigo, year, region_code):
            # nationwide=False → festivo regional/local no aplicable en todo el país
            if not fh.get('nationwide', True) and date_from <= fh['fecha'] <= date_to:
                _ensure(fh['fecha'])['ev_festivo_regional'] = 1
                raw_calendar_rows.append({
                    'evento_key':  'festivo_regional',
                    'fecha_inicio': fh['fecha'],
                    'fecha_fin':    fh['fecha'],
                    'fuente':       'open_holidays',
                    'source_key':   f"oh_ph:{pais_codigo}:{region_code or ''}:{fh['fecha']}:{fh['name'][:20]}",
                    'metadata':     {'nombre': fh['name'], 'scope': fh.get('scope', '')},
                })

    # ── 3. Ticketmaster ───────────────────────────────────────────────────────
    if lat and lon:
        tm_raw    = fetch_events_raw(lat, lon, date_from, date_to)
        tm_scores = events_to_daily_scores(tm_raw)
        tm_rows   = events_to_raw_rows(tm_raw, location_uuid)

        for d, cats in tm_scores.items():
            if date_from <= d <= date_to:
                slot = _ensure(d)
                slot['ev_rank_deportivo'] = max(slot['ev_rank_deportivo'], cats.get('deportivo', 0))
                slot['ev_rank_concierto'] = max(slot['ev_rank_concierto'], cats.get('concierto', 0))
                slot['ev_rank_festival']  = max(slot['ev_rank_festival'],  cats.get('festival',  0))
        raw_calendar_rows.extend(tm_rows)

    # ── 4. TheSportsDB ────────────────────────────────────────────────────────
    if ciudad:
        for ev in get_events_for_city(ciudad, pais_codigo, date_from, date_to):
            d = ev['fecha']
            slot = _ensure(d)
            slot['ev_rank_deportivo'] = max(slot['ev_rank_deportivo'], ev['score'])
            raw_calendar_rows.append({
                'evento_key':  'partido_deportivo',
                'fecha_inicio': d,
                'fecha_fin':    d,
                'fuente':       'thesportsdb',
                'source_key':   f"tsdb:{location_uuid}:{ev['source_key']}",
                'metadata':     {
                    'evento':      ev['evento'],
                    'liga':        ev['liga'],
                    'sede':        ev.get('sede', ''),
                    'ciudad_sede': ev.get('ciudad_sede', ''),
                    'es_local':    ev.get('es_local', True),
                },
            })

    # ── 5. Agenda municipal ───────────────────────────────────────────────────
    if ciudad:
        for ev in fetch_agenda_ciudad(ciudad, date_from, date_to):
            d = ev['fecha']
            slot = _ensure(d)
            slot['ev_rank_municipal'] = max(slot['ev_rank_municipal'], ev['score'])
            raw_calendar_rows.append({
                'evento_key':  'evento_municipal',
                'fecha_inicio': d,
                'fecha_fin':    d,
                'fuente':       'agenda_municipal',
                'source_key':   f"muni:{location_uuid}:{ev['source_key']}",
                'metadata':     {'titulo': ev['titulo'], 'categoria': ev['categoria']},
            })

    # ── 6. Calcular ev_rank_total ─────────────────────────────────────────────
    for d, slot in daily.items():
        slot['ev_rank_total'] = min(100, max(
            slot['ev_rank_deportivo'],
            slot['ev_rank_concierto'],
            slot['ev_rank_festival'],
            slot['ev_rank_municipal'],
        ))

    # ── 7. Persistir en DuckDB ────────────────────────────────────────────────
    _write_features_ext(location_uuid, daily)
    _write_calendario_org(location_uuid, raw_calendar_rows, pais_codigo)

    # ── 8. Actualizar caché en memoria ────────────────────────────────────────
    _mem[location_uuid] = _load_from_db(location_uuid)
    _prefetched.add(location_uuid)

    return len(daily)


# ── Interfaz pública ──────────────────────────────────────────────────────────

def get_eventos_features(fecha, location_uuid: Optional[str] = None) -> dict:
    """
    Retorna ev_* features para una fecha y location_uuid.
    Carga lazy: prefetch completo en primer acceso por location.
    """
    if not isinstance(fecha, date):
        try:
            fecha = pd.to_datetime(fecha).date()
        except Exception:
            return dict(_ZERO_ROW)

    if location_uuid:
        if location_uuid not in _mem:
            # Primera vez: cargar desde DuckDB o prefetch
            cached = _load_from_db(location_uuid)
            if not cached:
                prefetch_eventos(location_uuid)
            else:
                _mem[location_uuid] = cached
                _prefetched.add(location_uuid)

        row = _mem.get(location_uuid, {}).get(str(fecha))
        if row:
            return dict(row)

    return dict(_ZERO_ROW)


def prefetch_all_locations(force: bool = False) -> dict:
    """
    Ejecuta prefetch_eventos para todas las ubicaciones activas en DuckDB.
    Útil para inicializar los datos o refrescar tras cambios de calendario.
    Retorna {location_uuid: n_dias}.
    """
    from src.db.queries import get_locations_with_coords, get_all_zones_flat
    from src.db.store import get_conn as _db

    all_uuids = [
        r[0] for r in _db().execute(
            "SELECT location_uuid FROM dim_ubicaciones WHERE activa = TRUE"
        ).fetchall()
    ]

    results = {}
    for i, uuid in enumerate(all_uuids, 1):
        print(f"  [{i:02d}/{len(all_uuids)}] {uuid[:8]}...", end=" ", flush=True)
        n = prefetch_eventos(uuid, force=force)
        results[uuid] = n
        print(f"{n} días")
    return results
