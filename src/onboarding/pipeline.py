"""
Pipeline de onboarding — orquestador Prefect.

Cada nueva ubicación detectada por descargar_maestro_ubicaciones() pasa por
este pipeline. Cada agente es un @task visible en la UI de Prefect.

Fases implementadas:
  1. Quality Gate      — validación, geocodificación, bounding box
  2. Feature Router    — qué fuentes aplican por país/ciudad/tenant
  3. Context Scout     — descubre fuentes abiertas para la isócrona y las registra
                         en feature_registry + feature_flags (status='contexto')
  4. Feature Evaluator — walk-forward WMAPE sobre features con cobertura;
                         auto-activa las que mejoran ≥ 0.5 pp

En cola:
  5. Smoke Test — cobertura en DB + llamada a ml_predictivo
"""

from __future__ import annotations

from prefect import flow, get_run_logger, task

from src.onboarding.context_scout import ScoutResult, descubrir_fuentes, registrar_fuentes
from src.onboarding.feature_eval import FeatureEvalResult, evaluar
from src.onboarding.feature_router import RoutingResult, enrutar
from src.onboarding.quality_gate import QualityResult, validar
from src.onboarding.smoke_test import SmokeTestResult
from src.onboarding.smoke_test import ejecutar as smoke_ejecutar

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


# ── Activación de clima ───────────────────────────────────────────────────────


@task(name="activar-clima")
def activar_clima_task(location_uuid: str, routing: RoutingResult) -> int:
    """Crea feature_flags activos para clima y lanza prefetch si weather fue asignado."""
    if "weather" not in routing.fuentes:
        return 0

    from src.db.store import get_conn

    conn = get_conn()

    climate_keys = [
        r[0]
        for r in conn.execute(
            "SELECT feature_key FROM feature_registry WHERE source = 'open_meteo'"
        ).fetchall()
    ]
    if not climate_keys:
        return 0

    conn.executemany(
        "INSERT INTO feature_flags (feature_key, location_uuid, status, periodicidad) "
        "VALUES (?, ?, 'active', 'diaria') "
        "ON CONFLICT (feature_key, location_uuid) DO UPDATE SET status = 'active'",
        [(fk, location_uuid) for fk in climate_keys],
    )

    from src.data_ingestion.sync_diaria import run_all as _run_all

    result_all = _run_all(
        location_uuid=location_uuid,
        only={"weather"},
        max_age_hours=0,
        verbose=False,
    )
    result = result_all.get("weather", {})
    return result.get(location_uuid, 0)


# ── Agente 3: Context Scout ───────────────────────────────────────────────────


@task(name="context-scout", retries=1, retry_delay_seconds=30)
def context_scout_task(location_uuid: str) -> ScoutResult:
    result = descubrir_fuentes(location_uuid)
    if result.error:
        return result
    return registrar_fuentes(result)


# ── Agente 4: Feature Evaluator ───────────────────────────────────────────────


@task(name="feature-evaluator", retries=1, retry_delay_seconds=30)
def feature_eval_task(location_uuid: str) -> FeatureEvalResult:
    return evaluar(location_uuid)


# ── Agente 5: Smoke Test ──────────────────────────────────────────────────────


@task(name="smoke-test")
def smoke_test_task(location_uuid: str) -> SmokeTestResult:
    return smoke_ejecutar(location_uuid)


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

    # Fase 2b — Activar clima (flags + prefetch histórico)
    dias_clima = activar_clima_task(location_uuid, routing)
    if "weather" in routing.fuentes:
        logger.info(
            "Clima activado — %d días históricos escritos para %s", dias_clima, routing.nombre
        )

    # Fase 3 — Context Scout
    scout = context_scout_task(location_uuid)
    if scout.error:
        logger.warning("Context Scout warning — %s: %s", scout.nombre, scout.error)
    else:
        logger.info(
            "Context Scout OK — %d fuente(s) registrada(s) para %s",
            scout.n_registradas,
            scout.nombre,
        )
        for src in scout.seleccionadas:
            logger.info("  + %s (%s/%s)", src.feature_key, src.source, src.periodicidad)
        for desc in scout.descartadas:
            logger.info("  ✗ %s — %s", desc.get("feature_key", "?"), desc.get("razon_descarte", ""))

    # Fase 4 — Feature Evaluator
    eval_result = feature_eval_task(location_uuid)
    if eval_result.sin_historial:
        logger.info(
            "Feature Eval aplazada — %s aún no tiene suficiente historial en fact_visitas",
            eval_result.nombre,
        )
    else:
        logger.info(
            "Feature Eval OK — %s: %d evaluada(s), %d activada(s), %d inactiva(s)",
            eval_result.nombre,
            len(eval_result.evaluadas),
            len(eval_result.activadas),
            len(eval_result.inactivas),
        )

    # Fase 5 — Smoke Test
    smoke = smoke_test_task(location_uuid)
    if smoke.ok:
        logger.info("ONBOARDING COMPLETO ✓ — %s lista para producción", smoke.nombre)
    else:
        for c in smoke.fallidos:
            logger.error("  [✗] %s — %s", c.nombre, c.detalle)
        logger.error(
            "ONBOARDING INCOMPLETO — %s: %d check(s) fallido(s)",
            smoke.nombre,
            len(smoke.fallidos),
        )

    return smoke.ok


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
