#!/usr/bin/env python3
"""
Orquestador mensual — ejecutado por systemd timer el día 1 de cada mes a las 03:00.

Un único loop data-driven: lee feature_flags, agrupa por source, llama al ingestor
de ese source UNA sola vez con el lote completo de jobs asignados.
Escalar de 5 a 700 columnas distribuidas en N fuentes no cambia este script —
solo requiere registrar el ingestor en _build_ingestores().

Excepción: Geo/Esri escribe en store_geo_snapshots (no en store_features_ext)
y se gestiona al final como audit de estado.
"""

from __future__ import annotations

import logging
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Callable, NamedTuple

from prefect import flow, get_run_logger, task

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("sync_mensual")


class SyncJob(NamedTuple):
    feature_key: str
    location_uuid: str
    periodicidad: str


def _cargar_jobs(periodicidad: str) -> dict[str, list[SyncJob]]:
    """Lee feature_flags y devuelve {source: [SyncJob, ...]} para la periodicidad dada."""
    from src.db.store import get_conn

    conn = get_conn()
    filas = conn.execute(
        """
        SELECT ff.feature_key, ff.location_uuid, fr.source, ff.periodicidad
          FROM feature_flags ff
          JOIN feature_registry fr ON fr.feature_key = ff.feature_key
         WHERE ff.status IN ('contexto', 'active')
           AND ff.periodicidad = ?
         ORDER BY fr.source, ff.location_uuid
        """,
        [periodicidad],
    ).fetchall()

    groups: dict[str, list[SyncJob]] = defaultdict(list)
    for feature_key, location_uuid, source, per in filas:
        groups[source].append(SyncJob(feature_key, location_uuid, per))
    return dict(groups)


def _cargar_sources_lsc() -> set[str]:
    """Sources con configuración activa en location_source_config."""
    from src.db.store import get_conn

    rows = (
        get_conn()
        .execute("SELECT DISTINCT source FROM location_source_config WHERE activo = TRUE")
        .fetchall()
    )
    return {r[0] for r in rows}


def _build_ingestores(hoy: date) -> dict[str, Callable]:
    """
    Auto-descubre ingestores desde src/data_ingestion/mensual/.

    Para añadir una señal nueva:
      1. Crear src/data_ingestion/mensual/<source>.py con SOURCE, sync() y CATALOG_ENTRY.
      2. Nada más — el scanner lo registra automáticamente aquí y en Context Scout.
    """
    from src.data_ingestion.mensual import cargar_ingestores

    return cargar_ingestores()


# ── Tasks Prefect ─────────────────────────────────────────────────────────────


@task(name="ingestar-source", retries=1, retry_delay_seconds=60)
def _ingestar_source(source: str, jobs: list[SyncJob], hoy: date) -> int:
    logger = get_run_logger()
    ingestores = _build_ingestores(hoy)
    n = ingestores[source](jobs=jobs, fecha=hoy)
    logger.info("%-20s — %d fila(s) escritas (%d job(s))", source, n, len(jobs))
    return n


@task(name="cruceros-calendario")
def _cruceros_calendario(hoy: date) -> int:
    """Refresca el calendario completo de escalas (ene año-anterior → dic año-actual)."""
    logger = get_run_logger()
    try:
        from src.data_ingestion.prefetch.cruceros import sync_months

        n = sync_months(desde=(1, hoy.year - 1), hasta=(12, hoy.year))
        logger.info("cruceros-calendario — %d escalas", n)
        return n
    except Exception as exc:
        logger.warning("cruceros-calendario FAIL — %s", exc)
        return 0


@task(name="geo-audit")
def _geo_audit() -> list[str]:
    logger = get_run_logger()
    try:
        from src.data_ingestion.prefetch.geo import listar_estado

        estado = listar_estado(verbose=False)
        sin_datos = [e["nombre"] for e in estado if not e.get("tiene_datos")]
        if sin_datos:
            logger.warning(
                "Geo: %d location(s) sin snapshot Esri: %s%s",
                len(sin_datos),
                ", ".join(sin_datos[:5]),
                "..." if len(sin_datos) > 5 else "",
            )
        else:
            logger.info("Geo: todas las locations tienen snapshot Esri activo")
        return sin_datos
    except Exception as exc:
        logger.warning("Geo audit omitido: %s", exc)
        return []


# ── Flow principal ─────────────────────────────────────────────────────────────


@flow(name="sync-mensual")
def sync_mensual_flow() -> int:
    logger = get_run_logger()
    t0 = time.time()
    hoy = date.today()
    errores = 0

    logger.info("── sync_mensual START %s ─────────────────────────", hoy)

    ingestores = _build_ingestores(hoy)

    # ── Loop data-driven ──────────────────────────────────────────────────────
    try:
        jobs_por_source = _cargar_jobs("mensual")
        total = sum(len(v) for v in jobs_por_source.values())
        logger.info(
            "%d job(s) mensuales en %d fuente(s): %s",
            total,
            len(jobs_por_source),
            ", ".join(jobs_por_source.keys()) or "(ninguna)",
        )

        for source, jobs in jobs_por_source.items():
            if source not in ingestores:
                claves = ", ".join(j.feature_key for j in jobs[:3])
                logger.info(
                    "  %-20s sin ingestor — %d job(s) pendiente(s): %s%s",
                    source,
                    len(jobs),
                    claves,
                    "..." if len(jobs) > 3 else "",
                )
                continue

            try:
                _ingestar_source(source, jobs, hoy)
            except Exception as exc:
                logger.error("  %-20s FAIL — %s", source, exc)
                errores += 1

    except Exception as exc:
        logger.error("Loop mensual FAIL: %s", exc)
        errores += 1

    # ── Bootstrap: ingestores en location_source_config sin feature_flags aún ──
    # Primera ejecución: feature_flags vacío → el loop no los despacha → bootstrap los
    # llama con jobs=[] para que auto-registren sus feature_flags. Ejecuciones siguientes:
    # el set queda vacío porque ya aparecen en jobs_por_source.
    try:
        lsc_sources = _cargar_sources_lsc()
        bootstrap = lsc_sources & set(ingestores.keys()) - set(jobs_por_source.keys())
        for source in sorted(bootstrap):
            logger.info("  %-20s bootstrap (sin feature_flags aún)", source)
            try:
                _ingestar_source(source, [], hoy)
            except Exception as exc:
                logger.error("  %-20s bootstrap FAIL — %s", source, exc)
                errores += 1
    except Exception as exc:
        logger.warning("Bootstrap lsc FAIL: %s", exc)

    # ── Calendario cruceros: refresco anual independiente del feature loop ────
    _cruceros_calendario(hoy)

    # ── Geo/Esri: audit de snapshots ──────────────────────────────────────────
    _geo_audit()

    logger.info("── sync_mensual DONE (%.0fs) errores=%d ─", time.time() - t0, errores)
    return errores


def main() -> int:
    return sync_mensual_flow()


if __name__ == "__main__":
    sys.exit(main())
