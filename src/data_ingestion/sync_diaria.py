"""
Sincronizacion diaria de senales de contexto.

Delegado al pipeline dlt (src.pipeline.runner) para todos los sources diarios.
Mantiene sync_cruceros_months() para el flujo de cruceros (scraping Ajax).

CLI:
  python -m src.data_ingestion.sync_diaria
  python -m src.data_ingestion.sync_diaria --location <uuid>
  python -m src.data_ingestion.sync_diaria --solo <fuente>[,<fuente>]
  python -m src.data_ingestion.sync_diaria --force
"""

from __future__ import annotations

from src.pipeline.runner import run as _pipeline_run


def run_all(
    location_uuid: str | None = None,
    skip: set[str] | None = None,
    only: set[str] | None = None,
    max_age_hours: float = 23,
    verbose: bool = True,
) -> dict[str, dict[str, int]]:
    results = _pipeline_run(
        periodicidad="diaria",
        location_uuid=location_uuid,
        only=only,
        skip=skip,
        max_age_hours=max_age_hours,
        verbose=verbose,
    )
    # Wrap en formato {fuente: {ubicacion_id: n}} por compatibilidad con callers existentes
    return {fuente: {"_total": n} for fuente, n in results.items()}


def run(
    location_uuid: str | None = None,
    max_age_hours: float = 23,
    verbose: bool = True,
) -> dict[str, int]:
    """Alias de run_all — devuelve {fuente: n_ubicaciones}."""
    return _pipeline_run(
        periodicidad="diaria",
        location_uuid=location_uuid,
        max_age_hours=max_age_hours,
        verbose=verbose,
    )


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
    Delegado al conector agenda_ajax_tabla (scraping — no va por dlt).
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sincronizacion diaria — pipeline dlt")
    parser.add_argument("--location", metavar="UUID")
    parser.add_argument("--skip", action="append", default=[], metavar="SOURCE")
    parser.add_argument("--solo", metavar="SOURCE[,SOURCE]")
    parser.add_argument("--max-age", type=float, default=23, metavar="HORAS")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    only_set = set(args.solo.split(",")) if args.solo else None
    _pipeline_run(
        periodicidad="diaria",
        location_uuid=args.location,
        only=only_set,
        skip=set(args.skip) or None,
        max_age_hours=0 if args.force else args.max_age,
        verbose=not args.quiet,
    )
