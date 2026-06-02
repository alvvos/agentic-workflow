from datetime import date, timedelta
from typing import Optional
import pandas as pd

# Spain + shared events
_ES_COLS = [
    'es_rebajas_invierno',
    'es_rebajas_verano',
    'es_black_friday_semana',
    'es_cyber_monday',
    'es_navidad_compras',
    'es_reyes_compras',
    'es_san_valentin_ventana',
    'es_dia_madre_ventana',
]

# Mexico-specific events (always 0 for ES orgs; model learns the split via training data)
_MX_COLS = [
    'es_buen_fin_mx',
    'es_dia_muertos_ventana',
    'es_independencia_mx',
    'es_dia_madre_mx',
    'es_regreso_clases_mx',
    'es_dia_nino_mx',
]

CALENDARIO_FEATURE_COLS = _ES_COLS + _MX_COLS + ['dias_hasta_evento_comercial']

# Default config: all ES events on, all MX events off.
# Use CONFIG_PRESETS['MX'] for Mexican orgs or pass org_config overrides directly.
_DEFAULT_CONFIG = {
    # ES
    'rebajas_invierno': True,
    'rebajas_verano': True,
    'black_friday': True,
    'cyber_monday': True,
    'navidad_compras': True,
    'reyes_compras': True,
    'san_valentin': True,
    'dia_madre': True,
    # MX (off by default)
    'buen_fin_mx': False,
    'dia_muertos': False,
    'independencia_mx': False,
    'dia_madre_mx': False,
    'regreso_clases_mx': False,
    'dia_nino_mx': False,
}

# Ready-to-use presets — pass as org_config or store in dim_organizaciones.config_calendario
CONFIG_PRESETS: dict = {
    'ES': dict(_DEFAULT_CONFIG),
    'MX': {
        'rebajas_invierno': False,
        'rebajas_verano': False,
        'black_friday': False,   # replaced by buen_fin_mx
        'cyber_monday': True,
        'navidad_compras': True,
        'reyes_compras': True,
        'san_valentin': True,
        'dia_madre': False,      # ES = 1st Sunday May; MX = May 10 fixed
        'buen_fin_mx': True,
        'dia_muertos': True,
        'independencia_mx': True,
        'dia_madre_mx': True,
        'regreso_clases_mx': True,
        'dia_nino_mx': True,
    },
}


# ── date helpers ──────────────────────────────────────────────────────────────

def _black_friday(year: int) -> date:
    d = date(year, 11, 30)
    while d.weekday() != 4:  # Friday
        d -= timedelta(days=1)
    return d


def _dia_madre_es(year: int) -> date:
    """First Sunday of May (Spain)."""
    d = date(year, 5, 1)
    while d.weekday() != 6:
        d += timedelta(days=1)
    return d


def _buen_fin_mx(year: int) -> date:
    """
    Start of El Buen Fin (MX): Friday preceding the 3rd Monday of November.
    The 3rd Monday of November is Mexico's Día de la Revolución (movable holiday).
    2024 → Nov 15 (Fri); 2023 → Nov 17 (Fri); 2025 → Nov 14 (Fri).
    """
    d = date(year, 11, 1)
    lunes = 0
    while True:
        if d.weekday() == 0:
            lunes += 1
            if lunes == 3:
                return d - timedelta(days=3)  # preceding Friday
        d += timedelta(days=1)


# ── event builder ─────────────────────────────────────────────────────────────

