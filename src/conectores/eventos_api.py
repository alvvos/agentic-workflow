"""
Conector genérico para APIs de eventos.

cfg["modulo"] determina el módulo cliente cargado desde
src/data_processing/fuentes_eventos/<modulo>.py.

Cada módulo debe exponer:
    sync(ubicacion, cfg, date_from, date_to) -> tuple[dict[date, dict], list[dict]]

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


def sync(ubicacion: dict, cfg: dict, verbose: bool = True) -> int:
    modulo_nombre = cfg.get("modulo")
    if not modulo_nombre:
        if verbose:
            print("  [eventos_api] sin 'modulo' en cfg — omitido")
        return 0

    try:
        cliente = importlib.import_module(f"src.data_processing.fuentes_eventos.{modulo_nombre}")
    except ModuleNotFoundError:
        if verbose:
            print(f"  [eventos_api] módulo '{modulo_nombre}' no encontrado — omitido")
        return 0

    date_from = EVENTS_DATE_FROM
    date_to = date.today() + timedelta(days=EVENTS_HORIZON)

    daily, raw_rows = cliente.sync(ubicacion, cfg, date_from, date_to)

    if daily:
        write_ev_features(ubicacion["ubicacion_id"], daily)
    if raw_rows:
        write_calendario_org(ubicacion["ubicacion_id"], raw_rows, ubicacion["pais_codigo"])

    n = len(daily)
    if verbose:
        print(f"  [eventos_api/{modulo_nombre}] {ubicacion.get('nombre', '')}: {n}d con datos")
    return n
