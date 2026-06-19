"""
Meetup GraphQL API — eventos de comunidad por ubicación geográfica.
Requiere MEETUP_TOKEN (Bearer token OAuth2) en .env.
Sin token → degradación graceful (devuelve listas vacías).

Obtener token: https://www.meetup.com/api/oauth/list/
Scopes necesarios: basic, event_management (read-only con basic es suficiente)
"""
import os
import requests
from datetime import date
from dotenv import load_dotenv

load_dotenv()

_GQL_URL   = "https://api.meetup.com/gql"
_RADIUS_KM = 10
_PER_PAGE  = 50
_TIMEOUT   = 20

_QUERY = """
query SearchEvents($filter: KeywordSearchFilter!, $input: ConnectionInput) {
  keywordSearch(filter: $filter, input: $input) {
    pageInfo { hasNextPage endCursor }
    count
    edges {
      node {
        ... on Event {
          id
          title
          dateTime
          endTime
          going
          description
          eventUrl
          venue { id name lat lon city }
          group { id name urlname category { name } }
        }
      }
    }
  }
}
"""

# Score base por categoría Meetup — refleja impacto de tráfico peatonal en retail
_CAT_BASE_SCORE: dict[str, int] = {
    'Fashion & Beauty':   65,
    'Music':              65,
    'Tech':               55,
    'Food & Drink':       55,
    'Arts & Culture':     55,
    'Career & Business':  50,
    'Sports & Fitness':   50,
    'Social':             50,
    'Film':               50,
    'Dancing':            55,
    'Language & Culture': 50,
    'LGBTQ+':             50,
    'Outdoors & Adventure': 45,
    'Parents & Family':   45,
    'Health & Wellbeing': 45,
    'Movements':          45,
    'Learning':           45,
    'Photography':        40,
    'Writing':            40,
    'Games':              40,
    'Book Clubs':         35,
    'Beliefs':            35,
}
_DEFAULT_CAT_SCORE = 40


def _token() -> str:
    return os.getenv('MEETUP_TOKEN', '')


def fetch_events_raw(lat: float, lon: float, date_from: date, date_to: date) -> list[dict]:
    """
    Descarga eventos cercanos mediante Meetup GraphQL con paginación por cursor.
    Retorna lista de nodos Event (dicts).
    """
    token = _token()
    if not token:
        return []

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type':  'application/json',
    }
    all_events: list[dict] = []
    cursor = None

    for _ in range(20):  # max 20 páginas × 50 = 1 000 eventos
        variables = {
            'filter': {
                'lat':            lat,
                'lon':            lon,
                'radius':         _RADIUS_KM,
                'startDateRange': f"{date_from.isoformat()}T00:00:00",
                'endDateRange':   f"{date_to.isoformat()}T23:59:59",
            },
            'input': {'first': _PER_PAGE, 'after': cursor},
        }
        try:
            r = requests.post(
                _GQL_URL,
                json={'query': _QUERY, 'variables': variables},
                headers=headers,
                timeout=_TIMEOUT,
            )
            if r.status_code in (401, 403, 429):
                break
            r.raise_for_status()
            data = r.json()
        except Exception:
            break

        search = (data.get('data') or {}).get('keywordSearch') or {}
        edges  = search.get('edges') or []
        for edge in edges:
            node = (edge.get('node') or {})
            if node.get('id'):
                all_events.append(node)

        page_info = search.get('pageInfo') or {}
        if not page_info.get('hasNextPage'):
            break
        cursor = page_info.get('endCursor')

    return all_events


def events_to_daily_scores(events: list[dict]) -> dict[date, dict]:
    """
    Retorna {date: {comunidad: int}}.
    Score combinado de going (RSVPs) y categoría del grupo.
    """
    daily: dict[date, dict] = {}
    for ev in events:
        dt_str = (ev.get('dateTime') or '')[:10]
        if not dt_str:
            continue
        try:
            ev_date = date.fromisoformat(dt_str)
        except Exception:
            continue

        group    = ev.get('group') or {}
        cat_name = (group.get('category') or {}).get('name', '')
        base     = _CAT_BASE_SCORE.get(cat_name, _DEFAULT_CAT_SCORE)
        going    = ev.get('going') or 0

        if   going > 200: score = max(base, 85)
        elif going > 100: score = max(base, 70)
        elif going > 50:  score = max(base, 55)
        elif going > 10:  score = max(base, 40)
        else:             score = base

        if ev_date not in daily:
            daily[ev_date] = {'comunidad': 0}
        daily[ev_date]['comunidad'] = max(daily[ev_date]['comunidad'], score)

    return daily


def events_to_raw_rows(events: list[dict], location_uuid: str) -> list[dict]:
    """
    Convierte eventos de Meetup al formato de store_calendario_org.
    """
    rows = []
    for ev in events:
        dt_str = ev.get('dateTime') or ''
        if not dt_str:
            continue
        try:
            ev_date = date.fromisoformat(dt_str[:10])
        except Exception:
            continue

        end_str  = ev.get('endTime') or ''
        ev_id    = ev.get('id', '')
        venue    = ev.get('venue') or {}
        group    = ev.get('group') or {}
        cat_name = (group.get('category') or {}).get('name', '')
        desc     = ev.get('description') or ''

        try:
            end_date = date.fromisoformat(end_str[:10]) if end_str else ev_date
        except Exception:
            end_date = ev_date

        rows.append({
            'location_uuid': location_uuid,
            'evento_key':    'comunidad',
            'fecha_inicio':  ev_date,
            'fecha_fin':     end_date,
            'fuente':        'meetup',
            'source_key':    f"meetup:{location_uuid}:{ev_id}",
            'metadata': {
                'nombre':       ev.get('title', ''),
                'grupo':        group.get('name', ''),
                'grupo_url':    group.get('urlname', ''),
                'categoria':    cat_name,
                'going':        ev.get('going', 0),
                'venue_nombre': venue.get('name', ''),
                'venue_ciudad': venue.get('city', ''),
                'venue_lat':    venue.get('lat'),
                'venue_lon':    venue.get('lon'),
                'hora_inicio':  dt_str[11:16] if len(dt_str) > 10 else None,
                'hora_fin':     end_str[11:16] if len(end_str) > 10 else None,
                'descripcion':  desc[:500] if desc else None,
                'url':          ev.get('eventUrl', ''),
            },
        })
    return rows
