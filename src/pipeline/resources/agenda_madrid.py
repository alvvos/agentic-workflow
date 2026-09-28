"""
Recurso dlt para la Agenda Cultural de Madrid (datos.madrid.es).

Fuente: https://datos.madrid.es/egob/catalogo/206974-0-agenda-eventos-culturales-100.json
Formato JSON-LD: array en "@graph", cada evento con dtstart / dtend.

Para cada día en [date_from, date_to] cuenta cuántos eventos están activos
(dtstart.date ≤ día ≤ dtend.date) y escribe el resultado en valores_señales
como señal_id="n_eventos_culturales_dia".
Solo se escriben fechas con count > 0; los días sin eventos no generan fila
(fill_gaps="zero" en la definición de la señal cubre la consulta).

Solo procesa ubicaciones cuyo campo city sea "Madrid".
"""

from __future__ import annotations

from datetime import date, timedelta

import dlt
import requests

_URL = "https://datos.madrid.es/egob/catalogo/206974-0-agenda-eventos-culturales-100.json"
_SIGNAL = "n_eventos_culturales_dia"
_TIMEOUT = 20


def _fetch_events() -> list[dict]:
    try:
        r = requests.get(_URL, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return data.get("@graph") or data.get("graph") or (data if isinstance(data, list) else [])
    except Exception:
        return []


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _count_by_day(events: list[dict], date_from: date, date_to: date) -> dict[date, int]:
    counts: dict[date, int] = {}
    for ev in events:
        start = _parse_date(ev.get("dtstart"))
        end = _parse_date(ev.get("dtend"))
        if start is None or end is None:
            continue
        # Clamp to requested window
        window_start = max(start, date_from)
        window_end = min(end, date_to)
        if window_start > window_end:
            continue
        d = window_start
        while d <= window_end:
            counts[d] = counts.get(d, 0) + 1
            d += timedelta(days=1)
    return counts


@dlt.resource(
    name="señal", write_disposition="merge", primary_key=["fecha", "ubicacion_id", "señal_id"]
)
def _resource(ubicaciones: list[dict], cfg: dict, date_from: date, date_to: date):
    madrid_locs = [u for u in ubicaciones if (u.get("city") or "").strip() == "Madrid"]
    if not madrid_locs:
        return

    events = _fetch_events()
    if not events:
        return

    counts = _count_by_day(events, date_from, date_to)
    if not counts:
        return

    for d, n in counts.items():
        for ubi in madrid_locs:
            yield {
                "fecha": d.isoformat(),
                "ubicacion_id": ubi["ubicacion_id"],
                "señal_id": _SIGNAL,
                "valor": float(n),
            }


@dlt.source
def source(ubicaciones: list[dict], cfg: dict, date_from: date, date_to: date):
    yield _resource(ubicaciones, cfg, date_from, date_to)
