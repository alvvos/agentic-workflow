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
    format='%(asctime)s [%(levelname)s] %(message)s',
    stream=sys.stdout,
)
log = logging.getLogger('sync_mensual')


def main() -> int:
    t0  = time.time()
    hoy = date.today()
    log.info(f'── sync_mensual START {hoy} ─────────────────────────')
    errores = 0

    # ── Fase A: Cruceros ──────────────────────────────────────────────
    log.info('Fase A — Cruceros sync (Jan año anterior → mes actual)')
    try:
        from src.data_ingestion.prefetch.cruceros import sync_months

        # Desde Enero del año anterior para garantizar histórico completo
        m, y = hoy.month, hoy.year
        desde = (1, y - 1)   # Jan del año anterior

        n = sync_months(desde=desde, hasta=(m, y))
        log.info(f'Fase A OK — {n} escalas procesadas')
    except Exception as exc:
        log.error(f'Fase A FAILED: {exc}')
        errores += 1

    # ── Fase B: Geo/Esri — estado de snapshots ────────────────────────
    log.info('Fase B — Geo estado (Esri pendiente de contrato)')
    try:
        from src.data_ingestion.prefetch.geo import listar_estado
        estado = listar_estado(verbose=False)
        sin_datos = [e['nombre'] for e in estado if not e.get('tiene_datos')]
        if sin_datos:
            log.warning(
                f'{len(sin_datos)} locations sin snapshot Esri: '
                f"{', '.join(sin_datos[:5])}{'...' if len(sin_datos) > 5 else ''}"
            )
        else:
            log.info('Todas las locations tienen snapshot Esri activo')
    except Exception as exc:
        log.warning(f'Fase B omitida: {exc}')

    log.info(f'── sync_mensual DONE ({time.time() - t0:.0f}s) errores={errores} ─')
    return errores


if __name__ == '__main__':
    sys.exit(main())
