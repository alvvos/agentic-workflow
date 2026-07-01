"""
Ticketmaster Discovery API.
Registro gratuito: https://developer.ticketmaster.com
Free tier: 5 000 req/día. Set TICKETMASTER_KEY en .env.
Sin key → degradación graceful (devuelve listas vacías).
"""

import os
import re
from collections import Counter
from datetime import date

import requests
from dotenv import load_dotenv

load_dotenv()

_BASE = "https://app.ticketmaster.com/discovery/v2"
_RADIUS = "10"  # km alrededor de la ubicación
_PAGE_SIZE = 200
_MAX_PAGES = 5  # 1 000 eventos máx por llamada
_TIMEOUT = 20

# Segment IDs de Ticketmaster
_SEG_SPORTS = "KZFzniwnSyZfZ7v7nE"
_SEG_MUSIC = "KZFzniwnSyZfZ7v7nJ"
_SEG_ARTS = "KZFzniwnSyZfZ7v7na"
_SEG_FAMILY = "KZFzniwnSyZfZ7v7n1"

# Mapeo segment → categoría interna
_SEG_TO_CAT = {
    _SEG_SPORTS: "deportivo",
    _SEG_MUSIC: "concierto",
    _SEG_ARTS: "festival",
    _SEG_FAMILY: "festival",
}


def _key() -> str:
    return os.getenv("TICKETMASTER_KEY", "")


def fetch_events_raw(lat: float, lon: float, date_from: date, date_to: date) -> list[dict]:
    """
    Descarga todos los eventos en radio _RADIUS km para el rango de fechas.
    Retorna lista de dicts crudos de la API de Ticketmaster.
    """
    api_key = _key()
    if not api_key:
        return []

    all_events: list[dict] = []
    for page in range(_MAX_PAGES):
        params = {
            "apikey": api_key,
            "latlong": f"{lat},{lon}",
            "radius": _RADIUS,
            "unit": "km",
            "startDateTime": date_from.isoformat() + "T00:00:00Z",
            "endDateTime": date_to.isoformat() + "T23:59:59Z",
            "size": _PAGE_SIZE,
            "sort": "date,asc",
            "page": page,
        }
        try:
            r = requests.get(f"{_BASE}/events.json", params=params, timeout=_TIMEOUT)
            if r.status_code == 429:
                break
            r.raise_for_status()
            data = r.json()
        except Exception:
            break

        events = data.get("_embedded", {}).get("events", [])
        all_events.extend(events)

        page_info = data.get("page", {})
        total_pages = page_info.get("totalPages", 1)
        if page + 1 >= _MAX_PAGES and total_pages > _MAX_PAGES:
            import warnings

            warnings.warn(
                f"Ticketmaster: truncado a {_MAX_PAGES * _PAGE_SIZE} eventos "
                f"({total_pages} páginas disponibles). Aumentar _MAX_PAGES si la cobertura es insuficiente.",
                stacklevel=2,
            )
        if page + 1 >= total_pages:
            break

    return all_events


def events_to_daily_scores(events: list[dict]) -> dict[date, dict]:
    """
    Agrega eventos crudos en scores diarios por categoría.
    Retorna {date: {deportivo: int, concierto: int, festival: int}}.
    """
    daily: dict[date, dict] = {}

    for ev in events:
        local_date = ev.get("dates", {}).get("start", {}).get("localDate")
        if not local_date:
            continue
        try:
            ev_date = date.fromisoformat(local_date)
        except Exception:
            continue

        # Clasificar por segment
        segment_id = ""
        try:
            segment_id = ev["classifications"][0]["segment"]["id"]
        except (KeyError, IndexError, TypeError):
            pass
        category = _SEG_TO_CAT.get(segment_id, "festival")

        # Score proxy: usa priceRange si está disponible
        score = 40
        try:
            max_price = (ev.get("priceRanges") or [{}])[0].get("max") or 0
            if max_price > 150:
                score = 95
            elif max_price > 80:
                score = 75
            elif max_price > 30:
                score = 55
        except Exception:
            pass

        if ev_date not in daily:
            daily[ev_date] = {"deportivo": 0, "concierto": 0, "festival": 0}
        daily[ev_date][category] = max(daily[ev_date][category], score)

    return daily


_VIP_RE = re.compile(
    r"(?:\s*[\|:]\s*|\s+)(VIP|Package[s]?|Paquete[s]?|Upgrade|M&G|Meet\s*&?\s*Greet)\b.*",
    re.IGNORECASE,
)
_ATTRACTION_THRESHOLD = 7  # mismo nombre >= N veces → atracción permanente, descartar


def _normalize_title(name: str) -> str:
    return _VIP_RE.sub("", name).strip()


def events_to_raw_rows(events: list[dict], location_uuid: str) -> list[dict]:
    """
    Convierte eventos crudos de Ticketmaster al formato de store_calendario_org.

    Filtros aplicados:
    - Atracciones permanentes: mismo nombre > _ATTRACTION_THRESHOLD veces → descartado.
    - Duplicados VIP/paquetes: normaliza el nombre y mantiene una fila por (título, fecha).
    """
    # Primera pasada: construir filas con título normalizado
    pre: list[dict] = []
    for ev in events:
        local_date = ev.get("dates", {}).get("start", {}).get("localDate")
        if not local_date:
            continue
        try:
            ev_date = date.fromisoformat(local_date)
        except Exception:
            continue

        segment_id = ""
        try:
            segment_id = ev["classifications"][0]["segment"]["id"]
        except (KeyError, IndexError, TypeError):
            pass
        category = _SEG_TO_CAT.get(segment_id, "festival")

        titulo = _normalize_title(ev.get("name", ""))
        venue_list = ev.get("_embedded", {}).get("venues") or [{}]
        venue = venue_list[0].get("name", "") if venue_list else ""

        pre.append(
            {
                "_titulo_norm": titulo,
                "location_uuid": location_uuid,
                "evento_key": f"tm_{category}",
                "fecha_inicio": ev_date,
                "fecha_fin": ev_date,
                "fuente": "ticketmaster",
                "source_key": f"{location_uuid}:tm:{ev.get('id', ev_date)}",
                "metadata": {
                    "titulo": titulo,
                    "venue": venue,
                    "segment": segment_id,
                    "url": ev.get("url", ""),
                },
            }
        )

    # Detectar atracciones permanentes: mismo nombre aparece más de N veces
    name_count = Counter(r["_titulo_norm"] for r in pre)
    attractions = {name for name, n in name_count.items() if n >= _ATTRACTION_THRESHOLD}

    # Segunda pasada: deduplicar VIP y eliminar atracciones
    seen: set[tuple] = set()
    rows: list[dict] = []
    for r in pre:
        titulo = r.pop("_titulo_norm")
        if titulo in attractions:
            continue
        key = (titulo, r["fecha_inicio"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(r)

    return rows


def sync(ubicacion: dict, cfg: dict, date_from: date, date_to: date) -> tuple[dict, list]:
    if not _key():
        return {}, []
    raw = fetch_events_raw(ubicacion["lat"], ubicacion["lon"], date_from, date_to)
    scores = events_to_daily_scores(raw)
    rows = events_to_raw_rows(raw, ubicacion["ubicacion_id"])
    daily = {
        d: {
            "ev_rank_deportivo": cats.get("deportivo", 0),
            "ev_rank_concierto": cats.get("concierto", 0),
            "ev_rank_festival": cats.get("festival", 0),
        }
        for d, cats in scores.items()
        if date_from <= d <= date_to
    }
    return daily, rows
