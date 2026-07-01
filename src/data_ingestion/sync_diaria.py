"""
Sincronizacion diaria de senales de contexto.

Recorre la API interna para descubrir que fuentes tiene configuradas cada ubicacion
activa, ejecuta cada handler y valida el resultado.

CLI:
  python -m src.data_ingestion.sync_diaria
  python -m src.data_ingestion.sync_diaria --location <uuid>
  python -m src.data_ingestion.sync_diaria --solo weather,open_holidays
  python -m src.data_ingestion.sync_diaria --force
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta

from src.data_ingestion._common import (
    EVENTS_DATE_FROM,
    EVENTS_HORIZON,
    WEATHER_ARCHIVE_LAG,
    WEATHER_FORECAST,
    get_active_locations,
    get_configured_locations,
    get_source_config,
    is_fresh,
    update_ev_rank_total,
    write_calendario_org,
    write_ev_features,
    write_sync_marker,
)

# ── Fuentes universales vs configuradas ──────────────────────────────────────

# Corren para TODAS las ubicaciones activas (sin config en location_source_config)
_UNIVERSAL: set[str] = {"weather", "open_holidays", "thesportsdb", "ticketmaster", "agenda_es"}

# Solo si la ubicacion tiene fila en location_source_config para ese source
_CONFIGURADAS: set[str] = {"cruceros"}

# Sources de eventos que contribuyen a ev_rank_total
_EVENT_SOURCES: set[str] = {"open_holidays", "ticketmaster", "thesportsdb", "agenda_es"}


# ── Handlers privados ─────────────────────────────────────────────────────────


def _handler_weather(
    loc: dict,
    params: dict,  # noqa: ARG001 — universales ignoran params
    max_age_hours: float,
    verbose: bool,
) -> int:
    uuid = loc["uuid"]
    if is_fresh(uuid, "weather", max_age_hours):
        if verbose:
            print(f"  [weather] {loc['nombre']}: omitido (datos < {max_age_hours:.0f}h)")
        return 0
    try:
        from src.db.queries import _cache_weather, _fetch_weather, _fetch_weather_forecast

        lat, lon = loc["lat"], loc["lon"]
        hoy = date.today()

        arch_to = hoy - timedelta(days=WEATHER_ARCHIVE_LAG)
        arch_from = date(2024, 1, 1)
        n_arch = 0
        if arch_from <= arch_to:
            df = _fetch_weather(lat, lon, str(arch_from), str(arch_to))
            if not df.empty:
                _cache_weather(uuid, df, overwrite=False)
                n_arch = len(df)

        df_fore = _fetch_weather_forecast(
            lat, lon, past_days=WEATHER_ARCHIVE_LAG, forecast_days=WEATHER_FORECAST
        )
        n_fore = 0
        if not df_fore.empty:
            _cache_weather(uuid, df_fore, overwrite=True)
            n_fore = len(df_fore)

        write_sync_marker(uuid, "weather")
        if verbose:
            print(f"  [weather] {loc['nombre']}: archivo={n_arch}d  pronostico={n_fore}d")
        return n_arch + n_fore
    except Exception as e:
        if verbose:
            print(f"  [weather] {loc['nombre']}: ERROR — {e}")
        return 0


def _handler_open_holidays(
    loc: dict,
    params: dict,  # noqa: ARG001
    max_age_hours: float,
    verbose: bool,
) -> int:
    uuid = loc["uuid"]
    if is_fresh(uuid, "open_holidays", max_age_hours):
        if verbose:
            print(f"  [open_holidays] {loc['nombre']}: omitido (datos < {max_age_hours:.0f}h)")
        return 0
    try:
        from src.data_processing.fuentes_eventos.open_holidays import (
            expand_periods,
            get_public_holidays_detail,
            get_school_holidays,
        )

        pais_codigo = loc["pais_codigo"]
        region_code = loc["region_code"]
        date_from = EVENTS_DATE_FROM
        date_to = date.today() + timedelta(days=EVENTS_HORIZON)
        years = list(range(date_from.year, date_to.year + 1))

        daily: dict[date, dict] = {}
        raw_rows: list[dict] = []

        def _slot(d: date) -> dict:
            if d not in daily:
                daily[d] = {"ev_vacaciones_escolares": 0, "ev_festivo_regional": 0}
            return daily[d]

        for year in years:
            for d in expand_periods(get_school_holidays(pais_codigo, year, region_code)):
                if date_from <= d <= date_to:
                    _slot(d)["ev_vacaciones_escolares"] = 1
                    raw_rows.append(
                        {
                            "evento_key": "vacaciones_escolares",
                            "fecha_inicio": d,
                            "fecha_fin": d,
                            "fuente": "open_holidays",
                            "source_key": f"oh_school:{pais_codigo}:{region_code or ''}:{d}",
                            "metadata": {"pais": pais_codigo, "region": region_code},
                        }
                    )

            for fh in get_public_holidays_detail(pais_codigo, year, region_code):
                if not fh.get("nationwide", True) and date_from <= fh["fecha"] <= date_to:
                    _slot(fh["fecha"])["ev_festivo_regional"] = 1
                    raw_rows.append(
                        {
                            "evento_key": "festivo_regional",
                            "fecha_inicio": fh["fecha"],
                            "fecha_fin": fh["fecha"],
                            "fuente": "open_holidays",
                            "source_key": (
                                f"oh_ph:{pais_codigo}:{region_code or ''}:"
                                f"{fh['fecha']}:{fh['name']}"
                            ),
                            "metadata": {
                                "nombre": fh["name"],
                                "scope": fh.get("scope", ""),
                            },
                        }
                    )

        write_ev_features(uuid, daily)
        write_calendario_org(uuid, raw_rows, pais_codigo)
        write_sync_marker(uuid, "open_holidays")

        n = len(daily)
        if verbose:
            print(f"  [open_holidays] {loc['nombre']}: {n}d  (vacaciones + festivos regionales)")
        return n
    except Exception as e:
        if verbose:
            print(f"  [open_holidays] {loc['nombre']}: ERROR — {e}")
        return 0


def _handler_cruceros(
    loc: dict,
    params: dict,
    max_age_hours: float,
    verbose: bool,
) -> int:
    """Handler para cruceros — solo para ubicaciones con config activa."""
    uuid = loc["uuid"]
    if is_fresh(uuid, "cruceros", max_age_hours):
        if verbose:
            print(f"  [cruceros] {uuid[:8]}…: omitido (datos < {max_age_hours:.0f}h)")
        return 0
    try:
        import json as _json
        import re

        import requests

        from src.data_ingestion._common import ensure_feature_registry
        from src.db.store import get_conn

        cfg = get_source_config("cruceros", params)

        ajax_url = params.get("ajax_url")
        if not ajax_url:
            if verbose:
                print(f"  [cruceros] {uuid[:8]}…: sin ajax_url en params — omitido")
            return 0
        pais_codigo = params.get("pais_codigo", "ES")

        feature_key = cfg["feature_key"]
        categoria_evento = cfg.get("categoria_evento", "escala_crucero")

        def _fetch_month(month: int, year: int) -> list[dict]:
            resp = requests.post(
                ajax_url,
                data={
                    "action": "get_prevision_turistas_by_date",
                    "date": f"{month:02d}/{year}",
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": ajax_url.replace(
                        "/wp-admin/admin-ajax.php", "/es/prevision-cruceros/"
                    ),
                    "User-Agent": "Mozilla/5.0 (compatible; agentic-workflow/1.0)",
                },
                timeout=20,
            )
            resp.raise_for_status()
            rows = resp.json()
            escalas = []
            for row in rows[1:]:
                if len(row) < 5:
                    continue
                fecha = _parse_arrival_date(row[4], month, year)
                if fecha is None:
                    continue
                buque = re.sub(r"<[^>]+>", " ", row[0]).strip()
                n_pax = _parse_int(str(row[2]))
                escalas.append(
                    {"fecha": str(fecha), "barco": buque, "n_pasajeros": n_pax, "terminal": ""}
                )
            return escalas

        def _parse_arrival_date(entrada_salida: str, query_month: int, query_year: int):
            try:
                llegada = re.split(r"<br\s*/?>", entrada_salida, flags=re.I)[0].strip()
                m = re.match(r"(\d{1,2})/(\d{1,2})", llegada)
                if not m:
                    return None
                day, month = int(m.group(1)), int(m.group(2))
                year = query_year
                diff = month - query_month
                if diff > 6:
                    year -= 1
                elif diff < -6:
                    year += 1
                return date(year, month, day)
            except Exception:
                return None

        def _parse_int(s: str):
            s = re.sub(r"[^\d]", "", s)
            return int(s) if s else None

        def ingestar_escalas(escalas: list[dict]) -> int:
            if not escalas:
                return 0
            conn = get_conn()
            cal_rows = [
                (
                    None,
                    uuid,
                    pais_codigo,
                    categoria_evento,
                    e["fecha"],
                    e["fecha"],
                    _json.dumps(
                        {
                            "barco": e.get("barco", ""),
                            "n_pasajeros": e.get("n_pasajeros"),
                            "terminal": "",
                        },
                        ensure_ascii=False,
                    ),
                    "cruceros",
                    f"{uuid}:{categoria_evento}:{e['fecha']}:{e.get('barco', '')}",
                )
                for e in escalas
            ]
            conn.executemany(
                """INSERT INTO store_calendario_org
                       (org_uuid, location_uuid, pais_codigo, evento_key,
                        fecha_inicio, fecha_fin, metadata, fuente, source_key)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (source_key) DO UPDATE SET metadata = excluded.metadata""",
                cal_rows,
            )
            daily: dict[str, float] = {}
            for e in escalas:
                pax = e.get("n_pasajeros")
                if pax and pax > 0:
                    daily[e["fecha"]] = daily.get(e["fecha"], 0.0) + pax
            if daily:
                ensure_feature_registry(feature_key, "cruceros", "turismo")
                conn.executemany(
                    "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) "
                    "VALUES (?,?,?,?) "
                    "ON CONFLICT (fecha, location_uuid, feature_key) "
                    "DO UPDATE SET value = excluded.value, ingested_at = NOW()",
                    [(f, uuid, feature_key, v) for f, v in daily.items()],
                )
            return len(cal_rows)

        today = date.today()
        prev = (today.month - 1 or 12, today.year if today.month > 1 else today.year - 1)
        nxt = (today.month % 12 + 1, today.year if today.month < 12 else today.year + 1)

        m, y = prev
        total = 0
        while (y, m) <= (nxt[1], nxt[0]):
            escalas = _fetch_month(m, y)
            if verbose:
                print(f"  [cruceros] {m:02d}/{y}: {len(escalas)} escalas", end="")
            if escalas:
                ingestar_escalas(escalas)
            if verbose:
                print()
            total += len(escalas)
            m += 1
            if m > 12:
                m, y = 1, y + 1

        write_sync_marker(uuid, "cruceros")
        if verbose:
            print(f"  [cruceros] {uuid[:8]}…: {total} escalas en calendario")
        return total
    except Exception as e:
        if verbose:
            print(f"  [cruceros] {uuid[:8]}… ERROR — {e}")
        return 0


def _handler_ticketmaster(
    loc: dict,
    params: dict,  # noqa: ARG001
    max_age_hours: float,
    verbose: bool,
) -> int:
    uuid = loc["uuid"]
    if is_fresh(uuid, "ticketmaster", max_age_hours):
        if verbose:
            print(f"  [ticketmaster] {loc['nombre']}: omitido (datos < {max_age_hours:.0f}h)")
        return 0
    try:
        from src.data_processing.fuentes_eventos.ticketmaster import (
            _key,
            events_to_daily_scores,
            events_to_raw_rows,
            fetch_events_raw,
        )

        if not _key():
            if verbose:
                print("  [ticketmaster] TICKETMASTER_KEY no configurada — omitido")
            return 0

        lat, lon = loc["lat"], loc["lon"]
        date_from = EVENTS_DATE_FROM
        date_to = date.today() + timedelta(days=EVENTS_HORIZON)

        raw = fetch_events_raw(lat, lon, date_from, date_to)
        scores = events_to_daily_scores(raw)
        rows = events_to_raw_rows(raw, uuid)

        daily: dict[date, dict] = {}
        for d, cats in scores.items():
            if date_from <= d <= date_to:
                daily[d] = {
                    "ev_rank_deportivo": cats.get("deportivo", 0),
                    "ev_rank_concierto": cats.get("concierto", 0),
                    "ev_rank_festival": cats.get("festival", 0),
                }

        write_ev_features(uuid, daily)
        write_calendario_org(uuid, rows, loc["pais_codigo"])
        write_sync_marker(uuid, "ticketmaster")

        n = len(daily)
        if verbose:
            print(f"  [ticketmaster] {loc['nombre']}: {n}d con eventos  ({len(raw)} raw)")
        return n
    except Exception as e:
        if verbose:
            print(f"  [ticketmaster] {loc['nombre']}: ERROR — {e}")
        return 0


def _handler_thesportsdb(
    loc: dict,
    params: dict,  # noqa: ARG001
    max_age_hours: float,
    verbose: bool,
) -> int:
    uuid = loc["uuid"]
    if is_fresh(uuid, "thesportsdb", max_age_hours):
        if verbose:
            print(f"  [thesportsdb] {loc['nombre']}: omitido (datos < {max_age_hours:.0f}h)")
        return 0
    try:
        from src.data_processing.fuentes_eventos.thesportsdb import (
            get_events_for_city,
        )

        ciudad = loc["city"]
        pais_codigo = loc["pais_codigo"]
        date_from = EVENTS_DATE_FROM
        date_to = date.today() + timedelta(days=EVENTS_HORIZON)

        if not ciudad:
            if verbose:
                print(f"  [thesportsdb] {loc['nombre']}: sin ciudad configurada — omitido")
            write_sync_marker(uuid, "thesportsdb")
            return 0

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
                    "fuente": "thesportsdb",
                    "source_key": f"tsdb:{uuid}:{ev['source_key']}",
                    "metadata": {
                        "evento": ev["evento"],
                        "liga": ev["liga"],
                        "sede": ev.get("sede", ""),
                        "ciudad_sede": ev.get("ciudad_sede", ""),
                        "es_local": ev.get("es_local", True),
                    },
                }
            )

        write_ev_features(uuid, daily)
        write_calendario_org(uuid, raw_rows, pais_codigo)
        write_sync_marker(uuid, "thesportsdb")

        n = len(daily)
        if verbose:
            print(f"  [thesportsdb] {loc['nombre']}: {n}d con partidos  ({len(events)} eventos)")
        return n
    except Exception as e:
        if verbose:
            print(f"  [thesportsdb] {loc['nombre']}: ERROR — {e}")
        return 0


def _handler_agenda_es(
    loc: dict,
    params: dict,  # noqa: ARG001
    max_age_hours: float,
    verbose: bool,
) -> int:
    uuid = loc["uuid"]
    if is_fresh(uuid, "agenda_es", max_age_hours):
        if verbose:
            print(f"  [agenda_es] {loc['nombre']}: omitido (datos < {max_age_hours:.0f}h)")
        return 0
    try:
        from src.data_processing.fuentes_eventos.agenda_es import fetch_agenda_ciudad

        ciudad = loc["city"]
        pais_codigo = loc["pais_codigo"]
        date_from = EVENTS_DATE_FROM
        date_to = date.today() + timedelta(days=EVENTS_HORIZON)

        if not ciudad:
            if verbose:
                print(f"  [agenda_es] {loc['nombre']}: sin ciudad configurada — omitido")
            write_sync_marker(uuid, "agenda_es")
            return 0

        events = fetch_agenda_ciudad(ciudad, date_from, date_to)

        daily: dict[date, dict] = {}
        raw_rows: list[dict] = []
        for ev in events:
            d = ev["fecha"]
            if d not in daily:
                daily[d] = {"ev_rank_municipal": 0}
            daily[d]["ev_rank_municipal"] = max(daily[d]["ev_rank_municipal"], ev["score"])
            raw_rows.append(
                {
                    "evento_key": "evento_municipal",
                    "fecha_inicio": d,
                    "fecha_fin": d,
                    "fuente": "agenda_municipal",
                    "source_key": f"muni:{uuid}:{ev['source_key']}",
                    "metadata": {"titulo": ev["titulo"], "categoria": ev["categoria"]},
                }
            )

        write_ev_features(uuid, daily)
        write_calendario_org(uuid, raw_rows, pais_codigo)
        write_sync_marker(uuid, "agenda_es")

        n = len(daily)
        if verbose:
            print(f"  [agenda_es] {loc['nombre']}: {n}d con eventos municipales")
        return n
    except Exception as e:
        if verbose:
            print(f"  [agenda_es] {loc['nombre']}: ERROR — {e}")
        return 0


# ── Dispatch table ────────────────────────────────────────────────────────────

_HANDLERS: dict[str, Callable] = {
    "weather": _handler_weather,
    "open_holidays": _handler_open_holidays,
    "cruceros": _handler_cruceros,
    "ticketmaster": _handler_ticketmaster,
    "thesportsdb": _handler_thesportsdb,
    "agenda_es": _handler_agenda_es,
}


# ── Funcion publica ───────────────────────────────────────────────────────────


def run_all(
    location_uuid: str | None = None,
    skip: set[str] | None = None,
    only: set[str] | None = None,
    max_age_hours: float = 23,
    verbose: bool = True,
) -> dict[str, dict[str, int]]:
    """
    Para cada ubicacion activa:
      1. Ejecuta handlers universales para todos
      2. Ejecuta handlers configurados solo si la ubicacion tiene config
      3. Recalcula ev_rank_total al final

    Retorna {source: {location_uuid: n_rows}}.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    active_sources = set(_HANDLERS.keys())
    if only:
        active_sources &= only
    if skip:
        active_sources -= skip

    locations = get_active_locations(location_uuid)
    if not locations:
        log("[!] Sin locations activas.")
        return {}

    width = 60
    log(f"\n{'─'*width}")
    log(
        f"  sync_diaria/run_all — {len(locations)} location(s)"
        f"  |  sources: {', '.join(sorted(active_sources))}"
    )
    log(f"  max-age: {max_age_hours:.0f}h")
    log(f"{'─'*width}")

    t0 = time.time()
    results: dict[str, dict[str, int]] = {src: {} for src in active_sources}

    # Preparar config de fuentes configuradas una sola vez
    config_por_source: dict[str, dict[str, dict]] = {}
    for src in _CONFIGURADAS & active_sources:
        config_por_source[src] = {lu: p for lu, p in get_configured_locations(src)}

    # Pre-calentar cache de thesportsdb si se va a ejecutar
    if "thesportsdb" in active_sources and locations and not location_uuid:
        try:
            from src.data_processing.fuentes_eventos.thesportsdb import prewarm as _prewarm

            paises = {loc["pais_codigo"] for loc in locations if loc["pais_codigo"]}
            if verbose:
                print(f"  [thesportsdb] precalentando cache ({', '.join(sorted(paises))})...")
            _prewarm(paises, EVENTS_DATE_FROM, date.today() + timedelta(days=EVENTS_HORIZON))
        except Exception:
            pass

    def _run_source(src: str) -> dict[str, int]:
        handler = _HANDLERS[src]
        stats: dict[str, int] = {}
        for loc in locations:
            uuid = loc["uuid"]
            if src in _UNIVERSAL:
                params: dict = {}
            elif src in _CONFIGURADAS:
                cfg = config_por_source.get(src, {})
                if uuid not in cfg:
                    continue  # ubicacion sin config para esta source
                params = cfg[uuid]
            else:
                params = {}
            try:
                n = handler(loc, params, max_age_hours, verbose)
                stats[uuid] = n
            except Exception as e:
                if verbose:
                    print(f"  [{src}] {loc['nombre']}: ERROR no capturado — {e}")
                stats[uuid] = 0
        return stats

    with ThreadPoolExecutor(max_workers=max(1, len(active_sources))) as pool:
        futures = {pool.submit(_run_source, src): src for src in active_sources}
        for future in as_completed(futures):
            src = futures[future]
            try:
                results[src] = future.result()
            except Exception as e:
                log(f"  [!] {src}: ERROR no capturado — {e}")
                results[src] = {}

    ran_event_sources = active_sources & _EVENT_SOURCES
    if ran_event_sources:
        date_to = date.today() + timedelta(days=EVENTS_HORIZON)
        for loc in locations:
            update_ev_rank_total(loc["uuid"], EVENTS_DATE_FROM, date_to)

    elapsed = time.time() - t0
    log(f"\n{'─'*width}")
    log(f"  Completado en {elapsed:.0f}s")
    log(f"{'─'*width}\n")

    return results


