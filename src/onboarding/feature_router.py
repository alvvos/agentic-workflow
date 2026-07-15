"""
Agente 2 — Feature Router.

Recibe un location_uuid que ha pasado el Quality Gate y decide qué fuentes
de datos aplican según país, ciudad y tenant. Devuelve una lista de fuentes
activas y el motivo de cada decisión para que quede trazable en los logs.

Fuentes gestionadas:
    weather        Open-Meteo (clima histórico + forecast)
    cruceros       Puerto de Málaga — solo Málaga
    esri           ArcGIS GeoEnrichment — requiere ESRI_KEY + coordenadas
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class RoutingResult:
    location_uuid: str
    nombre: str
    fuentes: list[str] = field(default_factory=list)
    excluidas: dict[str, str] = field(default_factory=dict)  # fuente → motivo exclusión


def enrutar(location_uuid: str) -> RoutingResult:
    """
    Determina qué fuentes de ingesta aplican para una ubicación.
    Todas las decisiones quedan registradas en fuentes / excluidas.
    """
    from src.db.store import get_conn

    conn = get_conn()

    row = conn.execute(
        "SELECT nombre, ciudad, pais_codigo, lat, lon " "FROM ubicaciones WHERE ubicacion_id = ?",
        [location_uuid],
    ).fetchone()

    if not row:
        return RoutingResult(
            location_uuid=location_uuid,
            nombre="?",
            excluidas={"*": f"ubicacion_id '{location_uuid}' no encontrado"},
        )

    nombre, ciudad, pais_codigo, lat, lon = row
    tiene_coords = bool(lat and lon)

    fuentes: list[str] = []
    excluidas: dict[str, str] = {}

    # ── Meteo ─────────────────────────────────────────────────────────────────
    if tiene_coords:
        fuentes.append("weather")
    else:
        excluidas["weather"] = "sin coordenadas"

    # ── Cruceros ──────────────────────────────────────────────────────────────
    # Activamos cruceros si la ubicación tiene una fila activa en
    # location_source_config con source='cruceros'. El context_scout (o un
    # admin) decide qué ubicaciones reciben datos de puerto.
    try:
        cruceros_row = conn.execute(
            "SELECT 1 FROM location_source_config "
            "WHERE location_uuid = ? AND source = 'cruceros' AND activo = TRUE",
            [location_uuid],
        ).fetchone()
    except Exception:
        cruceros_row = None
    if cruceros_row:
        fuentes.append("cruceros")
    else:
        excluidas["cruceros"] = (
            "sin source='cruceros' activo en location_source_config " f"(ciudad='{ciudad}')"
        )

    # ── Esri ──────────────────────────────────────────────────────────────────
    if not os.getenv("ESRI_KEY"):
        excluidas["esri"] = "ESRI_KEY no configurada"
    elif not tiene_coords:
        excluidas["esri"] = "sin coordenadas"
    else:
        fuentes.append("esri")

    return RoutingResult(
        location_uuid=location_uuid,
        nombre=nombre or "",
        fuentes=fuentes,
        excluidas=excluidas,
    )
