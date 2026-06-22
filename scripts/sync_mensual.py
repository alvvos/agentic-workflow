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


def _build_ingestores(hoy: date) -> dict[str, Callable]:
    """
    Registra los ingestores disponibles.
    Interfaz: sync(jobs: list[SyncJob], fecha: date) -> int  (filas escritas)

    Para añadir una fuente nueva:
      1. Implementar src/data_ingestion/prefetch/<source>.py con sync(jobs, fecha) -> int
      2. Añadir el import + entrada al dict aquí. Nada más.
    """
    ingestores: dict[str, Callable] = {}

    # ── Cruceros ──────────────────────────────────────────────────────────────
    try:
        from src.data_ingestion.prefetch.cruceros import sync_months

        def _cruceros_sync(jobs: list[SyncJob], fecha: date) -> int:
            # jobs filtra las ubicaciones con cruceros activo (solo Málaga);
            # sync_months ya sabe internamente a qué locations aplicar.
            return sync_months(desde=(1, fecha.year - 1), hasta=(fecha.month, fecha.year))

        ingestores["cruceros"] = _cruceros_sync
    except ImportError:
        pass

    # ── Fuentes Context Scout — descomentar cuando el ingestor esté implementado ─
    # from src.data_ingestion.prefetch.ine   import sync as ine_sync;   ingestores["ine"]   = ine_sync
    # from src.data_ingestion.prefetch.sepe  import sync as sepe_sync;  ingestores["sepe"]  = sepe_sync
    # from src.data_ingestion.prefetch.inegi import sync as inegi_sync; ingestores["inegi"] = inegi_sync
    # from src.data_ingestion.prefetch.ons   import sync as ons_sync;   ingestores["ons"]   = ons_sync
    # from src.data_ingestion.prefetch.insee import sync as insee_sync; ingestores["insee"] = insee_sync

    return ingestores


def main() -> int:
    t0 = time.time()
    hoy = date.today()
    log.info("── sync_mensual START %s ─────────────────────────", hoy)
    errores = 0

    ingestores = _build_ingestores(hoy)

    # ── Loop data-driven ──────────────────────────────────────────────────────
    try:
        jobs_por_source = _cargar_jobs("mensual")
        total = sum(len(v) for v in jobs_por_source.values())
        log.info(
            "%d job(s) mensuales en %d fuente(s): %s",
            total,
            len(jobs_por_source),
            ", ".join(jobs_por_source.keys()) or "(ninguna)",
        )

        for source, jobs in jobs_por_source.items():
            if source not in ingestores:
                claves = ", ".join(j.feature_key for j in jobs[:3])
                log.info(
                    "  %-20s sin ingestor — %d job(s) pendiente(s): %s%s",
                    source,
                    len(jobs),
                    claves,
                    "..." if len(jobs) > 3 else "",
                )
                continue

            try:
                n = ingestores[source](jobs=jobs, fecha=hoy)
                log.info("  %-20s OK — %d fila(s) escritas (%d job(s))", source, n, len(jobs))
            except Exception as exc:
                log.error("  %-20s FAIL — %s", source, exc)
                errores += 1

    except Exception as exc:
        log.error("Loop mensual FAIL: %s", exc)
        errores += 1

    # ── Geo/Esri: audit de snapshots ──────────────────────────────────────────
    # No entra en el loop porque escribe en store_geo_snapshots, no store_features_ext.
    try:
        from src.data_ingestion.prefetch.geo import listar_estado

        estado = listar_estado(verbose=False)
        sin_datos = [e["nombre"] for e in estado if not e.get("tiene_datos")]
        if sin_datos:
            log.warning(
                "Geo: %d location(s) sin snapshot Esri: %s%s",
                len(sin_datos),
                ", ".join(sin_datos[:5]),
                "..." if len(sin_datos) > 5 else "",
            )
        else:
            log.info("Geo: todas las locations tienen snapshot Esri activo")
    except Exception as exc:
        log.warning("Geo audit omitido: %s", exc)

    log.info("── sync_mensual DONE (%.0fs) errores=%d ─", time.time() - t0, errores)
    return errores


if __name__ == "__main__":
    sys.exit(main())