def _eventos_del_anio(year: int, config: dict) -> list:
    """Returns [(start, end, feature_key), ...] for the given year."""
    eventos = []

    # ── Spain / global ────────────────────────────────────────────────────────
    if config.get('reyes_compras', True):
        eventos.append((date(year, 1, 1), date(year, 1, 5), 'es_reyes_compras'))
    if config.get('rebajas_invierno', True):
        eventos.append((date(year, 1, 7), date(year, 2, 28), 'es_rebajas_invierno'))
    if config.get('san_valentin', True):
        eventos.append((date(year, 2, 7), date(year, 2, 14), 'es_san_valentin_ventana'))
    if config.get('dia_madre', True):
        dm = _dia_madre_es(year)
        eventos.append((dm - timedelta(days=7), dm, 'es_dia_madre_ventana'))
    if config.get('rebajas_verano', True):
        eventos.append((date(year, 7, 1), date(year, 8, 31), 'es_rebajas_verano'))

    bf = _black_friday(year)
    if config.get('black_friday', True):
        bf_monday = bf - timedelta(days=4)
        eventos.append((bf_monday, bf, 'es_black_friday_semana'))
    if config.get('cyber_monday', True):
        cm = bf + timedelta(days=3)
        eventos.append((cm, cm, 'es_cyber_monday'))
    if config.get('navidad_compras', True):
        eventos.append((date(year, 12, 1), date(year, 12, 24), 'es_navidad_compras'))

    # ── Mexico ────────────────────────────────────────────────────────────────
    if config.get('dia_nino_mx', False):
        # Día del Niño: April 30 (shopping window Apr 28–30)
        eventos.append((date(year, 4, 28), date(year, 4, 30), 'es_dia_nino_mx'))
    if config.get('dia_madre_mx', False):
        # Día de la Madre MX: fixed May 10 (shopping window May 3–10)
        eventos.append((date(year, 5, 3), date(year, 5, 10), 'es_dia_madre_mx'))
    if config.get('independencia_mx', False):
        # Noche de independencia Sep 15 + holiday Sep 16 (shopping Sep 13–16)
        eventos.append((date(year, 9, 13), date(year, 9, 16), 'es_independencia_mx'))
    if config.get('regreso_clases_mx', False):
        # Back-to-school MX: mid-August
        eventos.append((date(year, 8, 15), date(year, 8, 31), 'es_regreso_clases_mx'))
    if config.get('buen_fin_mx', False):
        # El Buen Fin: 4-day event (Fri–Mon) around the 3rd Monday of November
        bf_mx = _buen_fin_mx(year)
        eventos.append((bf_mx, bf_mx + timedelta(days=3), 'es_buen_fin_mx'))
    if config.get('dia_muertos', False):
        # Día de Muertos: Oct 31–Nov 2 (shopping window Oct 28–Nov 2)
        eventos.append((date(year, 10, 28), date(year, 11, 2), 'es_dia_muertos_ventana'))

    return eventos


# ── public API ────────────────────────────────────────────────────────────────

def get_calendario_features(fecha, org_config: Optional[dict] = None) -> dict:
    """
    Returns commercial calendar features for a given date as a flat dict.

    org_config: per-org event toggles — {event_key: True/False}.
    Pass CONFIG_PRESETS['MX'] for Mexican orgs, or load from
    dim_organizaciones.config_calendario in DuckDB.
    Default (None) → all ES events on, all MX events off.
    """
    if isinstance(fecha, pd.Timestamp):
        fecha = fecha.date()
    elif not isinstance(fecha, date):
        fecha = pd.to_datetime(fecha).date()

    config = {**_DEFAULT_CONFIG, **(org_config or {})}
    year = fecha.year

    # Three years to handle year-boundary lookups and countdowns
    all_events = (
        _eventos_del_anio(year - 1, config)
        + _eventos_del_anio(year, config)
        + _eventos_del_anio(year + 1, config)
    )

    result = {col: 0 for col in CALENDARIO_FEATURE_COLS}

    for start, end, key in all_events:
        if start <= fecha <= end:
            result[key] = 1

    # Days to nearest upcoming event start (capped at 30)
    dias_hasta = 30
    for start, _end, _key in all_events:
        if start > fecha:
            delta = (start - fecha).days
            if delta < dias_hasta:
                dias_hasta = delta
    result['dias_hasta_evento_comercial'] = dias_hasta

    return result
