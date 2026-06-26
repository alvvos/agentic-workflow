"""
Agente 4 — Feature Evaluator.

Para la ubicación que acaba de pasar Quality Gate + Feature Router + Context Scout:
1. Recoge features con status='con_cobertura' que aún no tienen decisión
   (active/inactive) para esta ubicación.
2. Evalúa cada una con walk-forward WMAPE (reutiliza eval_features.py).
3. Auto-activa (status='active') las que mejoran WMAPE en ≥ WMAPE_DELTA_THRESHOLD.
4. Las que no mejoran quedan 'inactive' con wmape_delta registrado.
5. No toca features en status='contexto' — esas las evaluará este mismo agente
   cuando los ingestores de Context Scout hayan rellenado store_features_ext.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np

log = logging.getLogger(__name__)

# Umbral de activación automática.
# Una feature se activa si mejora el WMAPE medio en al menos este valor.
# -0.005 = -0.5 pp — conservador: solo activa mejoras claras y consistentes.
WMAPE_DELTA_THRESHOLD = -0.005

# Parámetros del walk-forward por defecto para onboarding automático.
# Ventanas más cortas que en el notebook para no bloquear el pipeline.
_HORIZONTE_DEFAULT = 21
_SPLITS_DEFAULT = 3


@dataclass
class FeatureEvalResult:
    location_uuid: str
    nombre: str
    evaluadas: list[str] = field(default_factory=list)
    activadas: list[str] = field(default_factory=list)
    inactivas: list[str] = field(default_factory=list)
    sin_datos: list[str] = field(default_factory=list)
    sin_historial: bool = False  # True si fact_visitas tiene < MIN_TRAIN_ROWS
    error: str | None = None


def _features_pendientes(conn, location_uuid: str) -> list[str]:
    """
    Devuelve feature_keys con cobertura suficiente y sin decisión para esta ubicación.
    Excluye explícitamente las que ya tienen status='active' o 'inactive'.
    Las features 'contexto' (Context Scout) se dejan para cuando tengan datos.
    """
    rows = conn.execute(
        """
        SELECT fr.feature_key
          FROM feature_registry fr
         WHERE fr.status = 'con_cobertura'
           AND fr.feature_key NOT IN (
               SELECT feature_key FROM feature_flags
                WHERE location_uuid = ?
                  AND status IN ('active', 'inactive')
           )
         ORDER BY fr.feature_key
        """,
        [location_uuid],
    ).fetchall()
    return [r[0] for r in rows]


def _auto_write_flags(conn, results: list[dict], threshold: float) -> tuple[list[str], list[str]]:
    """
    Escribe feature_flags con decisión automática:
      mean_delta ≤ threshold → 'active'
      mean_delta >  threshold → 'inactive'

    ON CONFLICT: actualiza wmape_delta + evaluated_at pero NO cambia status
    si ya fue decidido externamente (ej. notebook o una ejecución previa).
    Devuelve (activadas, inactivas).
    """
    by_loc: dict[tuple, list[float]] = {}
    for r in results:
        by_loc.setdefault((r["feature_key"], r["location_uuid"]), []).append(r["wmape_delta"])

    activadas: list[str] = []
    inactivas: list[str] = []

    for (feat_key, loc_uuid), deltas in by_loc.items():
        mean_delta = float(np.mean(deltas))
        status = "active" if mean_delta <= threshold else "inactive"

        conn.execute(
            """
            INSERT INTO feature_flags
              (feature_key, location_uuid, status, wmape_delta, evaluated_at)
            VALUES (?, ?, ?, ?, NOW())
            ON CONFLICT (feature_key, location_uuid) DO UPDATE
                SET wmape_delta  = excluded.wmape_delta,
                    evaluated_at = NOW()
            """,
            [feat_key, loc_uuid, status, mean_delta],
        )

        if status == "active":
            activadas.append(feat_key)
        else:
            inactivas.append(feat_key)

    return activadas, inactivas


def evaluar(
    location_uuid: str,
    horizonte: int = _HORIZONTE_DEFAULT,
    n_splits: int = _SPLITS_DEFAULT,
    fecha_corte: date | None = None,
    threshold: float = WMAPE_DELTA_THRESHOLD,
) -> FeatureEvalResult:
    """
    Evalúa y auto-activa features para una ubicación recién onboardeada.
    Reutiliza _evaluate_feature() de src/lab/eval_features.py sin duplicar lógica.
    """
    from src.db.store import get_conn
    from src.onboarding._eval_core import MIN_TRAIN_ROWS, _evaluate_feature, _write_results

    conn = get_conn()

    nombre_row = conn.execute(
        "SELECT nombre FROM dim_ubicaciones WHERE location_uuid = ?", [location_uuid]
    ).fetchone()
    nombre = nombre_row[0] if nombre_row else location_uuid

    result = FeatureEvalResult(location_uuid=location_uuid, nombre=nombre)

    if not fecha_corte:
        row = conn.execute(
            "SELECT MAX(fecha) FROM fact_visitas WHERE location_uuid = ?", [location_uuid]
        ).fetchone()
        fecha_corte = row[0] if row and row[0] else date.today()

    # Comprobación rápida de historial mínimo
    n_dias = conn.execute(
        "SELECT COUNT(DISTINCT fecha) FROM fact_visitas WHERE location_uuid = ?",
        [location_uuid],
    ).fetchone()[0]

    if n_dias < MIN_TRAIN_ROWS:
        log.info(
            "Feature Eval: %s — solo %d días en fact_visitas (mínimo %d) — evaluación aplazada",
            nombre,
            n_dias,
            MIN_TRAIN_ROWS,
        )
        result.sin_historial = True
        return result

    features = _features_pendientes(conn, location_uuid)
    if not features:
        log.info("Feature Eval: %s — sin features pendientes de evaluación", nombre)
        return result

    log.info(
        "Feature Eval: %s — evaluando %d feature(s): %s",
        nombre,
        len(features),
        ", ".join(features),
    )

    all_results: list[dict] = []

    for feat in features:
        rows = _evaluate_feature(
            conn,
            feature_key=feat,
            location_uuid=location_uuid,
            fecha_corte=fecha_corte,
            horizonte=horizonte,
            n_splits=n_splits,
        )
        if rows:
            all_results.extend(rows)
            result.evaluadas.append(feat)
        else:
            result.sin_datos.append(feat)
            log.info("  %s — sin datos suficientes en store_features_ext", feat)

    if all_results:
        _write_results(conn, all_results)
        activadas, inactivas = _auto_write_flags(conn, all_results, threshold)
        result.activadas = activadas
        result.inactivas = inactivas

        for feat in activadas:
            delta = float(
                np.mean([r["wmape_delta"] for r in all_results if r["feature_key"] == feat])
            )
            log.info("  ACTIVADA ✓  %s  (delta medio: %+.2f pp)", feat, delta * 100)
        for feat in inactivas:
            delta = float(
                np.mean([r["wmape_delta"] for r in all_results if r["feature_key"] == feat])
            )
            log.info("  inactiva    %s  (delta medio: %+.2f pp)", feat, delta * 100)

    return result
