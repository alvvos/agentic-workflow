"""
Agenda cultural — fuentes municipales españolas abiertas.
Sin API key. Cobertura parcial (crece por ciudad).

Madrid: datos.madrid.es — agenda de actividades y eventos
"""
import requests
from datetime import date
from typing import Optional

_TIMEOUT = 15

# ciudad → fuente open data
_SOURCES: dict[str, dict] = {
    'Madrid': {
        'url':    'https://datos.madrid.es/egob/catalogo/206974-0-agenda-actividades-eventos.json',
        'format': 'madrid_egob',
    },
}


def _parse_madrid_egob(data: dict, date_from: date, date_to: date) -> list[dict]:
    events = []
    for item in data.get('@graph', []):
        try:
            dtstart = (item.get('dtstart') or '')[:10]
            if not dtstart:
                continue
            ev_date = date.fromisoformat(dtstart)
            if not (date_from <= ev_date <= date_to):
                continue
            events.append({
                'fecha':     ev_date,
                'titulo':    item.get('title', ''),
                'categoria': item.get('event-location', ''),
                'score':     30,
                'source_key': f"madrid_egob:{item.get('@id', dtstart)}",
            })
        except Exception:
            continue
    return events


def fetch_agenda_ciudad(
    ciudad: str,
    date_from: date,
    date_to: date,
) -> list[dict]:
    """
    Descarga eventos culturales municipales para la ciudad indicada.
    Retorna [{fecha, titulo, categoria, score, source_key}].
    """
    source = _SOURCES.get(ciudad)
    if not source:
        return []
    try:
        r = requests.get(source['url'], timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    if source['format'] == 'madrid_egob':
        return _parse_madrid_egob(data, date_from, date_to)
    return []
