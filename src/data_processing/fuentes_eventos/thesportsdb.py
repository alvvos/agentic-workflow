"""
Fixtures deportivos — TheSportsDB API v1.
https://www.thesportsdb.com/api/v1/json/3/

Configuración en fuentes.config (source-level):
  ligas: {pais_codigo: [{nombre, id, tipo}]}   ligas por país + "EU" para europeas
  scores: {tipo: int, factor_visitante: float}  puntuación base por tipo de partido
  delay: float                                  segundos entre peticiones
  retries: int                                  reintentos ante 429

Configuración en config_fuentes.params (por ubicación):
  equipos: [str]   substrings del nombre de equipos de la ciudad (minúsculas)
  sedes: [str]     substrings del nombre de estadios de la ciudad (minúsculas)

Interfaz pública requerida por eventos_api:
  sync(ubicacion, cfg, date_from, date_to) -> tuple[dict[date, dict], list[dict]]
"""

import time
from datetime import date

import requests

_BASE = "https://www.thesportsdb.com/api/v1/json/3"

# Caché de temporadas en memoria — compartido entre llamadas del mismo proceso
_season_cache: dict[tuple, list] = {}


def _fetch_season(league_id: str, season: str, delay: float, retries: int) -> list[dict]:
    key = (league_id, season)
    if key in _season_cache:
        return _season_cache[key]
    for attempt in range(retries):
        try:
            r = requests.get(
                f"{_BASE}/eventsseason.php",
                params={"id": league_id, "s": season},
                timeout=15,
            )
            if r.status_code == 429:
                time.sleep(delay * (attempt + 3))
                continue
            r.raise_for_status()
            data = r.json().get("events") or []
            if data:
                _season_cache[key] = data
            time.sleep(delay)
            return data
        except Exception:
            time.sleep(delay)
    return []


def _fetch_next_league(league_id: str, delay: float) -> list[dict]:
    key = (league_id, "__next__")
    if key in _season_cache:
        return _season_cache[key]
    try:
        r = requests.get(f"{_BASE}/eventsnextleague.php", params={"id": league_id}, timeout=15)
        r.raise_for_status()
        data = r.json().get("events") or []
        if data:
            _season_cache[key] = data
        time.sleep(delay)
        return data
    except Exception:
        return []


def _fetch_past_league(league_id: str, delay: float) -> list[dict]:
    key = (league_id, "__past__")
    if key in _season_cache:
        return _season_cache[key]
    try:
        r = requests.get(f"{_BASE}/eventspastleague.php", params={"id": league_id}, timeout=15)
        r.raise_for_status()
        data = r.json().get("events") or []
        if data:
            _season_cache[key] = data
        time.sleep(delay)
        return data
    except Exception:
        return []


def _seasons_for(date_from: date, date_to: date) -> list[str]:
    cap_year = date.today().year
    seasons: set[str] = set()
    for yr in range(date_from.year, min(date_to.year, cap_year) + 1):
        seasons.add(f"{yr}-{yr+1}")
        seasons.add(str(yr))
    return list(seasons)


def sync(ubicacion: dict, cfg: dict, date_from: date, date_to: date) -> tuple[dict, list]:
    ciudad = ubicacion.get("city", "")
    if not ciudad:
        return {}, []

    ubicacion_id = ubicacion["ubicacion_id"]
    pais_codigo = ubicacion["pais_codigo"]
    delay = float(cfg.get("delay", 1.2))
    retries = int(cfg.get("retries", 2))

    ligas_cfg: dict = cfg.get("ligas", {})
    scores_cfg: dict = cfg.get("scores", {})
    equipos: list[str] = [e.lower() for e in cfg.get("equipos", [])]
    sedes: list[str] = [s.lower() for s in cfg.get("sedes", [])]

    leagues = ligas_cfg.get(pais_codigo, []) + ligas_cfg.get("EU", [])
    seasons = _seasons_for(date_from, date_to)
    ciudad_l = ciudad.lower()

    daily: dict[date, dict] = {}
    raw_rows: list[dict] = []
    seen: set[str] = set()

    def _venue_en_ciudad(ev: dict) -> bool:
        venue = (ev.get("strVenue") or "").lower()
        city = (ev.get("strCity") or "").lower()
        return (
            any(s in venue for s in sedes)
            or any(s in city for s in sedes)
            or (bool(ciudad_l) and ciudad_l in city)
        )

    def _equipo_en_ciudad(team: str) -> bool:
        team_l = team.lower()
        return any(e in team_l for e in equipos)

    def _process(events: list[dict], league_id: str, league_nombre: str, league_tipo: str) -> None:
        for ev in events:
            ev_date_str = ev.get("dateEvent") or ""
            if not ev_date_str:
                continue
            try:
                ev_date = date.fromisoformat(ev_date_str)
            except Exception:
                continue
            if not (date_from <= ev_date <= date_to):
                continue

            home = ev.get("strHomeTeam") or ""
            away = ev.get("strAwayTeam") or ""
            home_match = _equipo_en_ciudad(home)
            away_match = _equipo_en_ciudad(away)
            venue_match = _venue_en_ciudad(ev)

            if not (venue_match or home_match or away_match):
                continue

            dedup_key = f"{league_id}:{ev.get('idEvent', ev_date_str)}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            es_derby = home_match and away_match
            tipo = "derby" if es_derby else league_tipo
            base = int(scores_cfg.get(tipo, scores_cfg.get("liga", 55)))
            es_local = venue_match or home_match
            factor = float(scores_cfg.get("factor_visitante", 0.4))
            score = base if es_local else int(base * factor)

            if ev_date not in daily:
                daily[ev_date] = {"ev_rank_deportivo": 0}
            daily[ev_date]["ev_rank_deportivo"] = max(daily[ev_date]["ev_rank_deportivo"], score)

            raw_rows.append(
                {
                    "evento_key": "partido_deportivo",
                    "fecha_inicio": ev_date,
                    "fecha_fin": ev_date,
                    "fuente": "thesportsdb",
                    "source_key": f"tsdb:{ubicacion_id}:{dedup_key}",
                    "metadata": {
                        "evento": f"{home} vs {away}",
                        "liga": league_nombre,
                        "sede": ev.get("strVenue") or "",
                        "ciudad_sede": ev.get("strCity") or "",
                        "es_local": es_local,
                    },
                }
            )

    for liga in leagues:
        league_id = liga["id"]
        league_nombre = liga["nombre"]
        league_tipo = liga.get("tipo", "liga")
        for season in seasons:
            _process(
                _fetch_season(league_id, season, delay, retries),
                league_id,
                league_nombre,
                league_tipo,
            )
        _process(_fetch_next_league(league_id, delay), league_id, league_nombre, league_tipo)
        _process(_fetch_past_league(league_id, delay), league_id, league_nombre, league_tipo)

    return daily, raw_rows
