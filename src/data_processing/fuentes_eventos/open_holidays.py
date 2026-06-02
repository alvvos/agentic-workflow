"""
Open Holidays API — vacaciones escolares y festivos regionales.
https://openholidaysapi.org/api/v1/
Sin API key. Gratis. Cubre ES, MX y más de 50 países.
"""
import requests
from datetime import date, timedelta
from typing import Optional

_BASE    = "https://openholidaysapi.org"
_TIMEOUT = 15

# region_code (dim_ubicaciones) → Open Holidays subdivision code
_SUBDIV_ES: dict[str, str] = {
    'AN': 'ES-AN', 'AR': 'ES-AR', 'AS': 'ES-AS', 'CB': 'ES-CB',
    'CE': 'ES-CE', 'CL': 'ES-CL', 'CM': 'ES-CM', 'CN': 'ES-CN',
    'CT': 'ES-CT', 'EX': 'ES-EX', 'GA': 'ES-GA', 'IB': 'ES-IB',
    'MC': 'ES-MC', 'MD': 'ES-MD', 'ML': 'ES-ML', 'MU': 'ES-MC',
    'NC': 'ES-NC', 'PV': 'ES-PV', 'RI': 'ES-RI', 'VC': 'ES-VC',
}
_SUBDIV_MX: dict[str, str] = {
    'CDMX': 'MX-CMX', 'JAL': 'MX-JAL', 'NL': 'MX-NLE',
    'YUC': 'MX-YUC', 'NLE': 'MX-NLE',
}


def _get(endpoint: str, params: dict) -> list:
    try:
        r = requests.get(f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json() or []
    except Exception:
        return []


def _name(item: dict) -> str:
    names = item.get('name') or []
    return names[0].get('text', '') if names else ''


def get_school_holidays(pais_codigo: str, year: int, region_code: Optional[str] = None) -> list[dict]:
    """
    Returns school holiday periods as [{start: date, end: date, name: str}].
    region_code mejora la precisión (comunidad autónoma en ES, estado en MX).
    """
    subdiv_map = _SUBDIV_ES if pais_codigo == 'ES' else _SUBDIV_MX
    params = {
        'countryIsoCode': pais_codigo,
        'languageIsoCode': pais_codigo,
        'validFrom': f"{year}-01-01",
        'validTo':   f"{year}-12-31",
    }
    subdiv = subdiv_map.get(region_code or '')
    if subdiv:
        params['subdivisionCode'] = subdiv

    result = []
    for item in _get('SchoolHolidays', params):
        try:
            result.append({
                'start': date.fromisoformat(item['startDate']),
                'end':   date.fromisoformat(item['endDate']),
                'name':  _name(item),
            })
        except Exception:
            continue
    return result


def get_public_holidays_detail(pais_codigo: str, year: int, region_code: Optional[str] = None) -> list[dict]:
    """
    Returns public holidays with type flag (National / Regional / Local).
    """
    subdiv_map = _SUBDIV_ES if pais_codigo == 'ES' else _SUBDIV_MX
    params = {
        'countryIsoCode': pais_codigo,
        'languageIsoCode': pais_codigo,
        'validFrom': f"{year}-01-01",
        'validTo':   f"{year}-12-31",
    }
    subdiv = subdiv_map.get(region_code or '')
    if subdiv:
        params['subdivisionCode'] = subdiv

    result = []
    for item in _get('PublicHolidays', params):
        try:
            result.append({
                'fecha':      date.fromisoformat(item['startDate']),
                'name':       _name(item),
                'nationwide': item.get('nationwide', True),
                'scope':      item.get('regionalScope', 'National'),
            })
        except Exception:
            continue
    return result


def expand_periods(periods: list[dict]) -> set[date]:
    """Expands [{start, end}] → set of individual dates."""
    days: set[date] = set()
    for p in periods:
        d = p['start']
        while d <= p['end']:
            days.add(d)
            d += timedelta(days=1)
    return days
