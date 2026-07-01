"""
TheSportsDB — partidos deportivos por liga y ciudad.
API v1 gratuita, sin API key: https://www.thesportsdb.com/api/v1/json/3/

Endpoints usados:
  eventsseason.php   → fixtures completos de temporada (histórico + programados)
  eventsnextleague.php → próximos 15 partidos por liga (tiempo real, futuros)

Criterio de ciudad: primero strVenue/_VENUE_TO_CITY, después nombre del equipo.
Solo partidos en casa cuentan con score completo (el estadio está en la ciudad).
Partidos fuera reducen el score (efecto pantallas/bares, no estadio).
"""

import time
from datetime import date
from typing import Optional

import requests

_BASE = "https://www.thesportsdb.com/api/v1/json/3"
_TIMEOUT = 15
_DELAY = 1.2
_RETRIES = 2

# Caché de temporadas: {(league_id, season): list[dict]}
_season_cache: dict[tuple, list] = {}

_LEAGUES: dict[str, list[tuple]] = {
    "ES": [
        ("LaLiga", "4335"),
        ("LaLiga 2", "4336"),
        ("Copa del Rey", "4337"),
        ("Supercopa de España", "5104"),
    ],
    "MX": [
        ("Liga MX", "4350"),
        ("Liga de Expansión", "4351"),
    ],
    "EU": [
        ("UEFA Champions", "4480"),
        ("UEFA Europa", "4481"),
        ("UEFA Conference", "4966"),
    ],
}

# Equipos asociados a cada ciudad (matching parcial en minúsculas)
_CITY_TEAMS: dict[str, list[str]] = {
    "madrid": ["real madrid", "atlético", "atletico madrid", "getafe", "rayo vallecano", "leganés"],
    "barcelona": ["fc barcelona", "barça", "rcd espanyol", "espanyol"],
    "málaga": ["málaga cf", "malaga"],
    "malaga": ["málaga cf", "malaga"],
    "sevilla": ["sevilla fc", "real betis", "betis"],
    "valencia": ["valencia cf", "villarreal", "levante"],
    "bilbao": ["athletic club", "athletic bilbao"],
    "san sebastián": ["real sociedad"],
    "san sebastian": ["real sociedad"],
    "pamplona": ["osasuna", "ca osasuna"],
    "zaragoza": ["real zaragoza"],
    "ciudad de méxico": ["club américa", "america", "cruz azul", "pumas unam", "atlas"],
    "monterrey": ["cf monterrey", "tigres uanl", "tigres"],
    "guadalajara": ["chivas", "guadalajara", "atlas fc"],
}

# Sede → ciudad (matching parcial en minúsculas)
_VENUE_TO_CITY: dict[str, str] = {
    "santiago bernabéu": "madrid",
    "santiago bernabeu": "madrid",
    "estadio metropolitano": "madrid",
    "coliseum": "madrid",
    "estadio de vallecas": "madrid",
    "butarque": "madrid",
    "camp nou": "barcelona",
    "estadi olímpic": "barcelona",
    "estadi olimpic": "barcelona",
    "la rosaleda": "malaga",
    "mestalla": "valencia",
    "estadio de la cerámica": "valencia",
    "estadio de la ceramica": "valencia",
    "san mamés": "bilbao",
    "san mames": "bilbao",
    "reale arena": "san sebastian",
    "anoeta": "san sebastian",
    "el sadar": "pamplona",
    "ramón sánchez-pizjuán": "sevilla",
    "ramon sanchez pizjuan": "sevilla",
    "estadio benito villamarín": "sevilla",
    "estadio benito villamarin": "sevilla",
    "la romareda": "zaragoza",
    "estadio azteca": "ciudad de méxico",
    "estadio bbva": "monterrey",
    "estadio akron": "guadalajara",
}

_SCORE_LIGA = 55
_SCORE_COPA = 65
_SCORE_CHAMPIONS = 85
_SCORE_DERBY = 80
_AWAY_FACTOR = 0.4  # partidos fuera → 40% del score (efecto bares/pantallas)


