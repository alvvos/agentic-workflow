"""
Conector genérico para APIs de eventos (Ticketmaster, TheSportsDB, Agenda ES).

El campo cfg["modulo"] determina qué cliente se carga desde
src/data_processing/fuentes_eventos/<modulo>.py.

Interfaz pública:
    TIPO = "eventos_api"
    sync(ubicacion, cfg, verbose) -> int
"""

from __future__ import annotations

import importlib
from datetime import date, timedelta

from src.data_ingestion._common import (
    EVENTS_DATE_FROM,
    EVENTS_HORIZON,
    write_calendario_org,
    write_ev_features,
)

TIPO = "eventos_api"

# Funciones requeridas por módulo cliente
# ticketmaster: fetch_events_raw, events_to_daily_scores, events_to_raw_rows, _key
# thesportsdb:  get_events_for_city, prewarm (opcional)
# agenda_es:    fetch_agenda_ciudad


def sync(ubicacion: dict, cfg: dict, verbose: bool = True) -> int:
    """
    Descarga y persiste eventos de la API indicada en cfg["modulo"].

    ubicacion: {ubicacion_id, nombre, lat, lon, pais_codigo, region_code, city}
    cfg: config efectiva — debe contener "modulo" con el nombre del cliente.
    No llama a is_fresh() ni write_sync_marker() — los gestiona el orquestador.
    Devuelve el número de días con datos escritos.
    """
    modulo_nombre = cfg.get("modulo")
    if not modulo_nombre:
        if verbose:
            print("  [eventos_api] sin 'modulo' en cfg — omitido")
        return 0

    cliente = importlib.import_module(f"src.data_processing.fuentes_eventos.{modulo_nombre}")

    ubicacion_id = ubicacion["ubicacion_id"]
    nombre = ubicacion.get("nombre", ubicacion_id)
    pais_codigo = ubicacion["pais_codigo"]
    ciudad = ubicacion.get("city", "")
    lat = ubicacion.get("lat")
    lon = ubicacion.get("lon")
    date_from = EVENTS_DATE_FROM
    date_to = date.today() + timedelta(days=EVENTS_HORIZON)

    daily: dict[date, dict] = {}
    raw_rows: list[dict] = []

    # ── ticketmaster ─────────────────────────────────────────────────────────
    if modulo_nombre == "ticketmaster":
        if not cliente._key():
            if verbose:
                print("  [eventos_api/ticketmaster] TICKETMASTER_KEY no configurada — omitido")
            return 0

        raw = cliente.fetch_events_raw(lat, lon, date_from, date_to)
        scores = cliente.events_to_daily_scores(raw)
        rows = cliente.events_to_raw_rows(raw, ubicacion_id)

        for d, cats in scores.items():
            if date_from <= d <= date_to:
                daily[d] = {
                    "ev_rank_deportivo": cats.get("deportivo", 0),
                    "ev_rank_concierto": cats.get("concierto", 0),
                    "ev_rank_festival": cats.get("festival", 0),
                }
        raw_rows = rows

        n = len(daily)
        if verbose:
            print(f"  [eventos_api/ticketmaster] {nombre}: {n}d con eventos  ({len(raw)} raw)")

    # ── thesportsdb ──────────────────────────────────────────────────────────
    elif modulo_nombre == "thesportsdb":
        if not ciudad:
            if verbose:
                print(f"  [eventos_api/thesportsdb] {nombre}: sin ciudad configurada — omitido")
            return 0

        events = cliente.get_events_for_city(ciudad, pais_codigo, date_from, date_to)

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

        n = len(daily)
        if verbose:
            print(
                f"  [eventos_api/thesportsdb] {nombre}: {n}d con partidos  ({len(events)} eventos)"
            )

    # ── agenda_es ────────────────────────────────────────────────────────────
    elif modulo_nombre == "agenda_es":
        if not ciudad:
            if verbose:
                print(f"  [eventos_api/agenda_es] {nombre}: sin ciudad configurada — omitido")
            return 0

        events = cliente.fetch_agenda_ciudad(ciudad, date_from, date_to)

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
                    "source_key": f"muni:{ubicacion_id}:{ev['source_key']}",
                    "metadata": {"titulo": ev["titulo"], "categoria": ev["categoria"]},
                }
            )

        n = len(daily)
        if verbose:
            print(f"  [eventos_api/agenda_es] {nombre}: {n}d con eventos municipales")

    else:
        if verbose:
            print(f"  [eventos_api] módulo '{modulo_nombre}' no reconocido — omitido")
        return 0

    write_ev_features(ubicacion_id, daily)
    write_calendario_org(ubicacion_id, raw_rows, pais_codigo)
    return n
