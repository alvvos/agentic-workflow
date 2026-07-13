"""
Sincronización del árbol Aitanna (org → ubicacion → zona) con la DB.

descargar_maestro_ubicaciones() es el punto de entrada desde sync_noche.py (Fase 0).

Flujo:
  1. GET /api/v1/get-all-locations-and-zones  →  upsert orgs/ubicaciones/zonas
  2. Detectar ubicaciones activas sin activacion_señales  →  onboarding pipeline
"""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

_AITANNA_TREE_URL = "https://platform.aitanna.ai/api/v1/get-all-locations-and-zones"
_TIMEOUT = 20


def _sync_arbol_aitanna() -> int:
    """
    Descarga el árbol completo de Aitanna y hace upsert en orgs/ubicaciones/zonas.
    Solo procesa orgs que estén en ALLOWED_ORG_IDS.
    Devuelve el número de ubicaciones procesadas.
    """
    from src.data_ingestion._common import ALLOWED_ORG_IDS
    from src.db.store import get_conn

    key = os.getenv("AITANNA_API_KEY", "")
    try:
        resp = requests.get(_AITANNA_TREE_URL, headers={"x-api-key": key}, timeout=_TIMEOUT)
        resp.raise_for_status()
        tree = resp.json()
    except Exception as exc:
        log.warning("actualizar_arbol: no se pudo obtener árbol Aitanna — %s", exc)
        return 0

    conn = get_conn()
    n_locs = 0

    for org in tree:
        org_uuid = org.get("uuid")
        if not org_uuid or org_uuid not in ALLOWED_ORG_IDS:
            continue

        org_nombre = org.get("name", "")
        # Infiere país del nombre de la org o usa 'ES' como default
        org_pais = (
            "MX" if "méxico" in org_nombre.lower() or "mexico" in org_nombre.lower() else "ES"
        )
        conn.execute(
            "INSERT INTO organizaciones (org_id, nombre, pais_codigo) VALUES (%s, %s, %s)"
            " ON CONFLICT (org_id) DO UPDATE SET nombre = EXCLUDED.nombre",
            [org_uuid, org_nombre, org_pais],
        )

        for loc in org.get("locations", []):
            loc_uuid = loc.get("uuid")
            if not loc_uuid:
                continue

            conn.execute(
                """INSERT INTO ubicaciones
                   (ubicacion_id, org_id, nombre, ciudad, provincia, pais_codigo,
                    codigo_postal, direccion, activa)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s, TRUE)
                   ON CONFLICT (ubicacion_id) DO UPDATE
                   SET nombre      = EXCLUDED.nombre,
                       ciudad      = COALESCE(EXCLUDED.ciudad,      ubicaciones.ciudad),
                       provincia   = COALESCE(EXCLUDED.provincia,   ubicaciones.provincia),
                       pais_codigo = COALESCE(EXCLUDED.pais_codigo, ubicaciones.pais_codigo),
                       codigo_postal = COALESCE(EXCLUDED.codigo_postal, ubicaciones.codigo_postal),
                       direccion   = COALESCE(EXCLUDED.direccion,   ubicaciones.direccion)
                """,
                [
                    loc_uuid,
                    org_uuid,
                    loc.get("name", ""),
                    loc.get("city"),
                    loc.get("province"),
                    "MX" if loc.get("country", "").lower() in ("méxico", "mexico") else "ES",
                    loc.get("postCode") or loc.get("postal_code"),
                    loc.get("address"),
                ],
            )

            # Pasada 1: upsert zonas sin parent para evitar FK violations por orden
            zona_parents: list[tuple[str, str | None]] = []
            for zone in loc.get("zones", []):
                zone_uuid = zone.get("uuid")
                if not zone_uuid:
                    continue
                zone_name = zone.get("zoneName", "")
                hidden = zone.get("hidden", False)
                fathers = zone.get("fathers", [])
                parent_uuid = fathers[0] if fathers else None
                zona_parents.append((zone_uuid, parent_uuid))

                conn.execute(
                    """INSERT INTO zonas (zona_id, ubicacion_id, nombre, hidden, parent_zona_id)
                       VALUES (%s, %s, %s, %s, NULL)
                       ON CONFLICT (zona_id) DO UPDATE
                       SET nombre = EXCLUDED.nombre,
                           hidden = EXCLUDED.hidden
                    """,
                    [zone_uuid, loc_uuid, zone_name, hidden],
                )

            # Pasada 2: actualiza parent_zona_id una vez todas las zonas existen
            for zone_uuid, parent_uuid in zona_parents:
                if parent_uuid:
                    conn.execute(
                        "UPDATE zonas SET parent_zona_id = %s WHERE zona_id = %s",
                        [parent_uuid, zone_uuid],
                    )

            n_locs += 1

    log.info("actualizar_arbol: %d ubicacion(es) sincronizadas desde Aitanna", n_locs)
    return n_locs


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
    Sincroniza el árbol Aitanna en DB, luego detecta ubicaciones nuevas
    y lanza el pipeline de onboarding para cada una.

    Retorna los UUIDs enviados a onboarding (lista vacía si no hay nada nuevo).
    """
    _sync_arbol_aitanna()

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
