"""
Sincronizacion diaria de senales de contexto — orquestador puro.

Lee la tabla `fuentes` para descubrir qué fuentes están activas con periodicidad
diaria, carga el conector correspondiente desde src/conectores/<tipo_conector>.py
y ejecuta sync() por cada ubicación activa.

CLI:
  python -m src.data_ingestion.sync_diaria
  python -m src.data_ingestion.sync_diaria --location <uuid>
  python -m src.data_ingestion.sync_diaria --solo weather,open_holidays
  python -m src.data_ingestion.sync_diaria --force
"""

from __future__ import annotations

import importlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from src.data_ingestion._common import (
    EVENTS_DATE_FROM,
    EVENTS_HORIZON,
    get_active_locations,
    get_configured_locations,
    get_source_config,
    is_fresh,
    update_ev_rank_total,
    write_sync_marker,
)


def _cargar_conector(tipo: str):
    return importlib.import_module(f"src.conectores.{tipo}")


def run_all(
    location_uuid: str | None = None,
    skip: set[str] | None = None,
    only: set[str] | None = None,
    max_age_hours: float = 23,
    verbose: bool = True,
) -> dict[str, dict[str, int]]:
    """
    Para cada fuente diaria activa en la DB:
      1. Carga el conector dinámicamente por tipo_conector.
      2. Ejecuta sync() para cada ubicación activa (universales) o configurada.
      3. Recalcula ev_rank_total al final si se ejecutó alguna fuente de eventos.

    Retorna {fuente: {ubicacion_id: n_rows}}.
    """
    from src.db.store import get_conn

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    # Leer fuentes diarias de la DB
    fuentes_rows = (
        get_conn()
        .execute(
            "SELECT fuente, config FROM fuentes WHERE periodicidad = 'diaria' AND activo = TRUE"
        )
        .fetchall()
    )

    fuentes_activas = [
        (f, c) for f, c in fuentes_rows if (not only or f in only) and (not skip or f not in skip)
    ]

    if not fuentes_activas:
        log("[!] Sin fuentes diarias activas.")
        return {}

    # Fuentes con config por ubicación explícita (filas en config_fuentes)
    configured_sources = {
        r[0]
        for r in get_conn()
        .execute("SELECT DISTINCT fuente FROM config_fuentes WHERE activo = TRUE")
        .fetchall()
    }

    locations = get_active_locations(location_uuid)
    if not locations:
        log("[!] Sin locations activas.")
        return {}

    width = 60
    log(f"\n{'─'*width}")
    log(
        f"  sync_diaria/run_all — {len(locations)} location(s)"
        f"  |  fuentes: {', '.join(sorted(f for f, _ in fuentes_activas))}"
    )
    log(f"  max-age: {max_age_hours:.0f}h")
    log(f"{'─'*width}")

    # Pre-calentar cache de thesportsdb si va a ejecutarse
    _thesportsdb_entry = next(((f, c) for f, c in fuentes_activas if f == "thesportsdb"), None)
    if _thesportsdb_entry and not location_uuid:
        try:
            from src.data_processing.fuentes_eventos.thesportsdb import prewarm as _prewarm

            paises = {loc["pais_codigo"] for loc in locations if loc["pais_codigo"]}
            if verbose:
                print(f"  [thesportsdb] precalentando cache ({', '.join(sorted(paises))})...")
            _prewarm(paises, EVENTS_DATE_FROM, date.today() + timedelta(days=EVENTS_HORIZON))
        except Exception:
            pass

    t0 = time.time()
    results: dict[str, dict[str, int]] = {}
    event_sources_ran: set[str] = set()

    def _run_fuente(fuente_nombre: str, config: dict) -> dict[str, int]:
        tipo = config.get("tipo_conector")
        if not tipo:
            if verbose:
                print(f"  [{fuente_nombre}] sin tipo_conector en config — omitido")
            return {}
        try:
            conector = _cargar_conector(tipo)
        except ModuleNotFoundError:
            if verbose:
                print(f"  [{fuente_nombre}] conector '{tipo}' no encontrado — omitido")
            return {}

        stats: dict[str, int] = {}

        if fuente_nombre in configured_sources:
            # Solo ubicaciones con config explícita en config_fuentes
            loc_configs = get_configured_locations(fuente_nombre)
            if location_uuid:
                loc_configs = [(lu, p) for lu, p in loc_configs if lu == location_uuid]
            for lu, params in loc_configs:
                loc = next((lc for lc in locations if lc["ubicacion_id"] == lu), None)
                if not loc:
                    continue
                if is_fresh(lu, fuente_nombre, max_age_hours):
                    if verbose:
                        print(
                            f"  [{fuente_nombre}] {loc.get('nombre', lu)}: "
                            f"omitido (datos < {max_age_hours:.0f}h)"
                        )
                    stats[lu] = 0
                    continue
                cfg = get_source_config(fuente_nombre, params)
                try:
                    n = conector.sync(loc, cfg, verbose)
                    write_sync_marker(lu, fuente_nombre)
                    stats[lu] = n
                except Exception as e:
                    if verbose:
                        print(f"  [{fuente_nombre}] {lu}: ERROR — {e}")
                    stats[lu] = 0
        else:
            # Universal: corre para todas las ubicaciones activas
            for loc in locations:
                lu = loc["ubicacion_id"]
                if is_fresh(lu, fuente_nombre, max_age_hours):
                    if verbose:
                        print(
                            f"  [{fuente_nombre}] {loc.get('nombre', lu)}: "
                            f"omitido (datos < {max_age_hours:.0f}h)"
                        )
                    stats[lu] = 0
                    continue
                cfg = get_source_config(fuente_nombre, {})
                try:
                    n = conector.sync(loc, cfg, verbose)
                    write_sync_marker(lu, fuente_nombre)
                    stats[lu] = n
                except Exception as e:
                    if verbose:
                        print(f"  [{fuente_nombre}] {loc.get('nombre', lu)}: ERROR — {e}")
                    stats[lu] = 0

        return stats

    with ThreadPoolExecutor(max_workers=max(1, len(fuentes_activas))) as pool:
        futures = {pool.submit(_run_fuente, f, c): (f, c) for f, c in fuentes_activas}
        for future in as_completed(futures):
            f, c = futures[future]
            try:
                results[f] = future.result()
                if c.get("tipo_conector") == "eventos_api" or f in {
                    "open_holidays",
                    "ticketmaster",
                    "thesportsdb",
                    "agenda_es",
                }:
                    event_sources_ran.add(f)
            except Exception as e:
                log(f"  [!] {f}: ERROR — {e}")
                results[f] = {}

    if event_sources_ran:
        date_to = date.today() + timedelta(days=EVENTS_HORIZON)
        for loc in locations:
            update_ev_rank_total(loc["ubicacion_id"], EVENTS_DATE_FROM, date_to)

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
    Ejecuta todos los sources y agrega los conteos por ubicacion_id.
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
    Delegado al conector agenda_ajax_tabla.
    Función pública expuesta para scripts/sync_mensual.py (refresco del calendario anual).

    desde/hasta: (month, year). Por defecto: mes actual únicamente.
    Devuelve el total de escalas procesadas.
    """
    from src.conectores.agenda_ajax_tabla import sync_rango_meses
    from src.db.store import get_conn

    cfg_row = get_conn().execute("SELECT config FROM fuentes WHERE fuente = 'cruceros'").fetchone()
    cfg = {
        **(cfg_row[0] if cfg_row else {}),
        "ajax_url": ajax_url,
        "pais_codigo": pais_codigo,
    }
    return sync_rango_meses(
        location_uuid, cfg, desde=desde, hasta=hasta, dry_run=dry_run, verbose=verbose
    )


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