def _fetch_season(league_id: str, season: str) -> list[dict]:
    key = (league_id, season)
    if key in _season_cache:
        return _season_cache[key]
    for attempt in range(_RETRIES):
        try:
            r = requests.get(
                f"{_BASE}/eventsseason.php",
                params={"id": league_id, "s": season},
                timeout=_TIMEOUT,
            )
            if r.status_code == 429:
                time.sleep(_DELAY * (attempt + 3))
                continue
            r.raise_for_status()
            data = r.json().get("events") or []
            if data:
                _season_cache[key] = data
            time.sleep(_DELAY)
            return data
        except Exception:
            time.sleep(_DELAY)
    return []


def _fetch_next_league(league_id: str) -> list[dict]:
    """Próximos 15 partidos de una liga (tiempo real, sin depender de temporada)."""
    key = (league_id, "__next__")
    if key in _season_cache:
        return _season_cache[key]
    try:
        r = requests.get(
            f"{_BASE}/eventsnextleague.php",
            params={"id": league_id},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json().get("events") or []
        if data:
            _season_cache[key] = data
        time.sleep(_DELAY)
        return data
    except Exception:
        return []


def _fetch_past_league(league_id: str) -> list[dict]:
    """Últimos 15 partidos de una liga (complementa huecos recientes del season endpoint)."""
    key = (league_id, "__past__")
    if key in _season_cache:
        return _season_cache[key]
    try:
        r = requests.get(
            f"{_BASE}/eventspastleague.php",
            params={"id": league_id},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json().get("events") or []
        if data:
            _season_cache[key] = data
        time.sleep(_DELAY)
        return data
    except Exception:
        return []


def _seasons_for(date_from: date, date_to: date) -> list[str]:
    # No pedir temporadas futuras que aún no tienen fixtures en la API.
    # cap_year = año actual; la temporada "cap_year/cap_year+1" puede existir
    # si ya empezó (ej. agosto), pero la del año siguiente es siempre vacía.
    cap_year = date.today().year
    seasons: set[str] = set()
    for yr in range(date_from.year, min(date_to.year, cap_year) + 1):
        seasons.add(f"{yr}-{yr+1}")
        seasons.add(str(yr))
    return list(seasons)


def _city_team_names(ciudad: str) -> set[str]:
    ciudad_l = ciudad.lower()
    for key, teams in _CITY_TEAMS.items():
        if key in ciudad_l or ciudad_l in key:
            return set(teams)
    return set()


def _venue_city(ev: dict) -> Optional[str]:
    """Extrae la ciudad de la sede del evento, si la conocemos."""
    venue_raw = (ev.get("strVenue") or "").lower().strip()
    city_raw = (ev.get("strCity") or "").lower().strip()

    # Primero intentar con el nombre de la sede (más preciso)
    for venue_key, city in _VENUE_TO_CITY.items():
        if venue_key in venue_raw:
            return city

    # Fallback: campo strCity de la API
    if city_raw:
        return city_raw

    return None


def prewarm(paises: set[str], date_from: date, date_to: date) -> None:
    """
    Pre-carga en _season_cache todas las temporadas de las ligas de 'paises'.
    Llamar antes del loop de ubicaciones: cada ciudad solo filtra sin repetir HTTP.
    """
    seasons = _seasons_for(date_from, date_to)
    for pais in paises | {"EU"}:
        for _, league_id in _LEAGUES.get(pais, []):
            for season in seasons:
                _fetch_season(league_id, season)
            _fetch_next_league(league_id)
            _fetch_past_league(league_id)


def get_events_for_city(
    ciudad: str,
    pais_codigo: str,
    date_from: date,
    date_to: date,
) -> list[dict]:
    """
    Retorna partidos que afectan a 'ciudad' entre date_from y date_to.

    Criterio de ciudad (en orden de preferencia):
      1. Sede conocida en _VENUE_TO_CITY (el partido se juega físicamente aquí)
      2. strCity de la API
      3. El equipo local es de la ciudad (home team match)

    Score:
      - Partido en casa (equipo local + sede en la ciudad): score completo
      - Partido fuera (equipo visitante de la ciudad): score * _AWAY_FACTOR

    Cada dict devuelto incluye: fecha, evento, liga, score, sede, ciudad_sede,
    es_local, fuente, source_key.
    """
    team_names = _city_team_names(ciudad)
    ciudad_l = ciudad.lower()

    leagues = _LEAGUES.get(pais_codigo, []) + _LEAGUES["EU"]
    seasons = _seasons_for(date_from, date_to)

    seen: set[str] = set()
    results: list[dict] = []

    def _process_events(events: list[dict]) -> None:
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

            home = (ev.get("strHomeTeam") or "").lower()
            away = (ev.get("strAwayTeam") or "").lower()

            home_match = bool(team_names) and any(t in home for t in team_names)
            away_match = bool(team_names) and any(t in away for t in team_names)

            # Determinar ciudad de la sede
            vc = _venue_city(ev)

            # El partido afecta a la ciudad si:
            # a) la sede está en la ciudad, o
            # b) el equipo local o visitante es de la ciudad
            venue_in_city = vc is not None and (vc == ciudad_l or ciudad_l in vc or vc in ciudad_l)
            if not (venue_in_city or home_match or away_match):
                continue

            dedup_key = f"{league_id}:{ev.get('idEvent', ev_date_str)}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            is_euro = league_id in ("4480", "4481", "4966")
            is_copa = league_id in ("4337", "5104")
            both_local = home_match and away_match

            if both_local:
                base_score = _SCORE_DERBY
            elif is_euro:
                base_score = _SCORE_CHAMPIONS
            elif is_copa:
                base_score = _SCORE_COPA
            else:
                base_score = _SCORE_LIGA

            # Partido en casa → score completo. Fuera → reducido.
            # Si la sede está en la ciudad, siempre es "local" a efectos de impacto.
            es_local = venue_in_city or home_match
            score = base_score if es_local else int(base_score * _AWAY_FACTOR)

            results.append(
                {
                    "fecha": ev_date,
                    "evento": f"{ev.get('strHomeTeam')} vs {ev.get('strAwayTeam')}",
                    "liga": league_name,
                    "score": score,
                    "sede": ev.get("strVenue") or "",
                    "ciudad_sede": vc or "",
                    "es_local": es_local,
                    "fuente": "thesportsdb",
                    "source_key": dedup_key,
                }
            )

    for league_name, league_id in leagues:
        # 1. Temporadas históricas/programadas
        for season in seasons:
            _process_events(_fetch_season(league_id, season))

        # 2. Próximos fixtures en tiempo real (cubre huecos de temporada futura)
        _process_events(_fetch_next_league(league_id))

        # 3. Partidos recientes (por si el season endpoint tiene huecos)
        _process_events(_fetch_past_league(league_id))

    return results


def sync(ubicacion: dict, cfg: dict, date_from: date, date_to: date) -> tuple[dict, list]:
    ciudad = ubicacion.get("city", "")
    if not ciudad:
        return {}, []
    ubicacion_id = ubicacion["ubicacion_id"]
    pais_codigo = ubicacion["pais_codigo"]
    events = get_events_for_city(ciudad, pais_codigo, date_from, date_to)
    daily: dict[date, dict] = {}
    raw_rows: list[dict] = []
    for ev in events:
        d = ev["fecha"]
        if d not in daily:
            daily[d] = {"ev_rank_deportivo": 0}
        daily[d]["ev_rank_deportivo"] = max(daily[d]["ev_rank_deportivo"], ev["score"])
        raw_rows.append(
            {
                "evento_key": "partido_deportivo",
                "fecha_inicio": d,
                "fecha_fin": d,
                "fuente": ev["fuente"],
                "source_key": f"tsdb:{ubicacion_id}:{ev['source_key']}",
                "metadata": {
                    "evento": ev["evento"],
                    "liga": ev["liga"],
                    "sede": ev.get("sede", ""),
                    "ciudad_sede": ev.get("ciudad_sede", ""),
                    "es_local": ev.get("es_local", True),
                },
            }
        )
    return daily, raw_rows