def run(
    location_uuid: str | None = None,
    max_age_hours: float = 23,
    verbose: bool = True,
) -> dict[str, int]:
    """
    Alias de run_all para compatibilidad con onboarding (devuelve {uuid: n_rows} aplanado).
    Ejecuta todos los sources y agrega los conteos por location_uuid.
    """
    all_results = run_all(
        location_uuid=location_uuid,
        max_age_hours=max_age_hours,
        verbose=verbose,
    )
    aggregated: dict[str, int] = {}
    for src_stats in all_results.values():
        for uuid, n in src_stats.items():
            aggregated[uuid] = aggregated.get(uuid, 0) + n
    return aggregated


def sync_cruceros_months(
    location_uuid: str,
    ajax_url: str,
    pais_codigo: str = "ES",
    desde: tuple[int, int] | None = None,
    hasta: tuple[int, int] | None = None,
    dry_run: bool = False,
    verbose: bool = True,
) -> int:
    """
    Descarga y persiste escalas de cruceros para un rango de meses.
    Funcion publica expuesta para scripts/sync_mensual.py (refresco del calendario anual).

    desde/hasta: (month, year). Por defecto: mes actual unicamente.
    Devuelve el total de escalas procesadas.
    """
    import json as _json
    import re

    import requests

    from src.data_ingestion._common import ensure_feature_registry, get_source_config
    from src.db.store import get_conn

    _cfg = get_source_config("cruceros")
    _FK_DIA = _cfg.get("feature_key", "n_pasajeros_crucero_dia")
    _CATEGORIA_EVENTO = _cfg.get("categoria_evento", "escala_crucero")

    def _parse_arrival_date(entrada_salida: str, query_month: int, query_year: int):
        try:
            llegada = re.split(r"<br\s*/?>", entrada_salida, flags=re.I)[0].strip()
            m = re.match(r"(\d{1,2})/(\d{1,2})", llegada)
            if not m:
                return None
            day, month = int(m.group(1)), int(m.group(2))
            year = query_year
            diff = month - query_month
            if diff > 6:
                year -= 1
            elif diff < -6:
                year += 1
            return date(year, month, day)
        except Exception:
            return None

    def _parse_int(s: str):
        s = re.sub(r"[^\d]", "", s)
        return int(s) if s else None

    def _fetch_month(month: int, year: int) -> list[dict]:
        resp = requests.post(
            ajax_url,
            data={"action": "get_prevision_turistas_by_date", "date": f"{month:02d}/{year}"},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": ajax_url.replace("/wp-admin/admin-ajax.php", "/es/prevision-cruceros/"),
                "User-Agent": "Mozilla/5.0 (compatible; agentic-workflow/1.0)",
            },
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json()
        escalas = []
        for row in rows[1:]:
            if len(row) < 5:
                continue
            f = _parse_arrival_date(row[4], month, year)
            if f is None:
                continue
            buque = re.sub(r"<[^>]+>", " ", row[0]).strip()
            n_pax = _parse_int(str(row[2]))
            escalas.append({"fecha": str(f), "barco": buque, "n_pasajeros": n_pax, "terminal": ""})
        return escalas

    def _ingestar(escalas: list[dict]) -> None:
        if not escalas or dry_run:
            return
        conn = get_conn()
        cal_rows = [
            (
                None,
                location_uuid,
                pais_codigo,
                _CATEGORIA_EVENTO,
                e["fecha"],
                e["fecha"],
                _json.dumps(
                    {
                        "barco": e.get("barco", ""),
                        "n_pasajeros": e.get("n_pasajeros"),
                        "terminal": "",
                    },
                    ensure_ascii=False,
                ),
                "cruceros",
                f"{location_uuid}:{_CATEGORIA_EVENTO}:{e['fecha']}:{e.get('barco', '')}",
            )
            for e in escalas
        ]
        conn.executemany(
            """INSERT INTO store_calendario_org
                   (org_uuid, location_uuid, pais_codigo, evento_key,
                    fecha_inicio, fecha_fin, metadata, fuente, source_key)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT (source_key) DO UPDATE SET metadata = excluded.metadata""",
            cal_rows,
        )
        daily: dict[str, float] = {}
        for e in escalas:
            pax = e.get("n_pasajeros")
            if pax and pax > 0:
                daily[e["fecha"]] = daily.get(e["fecha"], 0.0) + pax
        if daily:
            ensure_feature_registry(_FK_DIA, "cruceros", "turismo")
            conn.executemany(
                "INSERT INTO store_features_ext (fecha, location_uuid, feature_key, value) "
                "VALUES (?,?,?,?) "
                "ON CONFLICT (fecha, location_uuid, feature_key) "
                "DO UPDATE SET value = excluded.value, ingested_at = NOW()",
                [(f, location_uuid, _FK_DIA, v) for f, v in daily.items()],
            )

    today = date.today()
    if hasta is None:
        hasta = (today.month, today.year)
    if desde is None:
        desde = hasta

    m, y = desde
    total = 0
    while (y, m) <= (hasta[1], hasta[0]):
        escalas = _fetch_month(m, y)
        if verbose:
            print(f"  {m:02d}/{y}: {len(escalas)} escalas", end="")
        _ingestar(escalas)
        if verbose:
            print()
        total += len(escalas)
        m += 1
        if m > 12:
            m, y = 1, y + 1

    return total


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Sincronizacion diaria completa (todos los sources en paralelo)"
    )
    parser.add_argument("--location", metavar="UUID")
    parser.add_argument("--skip", action="append", default=[], metavar="SOURCE")
    parser.add_argument(
        "--solo",
        default=None,
        metavar="SOURCE[,SOURCE]",
        help="Ejecutar solo estos sources (coma-separados)",
    )
    parser.add_argument("--max-age", type=float, default=23, metavar="HORAS")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    only_set = set(args.solo.split(",")) if args.solo else None

    run_all(
        location_uuid=args.location,
        skip=set(args.skip) or None,
        only=only_set,
        max_age_hours=0 if args.force else args.max_age,
        verbose=not args.quiet,
    )
