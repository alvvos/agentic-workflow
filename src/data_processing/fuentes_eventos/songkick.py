"""
Songkick API — conciertos y festivales por ubicación geográfica.
Registro gratuito: https://www.songkick.com/api_key_requests/new
Free tier: ~50 req/min. Set SONGKICK_KEY en .env.
Sin key → degradación graceful (devuelve listas vacías).
"""
import os
import requests
from datetime import date
from dotenv import load_dotenv

load_dotenv()

_BASE      = "https://api.songkick.com/api/3.0"
_RADIUS_KM = 10
_PER_PAGE  = 50
_MAX_PAGES = 10
_TIMEOUT   = 20


def _key() -> str:
    return os.getenv('SONGKICK_KEY', '')


def fetch_events_raw(lat: float, lon: float, date_from: date, date_to: date) -> list[dict]:
    """
    Descarga todos los eventos en radio _RADIUS_KM km para el rango de fechas.
    Retorna lista de dicts crudos de la API de Songkick.
    """
    api_key = _key()
    if not api_key:
        return []

    all_events: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        params = {
            'apikey':   api_key,
            'location': f"geo:{lat},{lon}",
            'radius':   _RADIUS_KM,
            'min_date': date_from.isoformat(),
            'max_date': date_to.isoformat(),
            'per_page': _PER_PAGE,
            'page':     page,
        }
        try:
            r = requests.get(f"{_BASE}/events.json", params=params, timeout=_TIMEOUT)
            if r.status_code in (403, 429):
                break
            r.raise_for_status()
            data = r.json()
        except Exception:
            break

        results  = data.get('resultsPage', {})
        events   = results.get('results', {}).get('event') or []
        if not events:
            break
        all_events.extend(events)

        total = results.get('totalEntries', 0)
        if len(all_events) >= total:
            break

    return all_events


def _score_from_event(ev: dict) -> int:
    """
    Score 0-100 por evento.
    Usa capacidad del venue si está disponible; fallback a tipo de evento.
    """
    capacity = (ev.get('venue') or {}).get('capacity') or 0
    if capacity > 10_000:
        return 95
    if capacity > 5_000:
        return 80
    if capacity > 1_000:
        return 65
    if capacity > 0:
        return 50
    return 65 if ev.get('type') == 'Festival' else 45


def events_to_daily_scores(events: list[dict]) -> dict[date, dict]:
    """
    Agrega eventos crudos en scores diarios por categoría.
    Retorna {date: {concierto: int, festival: int}}.
    """
    daily: dict[date, dict] = {}
    for ev in events:
        start_date = (ev.get('start') or {}).get('date')
        if not start_date:
            continue
        try:
            ev_date = date.fromisoformat(start_date)
        except Exception:
            continue

        cat   = 'festival' if ev.get('type') == 'Festival' else 'concierto'
        score = _score_from_event(ev)

        if ev_date not in daily:
            daily[ev_date] = {'concierto': 0, 'festival': 0}
        daily[ev_date][cat] = max(daily[ev_date][cat], score)

    return daily


def events_to_raw_rows(events: list[dict], location_uuid: str) -> list[dict]:
    """
    Convierte eventos crudos de Songkick al formato de store_calendario_org.
    """
    rows = []
    for ev in events:
        start   = ev.get('start') or {}
        start_d = start.get('date')
        if not start_d:
            continue
        try:
            ev_date = date.fromisoformat(start_d)
        except Exception:
            continue

        ev_id = ev.get('id', '')
        cat   = 'festival' if ev.get('type') == 'Festival' else 'concierto'
        venue = ev.get('venue') or {}
        perfs = ev.get('performance') or []
        headliner = next(
            (p['displayName'] for p in perfs if p.get('billing') == 'headline'),
            perfs[0].get('displayName', '') if perfs else '',
        )
        end_d = (ev.get('end') or {}).get('date') or start_d

        rows.append({
            'location_uuid': location_uuid,
            'evento_key':    cat,
            'fecha_inicio':  ev_date,
            'fecha_fin':     date.fromisoformat(end_d),
            'fuente':        'songkick',
            'source_key':    f"sk:{location_uuid}:{ev_id}",
            'metadata': {
                'nombre':       ev.get('displayName', ''),
                'artista':      headliner,
                'n_artistas':   len(perfs),
                'tipo':         ev.get('type', 'Concert'),
                'venue_nombre': venue.get('displayName', ''),
                'venue_ciudad': (venue.get('city') or {}).get('displayName', ''),
                'venue_lat':    venue.get('lat'),
                'venue_lon':    venue.get('lng'),
                'aforo':        venue.get('capacity'),
                'hora_inicio':  start.get('time'),
                'url':          ev.get('uri', ''),
            },
        })
    return rows
