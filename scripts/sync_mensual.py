#!/usr/bin/env python3
"""
Orquestador mensual — ejecutado por systemd timer el día 1 de cada mes a las 03:00.

Fase A: Cruceros — mes actual + 2 meses anteriores (el puerto actualiza con retraso)
Fase B: Geo/Esri — lista estado de snapshots pendientes hasta que llegue el contrato
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("sync_mensual")


def main() -> int:
    t0 = time.time()
    hoy = date.today()
    log.info(f"── sync_mensual START {hoy} ─────────────────────────")
    errores = 0

    # ── Fase A: Cruceros ──────────────────────────────────────────────
    log.info("Fase A — Cruceros sync (Jan año anterior → mes actual)")
    try:
        from src.data_ingestion.prefetch.cruceros import sync_months

        # Desde Enero del año anterior para garantizar histórico completo
        m, y = hoy.month, hoy.year
        desde = (1, y - 1)  # Jan del año anterior

        n = sync_months(desde=desde, hasta=(m, y))
        log.info(f"Fase A OK — {n} escalas procesadas")
    except Exception as exc:
        log.error(f"Fase A FAILED: {exc}")
        errores += 1

    # ── Fase B: Geo/Esri — estado de snapshots ────────────────────────
    log.info("Fase B — Geo estado (Esri pendiente de contrato)")
    try:
        from src.data_ingestion.prefetch.geo import listar_estado

        estado = listar_estado(verbose=False)
        sin_datos = [e["nombre"] for e in estado if not e.get("tiene_datos")]
        if sin_datos:
            log.warning(
                f"{len(sin_datos)} locations sin snapshot Esri: "
                f"{', '.join(sin_datos[:5])}{'...' if len(sin_datos) > 5 else ''}"
            )
        else:
            log.info("Todas las locations tienen snapshot Esri activo")
    except Exception as exc:
        log.warning(f"Fase B omitida: {exc}")

    # ── Fase C: Features contexto — despacho por source ───────────────
    # Lee feature_flags WHERE status IN ('contexto','active') AND periodicidad='mensual'
    # y llama al ingestor correspondiente cuando esté disponible.
    # Los ingestores se añaden al diccionario _INGESTORES a medida que se implementan.
    log.info("Fase C — Features contexto (Context Scout)")
    _INGESTORES: dict[str, object] = {
        # 'ine':   src.data_ingestion.prefetch.ine.sync,     ← pendiente
        # 'sepe':  src.data_ingestion.prefetch.sepe.sync,    ← pendiente
        # 'inegi': src.data_ingestion.prefetch.inegi.sync,   ← pendiente
        # 'ons':   src.data_ingestion.prefetch.ons.sync,     ← pendiente
    }
    try:
        from src.db.store import get_conn

        conn = get_conn()
        filas = conn.execute(
            """
            SELECT ff.feature_key, ff.location_uuid, fr.source, ff.periodicidad
            FROM feature_flags ff
            JOIN feature_registry fr ON fr.feature_key = ff.feature_key
            WHERE ff.status IN ('contexto', 'active')
              AND ff.periodicidad = 'mensual'
            ORDER BY fr.source, ff.location_uuid
            """
        ).fetchall()

        pendientes: dict[str, list[str]] = {}
        for feature_key, location_uuid, source, _ in filas:
            if source in _INGESTORES:
                try:
                    _INGESTORES[source](
                        feature_key=feature_key, location_uuid=location_uuid, fecha=hoy
                    )
                    log.info(f"Fase C OK — {source}/{feature_key} {location_uuid}")
                except Exception as exc:
                    log.error(f"Fase C FAIL — {source}/{feature_key}: {exc}")
                    errores += 1
            else:
                pendientes.setdefault(source, []).append(feature_key)

        if pendientes:
            for source, keys in pendientes.items():
                log.info(
                    f"Fase C — source={source!r} sin ingestor ({len(keys)} feature(s) pendientes: "
                    f"{', '.join(keys[:3])}{'...' if len(keys) > 3 else ''})"
                )
    except Exception as exc:
        log.warning(f"Fase C omitida: {exc}")

    log.info(f"── sync_mensual DONE ({time.time() - t0:.0f}s) errores={errores} ─")
    return errores


if __name__ == "__main__":
    sys.exit(main())
