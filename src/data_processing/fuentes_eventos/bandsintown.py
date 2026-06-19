"""
Bandsintown API v3.1 — conciertos por ubicación geográfica.
Registro: https://artists.bandsintown.com/support/public-api
Set BANDSINTOWN_KEY en .env.
Sin key → degradación graceful (devuelve listas vacías).
"""
import os
import requests
from datetime import date
from dotenv import load_dotenv

load_dotenv()

_BASE      = "https://rest.bandsintown.com/v3.1"
_RADIUS_KM = 10
_PER_PAGE  = 50
_MAX_PAGES = 10
_TIMEOUT   = 20


def _key() -> str:
    return os.getenv('BANDSINTOWN_KEY', '')


def fetch_events_raw(
    lat: float, lon: float, date_from: date, date_to: date,
    city: str = '',
) -> list[dict]:
    """
    Busca eventos por coordenadas (primario) o nombre de ciudad (fallback).
    Retorna lista de eventos crudos de Bandsintown.
    """
    app_id = _key()
    if not app_id:
        return []

    location = f"{lat},{lon}" if lat and lon else city
    if not location:
        return []

    all_events: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        params = {
            'app_id':     app_id,
            'location':   location,
            'radius':     _RADIUS_KM,
            'unit':       'km',
            'start_date': date_from.isoformat(),
            'end_date':   date_to.isoformat(),
            'per_page':   _PER_PAGE,
            'page':       page,
        }
        try:
            r = requests.get(f"{_BASE}/events/search", params=params, timeout=_TIMEOUT)
            if r.status_code in (401, 403, 429):
                break
            r.raise_for_status()
            data = r.json()
        except Exception:
            break

        events = data if isinstance(data, list) else (data.get('data') or [])
        if not events:
            break
        all_events.extend(events)
        if len(events) < _PER_PAGE:
            break

    return all_events


def events_to_daily_scores(events: list[dict]) -> dict[date, dict]:
    """
    Retorna {date: {concierto: int}}.
    Score basado en rsvp_count del evento.
    """
    daily: dict[date, dict] = {}
    for ev in events:
        dt_str = (ev.get('datetime') or '')[:10]
        if not dt_str:
            continue
        try:
            ev_date = date.fromisoformat(dt_str)
        except Exception:
            continue

        rsvp = ev.get('rsvp_count') or 0
        if   rsvp > 1_000: score = 90
        elif rsvp > 500:   score = 75
        elif rsvp > 100:   score = 55
        elif rsvp > 0:     score = 40
        else:              score = 30

        if ev_date not in daily:
            daily[ev_date] = {'concierto': 0}
        daily[ev_date]['concierto'] = max(daily[ev_date]['concierto'], score)

    return daily


def events_to_raw_rows(events: list[dict], location_uuid: str) -> list[dict]:
    """
    Convierte eventos crudos de Bandsintown al formato de store_calendario_org.
    """
    rows = []
    for ev in events:
        dt_str = ev.get('datetime') or ''
        if not dt_str:
            continue
        try:
            ev_date = date.fromisoformat(dt_str[:10])
        except Exception:
            continue

        ev_id   = ev.get('id', '')
        venue   = ev.get('venue') or {}
        lineup  = ev.get('lineup') or []

        rows.append({
            'location_uuid': location_uuid,
            'evento_key':    'concierto',
            'fecha_inicio':  ev_date,
            'fecha_fin':     ev_date,
            'fuente':        'bandsintown',
            'source_key':    f"bit:{location_uuid}:{ev_id}",
            'metadata': {
                'nombre':             ev.get('title') or ', '.join(lineup),
                'artistas':           lineup,
                'venue_nombre':       venue.get('name', ''),
                'venue_ciudad':       venue.get('city', ''),
                'venue_region':       venue.get('region', ''),
                'venue_pais':         venue.get('country', ''),
                'venue_lat':          venue.get('latitude'),
                'venue_lon':          venue.get('longitude'),
                'rsvp_count':         ev.get('rsvp_count', 0),
                'hora_inicio':        dt_str[11:16] if len(dt_str) > 10 else None,
                'on_sale_datetime':   ev.get('on_sale_datetime'),
                'url':                ev.get('url', ''),
                'descripcion':        (ev.get('description') or '')[:500] or None,
            },
        })
    return rows
