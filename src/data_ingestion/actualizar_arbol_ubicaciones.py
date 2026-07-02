"""
Detección de ubicaciones nuevas y disparo automático del pipeline de onboarding.

descargar_maestro_ubicaciones() es el punto de entrada desde sync_noche.py (Fase 0).

Criterio de "nueva": ubicacion con activa=TRUE sin ninguna entrada en activacion_señales,
lo que indica que nunca paso por el pipeline de onboarding.

Extensión futura: cuando Aitanna exponga un endpoint para listar el arbol
org → ubicacion → zona, llamar aqui primero para sincronizar la DB antes de detectar.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _nuevas() -> list[str]:
    """UUIDs activos sin ninguna señal registrada (nunca onboarded)."""
    from src.db.store import get_conn

    rows = (
        get_conn()
        .execute(
            """
        SELECT u.ubicacion_id
        FROM ubicaciones u
        WHERE u.activa = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM activacion_señales a
               WHERE a.ubicacion_id = u.ubicacion_id
          )
        ORDER BY u.ubicacion_id
        """
        )
        .fetchall()
    )
    return [r[0] for r in rows]


def descargar_maestro_ubicaciones() -> list[str]:
    """
    Detecta ubicaciones nuevas y lanza el pipeline de onboarding para cada una.

    Retorna los UUIDs enviados a onboarding (lista vacía si no hay nada nuevo).
    """
    nuevas = _nuevas()

    if not nuevas:
        log.info("actualizar_arbol: sin ubicaciones nuevas que onboardear")
        return []

    log.info(
        "actualizar_arbol: %d ubicacion(es) nueva(s) detectada(s) → onboarding",
        len(nuevas),
    )
    for uid in nuevas:
        log.info("  + %s", uid)

    from src.onboarding.pipeline import onboard_nuevas_ubicaciones

    onboard_nuevas_ubicaciones(nuevas)
    return nuevas
