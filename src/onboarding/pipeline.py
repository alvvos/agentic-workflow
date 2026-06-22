"""
Pipeline de onboarding — orquestador Prefect.

Cada nueva ubicación detectada por descargar_maestro_ubicaciones() pasa por
este pipeline. Cada agente es un @task visible en la UI de Prefect.

Fases implementadas:
  1. Quality Gate   — validación, geocodificación, bounding box
  2. Feature Router — qué fuentes aplican por país/ciudad/tenant

En cola:
  3. Ingesta paralela — weather, eventos, Esri, festivos, cruceros (ThreadPoolTaskRunner)
  4. Feature Evaluator — walk-forward WMAPE → activa feature_flags automáticamente
  5. Smoke Test       — cobertura en DB + llamada a ml_predictivo
"""

from __future__ import annotations

from prefect import flow, get_run_logger, task

from src.onboarding.feature_router import RoutingResult, enrutar
from src.onboarding.quality_gate import QualityResult, validar

# ── Agente 1: Quality Gate ─────────────────────────────────────────────────────


@task(name="quality-gate", retries=1, retry_delay_seconds=60)
def quality_gate_task(location_uuid: str) -> QualityResult:
    logger = get_run_logger()
    result = validar(location_uuid)

    geo = " [geocodificada]" if result.geocoded else ""
    coord = f"({result.lat:.5f}, {result.lon:.5f})" if result.lat else "sin coordenadas"
    logger.info("%s%s — %s", result.nombre, geo, coord)

    for issue in result.issues:
        logger.error("✗ %s", issue)
    for w in result.warnings:
        logger.warning("⚠ %s", w)

    return result


# ── Agente 2: Feature Router ───────────────────────────────────────────────────


@task(name="feature-router")
def feature_router_task(location_uuid: str) -> RoutingResult:
    logger = get_run_logger()
    routing = enrutar(location_uuid)

    logger.info("%s → fuentes activas: %s", routing.nombre, routing.fuentes)
    for fuente, motivo in routing.excluidas.items():
        logger.info("  excluida %-20s — %s", fuente, motivo)

    return routing


# ── Flow por ubicación ─────────────────────────────────────────────────────────


@flow(name="onboarding-ubicacion")
def onboarding_ubicacion(location_uuid: str) -> bool:
    """Ejecuta el pipeline completo para una ubicación nueva."""
    logger = get_run_logger()

    # Fase 1 — Quality Gate
    result = quality_gate_task(location_uuid)
    if not result.ok:
        logger.error("FAIL — %s bloqueada en Quality Gate", result.nombre)
        return False

    # Fase 2 — Feature Router
    routing = feature_router_task(location_uuid)
    logger.info("Routing OK — %d fuentes para %s", len(routing.fuentes), routing.nombre)

    # Fase 3 — Ingesta paralela (ThreadPoolTaskRunner)
    # futures = [ingesta_task.submit(location_uuid, src) for src in routing.fuentes]
    # wait(futures)

    # Fase 4 — Feature Evaluator
    # feature_eval_task(location_uuid)

    # Fase 5 — Smoke Test
    # smoke_test_task(location_uuid)

    return True


# ── Flow de entrada (trigger desde sync) ──────────────────────────────────────


@flow(name="onboarding-lote")
def onboard_nuevas_ubicaciones(location_uuids: list[str]) -> None:
    """
    Punto de entrada desde descargar_maestro_ubicaciones().
    Cada UUID lanza su propio subflow — visible como fila separada en la UI.
    """
    if not location_uuids:
        return

    logger = get_run_logger()
    logger.info("Onboarding: %d nueva(s) ubicación(es)", len(location_uuids))

    for uuid in location_uuids:
        onboarding_ubicacion(uuid)
