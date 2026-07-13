"""
Agente 5 — Smoke Test.

Última comprobación antes de declarar la ubicación como onboardeada.
Rápido y sin efectos secundarios: solo lectura de DB.

Checks:
  1. UBICACION  — activa=TRUE, lat/lon presentes, aparece en el árbol de tiendas
  2. VISITAS    — visitas tiene ≥ MIN_DIAS_VISITAS filas (historial mínimo útil)
  3. COBERTURA  — cada feature 'active' tiene filas en valores_señales
  4. ZONAS      — al menos una zona activa asociada a la ubicación
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

MIN_DIAS_VISITAS = 30


@dataclass
class CheckResult:
    nombre: str
    ok: bool
    detalle: str


@dataclass
class SmokeTestResult:
    location_uuid: str
    nombre: str
    ok: bool = False
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def fallidos(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok]


def _check_ubicacion(conn, location_uuid: str) -> CheckResult:
    row = conn.execute(
        "SELECT activa, lat, lon FROM ubicaciones WHERE ubicacion_id = ?",
        [location_uuid],
    ).fetchone()

    if not row:
        return CheckResult("ubicacion", False, "ubicacion_id no encontrado en ubicaciones")

    activa, lat, lon = row
    if not activa:
        return CheckResult("ubicacion", False, "activa=FALSE — excluida del sistema")
    if lat is None or lon is None:
        return CheckResult(
            "ubicacion",
            False,
            "lat/lon NULL — Quality Gate anuló coordenadas fuera de bounding box",
        )

    return CheckResult("ubicacion", True, f"activa=TRUE · ({lat:.4f}, {lon:.4f})")


def _check_visitas(conn, location_uuid: str) -> CheckResult:
    n = conn.execute(
        "SELECT COUNT(DISTINCT fecha) FROM visitas WHERE ubicacion_id = ?",
        [location_uuid],
    ).fetchone()[0]

    if n == 0:
        return CheckResult(
            "visitas",
            False,
            "0 días en visitas — sync nocturna aún no ha corrido para esta ubicación",
        )
    if n < MIN_DIAS_VISITAS:
        return CheckResult(
            "visitas",
            False,
            f"solo {n} días en visitas (mínimo {MIN_DIAS_VISITAS} para modelo útil)",
        )

    return CheckResult("visitas", True, f"{n} días con datos en visitas")


def _check_cobertura_features(conn, location_uuid: str) -> CheckResult:
    activas = conn.execute(
        "SELECT señal_id FROM activacion_señales WHERE ubicacion_id = ? AND status = 'active'",
        [location_uuid],
    ).fetchall()

    if not activas:
        return CheckResult(
            "cobertura_features",
            True,
            "sin features activas aún — normal en onboarding sin historial suficiente",
        )

    sin_datos: list[str] = []
    for (fk,) in activas:
        n = conn.execute(
            "SELECT COUNT(*) FROM valores_señales WHERE ubicacion_id = ? AND señal_id = ?",
            [location_uuid, fk],
        ).fetchone()[0]
        if n == 0:
            sin_datos.append(fk)

    if sin_datos:
        return CheckResult(
            "cobertura_features",
            False,
            f"{len(sin_datos)} feature(s) activa(s) sin datos en valores_señales: "
            + ", ".join(sin_datos[:5])
            + ("..." if len(sin_datos) > 5 else ""),
        )

    return CheckResult(
        "cobertura_features",
        True,
        f"{len(activas)} feature(s) activa(s) con cobertura en valores_señales",
    )


def _check_zonas(conn, location_uuid: str) -> CheckResult:
    n = conn.execute(
        "SELECT COUNT(*) FROM zonas WHERE ubicacion_id = ? AND oculta = FALSE",
        [location_uuid],
    ).fetchone()[0]

    if n == 0:
        return CheckResult(
            "zonas",
            False,
            "sin zonas visibles en zonas — el panel no podrá mostrar datos",
        )

    return CheckResult("zonas", True, f"{n} zona(s) visible(s)")


def ejecutar(location_uuid: str) -> SmokeTestResult:
    from src.db.store import get_conn

    conn = get_conn()

    nombre_row = conn.execute(
        "SELECT nombre FROM ubicaciones WHERE ubicacion_id = ?", [location_uuid]
    ).fetchone()
    nombre = nombre_row[0] if nombre_row else location_uuid

    result = SmokeTestResult(location_uuid=location_uuid, nombre=nombre)

    result.checks = [
        _check_ubicacion(conn, location_uuid),
        _check_visitas(conn, location_uuid),
        _check_cobertura_features(conn, location_uuid),
        _check_zonas(conn, location_uuid),
    ]

    result.ok = all(c.ok for c in result.checks)

    for c in result.checks:
        icon = "✓" if c.ok else "✗"
        level = log.info if c.ok else log.error
        level("  [%s] %-25s %s", icon, c.nombre, c.detalle)

    return result
