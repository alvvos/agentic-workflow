#!/usr/bin/env python3
"""
Orquestador nocturno — ejecutado por systemd timer a las 02:00.

Fase 0: Árbol      — actualiza orgs/ubicaciones/zonas desde Aitanna API
Fase A: Aitanna    — signals operacionales (sincronizador, incremental)
Fase B: Contexto   — weather + eventos diarios (excluye cruceros: mensual)

El script devuelve 0 si todo va bien, >0 si alguna fase falla.
Las fases son independientes: un fallo en A no cancela B.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("sync_noche")


def main() -> int:
    t0 = time.time()
    log.info("── sync_noche START ─────────────────────────────────")
    errores = 0

    # ── Fase 0: Árbol de ubicaciones ─────────────────────────────────
    log.info("Fase 0 — Actualizar árbol de ubicaciones (Aitanna API)")
    try:
        from src.data_ingestion.actualizar_arbol_ubicaciones import descargar_maestro_ubicaciones

        descargar_maestro_ubicaciones()
        log.info("Fase 0 OK")
    except Exception as exc:
        log.error(f"Fase 0 FAILED: {exc}")
        errores += 1

    # ── Fase A: Aitanna ───────────────────────────────────────────────
    log.info("Fase A — Aitanna sync (incremental)")
    try:
        from src.data_ingestion.sincronizador import actualizar_datos

        actualizar_datos()
        log.info("Fase A OK")
    except Exception as exc:
        log.error(f"Fase A FAILED: {exc}")
        errores += 1

    # ── Fase B: Contexto exterior (periodicidad=diaria) ───────────────
    log.info("Fase B — Prefetch contexto (excluye cruceros)")
    try:
        from src.data_ingestion.prefetch.run_all import run as prefetch_run

        results = prefetch_run(
            skip={"cruceros"},
            max_age_hours=20,  # salta si ya corrió en las últimas 20h
            verbose=True,
        )
        total = sum(v for src_stats in results.values() for v in src_stats.values())
        log.info(f"Fase B OK — {total} registros escritos")
    except Exception as exc:
        log.error(f"Fase B FAILED: {exc}")
        errores += 1

    log.info(f"── sync_noche DONE ({time.time() - t0:.0f}s) errores={errores} ─")
    return errores


if __name__ == "__main__":
    sys.exit(main())
