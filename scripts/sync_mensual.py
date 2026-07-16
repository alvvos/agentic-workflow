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
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, NamedTuple

from prefect import flow, get_run_logger, task

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_LOG_FILE = _ROOT / "logs" / "miniso_sync.log"
_LOG_FILE.parent.mkdir(exist_ok=True)

_fmt = logging.Formatter("%(asctime)s [%(levelname)-8s] %(name)-22s %(message)s")

_fh = RotatingFileHandler(_LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=10, encoding="utf-8")
_fh.setFormatter(_fmt)
_fh.setLevel(logging.DEBUG)

_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
_sh.setLevel(logging.INFO)

logging.basicConfig(level=logging.DEBUG, handlers=[_fh, _sh])
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
log = logging.getLogger("sync_mensual")


class SyncJob(NamedTuple):
    feature_key: str
    location_uuid: str
    periodicidad: str


def _cargar_jobs(periodicidad: str) -> dict[str, list[SyncJob]]:
    """Lee activacion_señales y devuelve {fuente: [SyncJob, ...]} para la periodicidad dada."""
    from src.db.store import get_conn

    conn = get_conn()
    filas = conn.execute(
        """
        SELECT ff.señal_id, ff.ubicacion_id, fr.fuente, ff.periodicidad
          FROM activacion_señales ff
          JOIN señales fr ON fr.señal_id = ff.señal_id
         WHERE ff.status IN ('contexto', 'active')
           AND ff.periodicidad = ?
         ORDER BY fr.fuente, ff.ubicacion_id
        """,
        [periodicidad],
    ).fetchall()

    groups: dict[str, list[SyncJob]] = defaultdict(list)
    for señal_id, ubicacion_id, fuente, per in filas:
        groups[fuente].append(SyncJob(señal_id, ubicacion_id, per))
    return dict(groups)


def _cargar_sources_lsc() -> set[str]:
    """Sources con configuración activa en config_fuentes."""
    from src.db.store import get_conn

    rows = (
        get_conn()
        .execute("SELECT DISTINCT fuente FROM config_fuentes WHERE activo = TRUE")
        .fetchall()
    )
    return {r[0] for r in rows}


def _build_ingestores(hoy: date) -> dict[str, Callable]:
    """
    Construye {source: adapter_fn} leyendo las fuentes mensuales activas de la DB.
    Cada adapter_fn acepta (jobs, fecha) y delega en el conector correspondiente.
    """
    import importlib

    from src.data_ingestion._common import get_configured_locations, get_source_config
    from src.db.store import get_conn

    rows = (
        get_conn()
        .execute(
            "SELECT fuente, config FROM fuentes WHERE periodicidad = 'mensual' AND activo = TRUE"
        )
        .fetchall()
    )

    def _make_adapter(fuente_nombre: str, config: dict) -> Callable | None:
        tipo = config.get("tipo_conector") if config else None
        if not tipo:
            return None
        try:
            conector = importlib.import_module(f"src.conectores.{tipo}")
        except ModuleNotFoundError:
            return None

        def _adapter(jobs, fecha):
            total = 0
            for lu, params in get_configured_locations(fuente_nombre):
                cfg = get_source_config(fuente_nombre, params)
                try:
                    total += conector.sync(lu, cfg, True)
                except Exception as e:
                    log = logging.getLogger("sync_mensual")
                    log.warning("  [%s] %s ERROR — %s", fuente_nombre, lu, e)
            return total

        return _adapter

    ingestores = {}
    for fuente_nombre, config in rows:
        adapter = _make_adapter(fuente_nombre, config)
        if adapter is not None:
            ingestores[fuente_nombre] = adapter
    return ingestores


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
    """Refresca el calendario completo de escalas (ene anyo-anterior → dic anyo-actual)."""
    logger = get_run_logger()
    try:
        from src.data_ingestion._common import get_configured_locations
        from src.data_ingestion.sync_diaria import sync_cruceros_months

        total = 0
        for loc_uuid, params in get_configured_locations("cruceros"):
            ajax_url = params.get("ajax_url", "")
            if not ajax_url:
                continue
            total += sync_cruceros_months(
                location_uuid=loc_uuid,
                ajax_url=ajax_url,
                pais_codigo=params.get("pais_codigo", "ES"),
                desde=(1, hoy.year - 1),
                hasta=(12, hoy.year),
            )
        n = total
        logger.info("cruceros-calendario — %d escalas", n)
        return n
    except Exception as exc:
        logger.warning("cruceros-calendario FAIL — %s", exc)
        return 0


@task(name="geo-enriquecer")
def _geo_enriquecer(hoy: date) -> int:
    logger = get_run_logger()
    try:
        from src.data_ingestion.esri_client import fetch_geoenrich
        from src.data_ingestion.geo import calcular_scores_poi, ingestar_snapshot_esri
        from src.db.store import get_conn

        rows = (
            get_conn()
            .execute(
                "SELECT ubicacion_id, nombre, lat, lon FROM ubicaciones "
                "WHERE activa = TRUE AND lat IS NOT NULL AND lon IS NOT NULL"
            )
            .fetchall()
        )

        ok = errores = 0
        for ubicacion_id, nombre, lat, lon in rows:
            try:
                valores = fetch_geoenrich(ubicacion_id, lat=lat, lon=lon)
                valores.update(calcular_scores_poi(ubicacion_id))
                res = ingestar_snapshot_esri(ubicacion_id, valores, str(hoy))
                tipo = "primera" if res["primera_entrega"] else "actualización"
                logger.info("  [geo] %-40s — %s, %d features", nombre, tipo, res["n_features"])
                ok += 1
            except Exception as exc:
                logger.warning("  [geo] %-40s ERROR — %s", nombre, exc)
                errores += 1

        logger.info("Geo enriquecimiento: %d ok, %d errores", ok, errores)
        return ok
    except Exception as exc:
        logger.warning("Geo enriquecimiento FAIL — %s", exc)
        return 0


@task(name="geo-audit")
def _geo_audit() -> list[str]:
    logger = get_run_logger()
    try:
        from src.data_ingestion.geo import listar_estado

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
    try:
        _cruceros_calendario(hoy)
    except Exception as exc:
        logger.warning("cruceros-calendario FAIL (no crítico): %s", exc)

    # ── Geo/Esri: enriquecimiento mensual + audit ─────────────────────────────
    try:
        _geo_enriquecer(hoy)
    except Exception as exc:
        logger.warning("geo-enriquecer FAIL (no crítico): %s", exc)
    try:
        _geo_audit()
    except Exception as exc:
        logger.warning("geo-audit FAIL (no crítico): %s", exc)

    logger.info("── sync_mensual DONE (%.0fs) errores=%d ─", time.time() - t0, errores)
    return errores


def main() -> int:
    return sync_mensual_flow()


if __name__ == "__main__":
    sys.exit(main())
