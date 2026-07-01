#!/usr/bin/env python3
"""
Orquestador nocturno — ejecutado por systemd timer a las 02:00.

Fase 0: Árbol    — actualiza orgs/ubicaciones/zonas desde Aitanna API
Fase A: Aitanna  — signals operacionales (sincronizador, incremental)
Fase B: Diaria   — weather + eventos + cruceros (todos los ingestores en diaria/)
Fase C: Mensual  — metro, INE, puertos, Esri Places (respetan max_age_hours propio)

Las fases son independientes: un fallo en una no cancela las siguientes.
El script devuelve 0 si todo va bien, >0 si alguna fase falla.
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

    # ── Fase 0: Árbol de ubicaciones ─────────────────────────────────────────
    log.info("Fase 0 — Actualizar árbol de ubicaciones (Aitanna API)")
    try:
        from src.data_ingestion.actualizar_arbol_ubicaciones import descargar_maestro_ubicaciones

        descargar_maestro_ubicaciones()
        log.info("Fase 0 OK")
    except Exception as exc:
        log.error(f"Fase 0 FAILED: {exc}")
        errores += 1

    # ── Fase A: Aitanna ───────────────────────────────────────────────────────
    log.info("Fase A — Aitanna sync (incremental)")
    try:
        from src.data_ingestion.sincronizador import actualizar_datos

        actualizar_datos()
        log.info("Fase A OK")
    except Exception as exc:
        log.error(f"Fase A FAILED: {exc}")
        errores += 1

    # ── Fase B: Ingestores diarios ────────────────────────────────────────────
    log.info("Fase B — Ingestores diarios (weather, eventos, cruceros…)")
    try:
        from src.data_ingestion.diaria import run_all

        results_b = run_all(
            skip=set(),
            max_age_hours=20,  # salta si ya corrió en las últimas 20h
            verbose=True,
        )
        total_b = sum(v for src_stats in results_b.values() for v in src_stats.values())
        log.info(f"Fase B OK — {total_b} registros escritos")
    except Exception as exc:
        log.error(f"Fase B FAILED: {exc}")
        errores += 1

    # ── Fase C: Ingestores mensuales ──────────────────────────────────────────
    log.info("Fase C — Ingestores mensuales (metro, INE, puertos…)")
    try:
        from src.data_ingestion.mensual import sync_all

        results_c = sync_all(
            max_age_hours=168,  # semanal por defecto (datos con lag de días)
            verbose=True,
        )
        total_c = sum(v for src_stats in results_c.values() for v in src_stats.values())
        log.info(f"Fase C OK — {total_c} registros escritos")
    except Exception as exc:
        log.error(f"Fase C FAILED: {exc}")
        errores += 1

    log.info(f"── sync_noche DONE ({time.time() - t0:.0f}s) errores={errores} ─")
    return errores


if __name__ == "__main__":
    sys.exit(main())
