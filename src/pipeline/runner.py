"""
Orquestador dlt — lee fuentes de la DB y despacha a los recursos registrados.

Lee la tabla `fuentes` para descubrir qué fuentes están activas, resuelve
el tipo_conector, construye las ubicaciones con sus params incrustados y
ejecuta el pipeline dlt correspondiente.

CLI:
  python -m src.pipeline.runner
  python -m src.pipeline.runner --periodicidad diaria
  python -m src.pipeline.runner --location <uuid>
  python -m src.pipeline.runner --solo <fuente>[,<fuente>]
  python -m src.pipeline.runner --force
"""

from __future__ import annotations

import time
from datetime import date, timedelta

from src.data_ingestion._common import (
    EVENTS_DATE_FROM,
    EVENTS_HORIZON,
    get_active_locations,
    get_configured_locations,
    is_fresh,
    update_ev_rank_total,
    write_sync_marker,
)
from src.pipeline.config import make_pipeline
from src.pipeline.resources import get_source_fn

# Tipos que generan datos en la tabla eventos (necesitan recalcular ev_rank_total)
_EVENT_TIPOS = {"festivos_calendario", "eventos", "agenda_opendata"}


def _read_fuentes(periodicidad: str | None = None) -> list[tuple[str, dict]]:
    from src.db.store import get_conn

    sql = "SELECT fuente, config FROM fuentes WHERE activo = TRUE"
    params: list = []
    if periodicidad:
        sql += " AND periodicidad = %s"
        params.append(periodicidad)
    rows = get_conn().execute(sql, params).fetchall()
    return [(f, c or {}) for f, c in rows]


def _configured_sources() -> set[str]:
    from src.db.store import get_conn

    return {
        r[0]
        for r in get_conn()
        .execute("SELECT DISTINCT fuente FROM config_fuentes WHERE activo = TRUE")
        .fetchall()
    }


def _build_ubicaciones(
    fuente: str,
    all_locations: list[dict],
    configured: set[str],
) -> list[dict]:
    """Retorna ubicaciones con params incrustados en ubi["params"]."""
    if fuente in configured:
        loc_map = {loc["ubicacion_id"]: loc for loc in all_locations}
        result = []
        for loc_uuid, params in get_configured_locations(fuente):
            loc = loc_map.get(loc_uuid)
            if loc:
                result.append({**loc, "params": params})
        return result
    return [{**loc, "params": {}} for loc in all_locations]


def run(
    periodicidad: str | None = None,
    location_uuid: str | None = None,
    only: set[str] | None = None,
    skip: set[str] | None = None,
    max_age_hours: float = 23,
    date_from: date | None = None,
    date_to: date | None = None,
    verbose: bool = True,
) -> dict[str, int]:
    """
    Ejecuta el pipeline dlt para todas las fuentes activas que coincidan con los filtros.
    Retorna {fuente: n_ubicaciones_procesadas}.
    """
    fuentes = _read_fuentes(periodicidad)
    fuentes = [
        (f, c) for f, c in fuentes if (not only or f in only) and (not skip or f not in skip)
    ]

    if not fuentes:
        if verbose:
            print("[pipeline] Sin fuentes activas.")
        return {}

    all_locations = get_active_locations(location_uuid)
    if not all_locations:
        if verbose:
            print("[pipeline] Sin ubicaciones activas.")
        return {}

    configured = _configured_sources()
    d_from = date_from or EVENTS_DATE_FROM
    d_to = date_to or (date.today() + timedelta(days=EVENTS_HORIZON))

    results: dict[str, int] = {}
    event_tipos_ran: set[str] = set()

    for fuente, cfg in fuentes:
        tipo = cfg.get("tipo_conector")
        if not tipo:
            if verbose:
                print(f"  [{fuente}] sin tipo_conector en config — omitido")
            continue

        try:
            source_fn = get_source_fn(tipo)
        except ValueError as e:
            if verbose:
                print(f"  [{fuente}] {e} — omitido")
            continue

        ubicaciones = _build_ubicaciones(fuente, all_locations, configured)
        stale = [u for u in ubicaciones if not is_fresh(u["ubicacion_id"], fuente, max_age_hours)]

        if not stale:
            if verbose:
                print(f"  [{fuente}] todos los datos frescos — omitido")
            results[fuente] = 0
            continue

        if verbose:
            print(f"  [{fuente}] {len(stale)} ubicacion(es) → tipo_conector={tipo}")

        try:
            t0 = time.time()
            pipeline = make_pipeline(fuente)
            pipeline.run(source_fn(stale, cfg, d_from, d_to))

            for ubi in stale:
                write_sync_marker(ubi["ubicacion_id"], fuente)

            results[fuente] = len(stale)
            if verbose:
                print(f"  [{fuente}] completado en {time.time() - t0:.0f}s")

            if tipo in _EVENT_TIPOS:
                event_tipos_ran.add(tipo)

        except Exception as e:
            if verbose:
                print(f"  [{fuente}] ERROR — {e}")
            results[fuente] = 0

    if event_tipos_ran:
        for loc in all_locations:
            update_ev_rank_total(loc["ubicacion_id"], d_from, d_to)

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pipeline dlt — todas las fuentes activas")
    parser.add_argument("--location", metavar="UUID")
    parser.add_argument("--periodicidad", metavar="diaria|mensual")
    parser.add_argument("--solo", metavar="FUENTE[,FUENTE]")
    parser.add_argument("--skip", action="append", default=[], metavar="FUENTE")
    parser.add_argument("--max-age", type=float, default=23, metavar="HORAS")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    only_set = set(args.solo.split(",")) if args.solo else None
    run(
        periodicidad=args.periodicidad,
        location_uuid=args.location,
        only=only_set,
        skip=set(args.skip) or None,
        max_age_hours=0 if args.force else args.max_age,
        verbose=not args.quiet,
    )
