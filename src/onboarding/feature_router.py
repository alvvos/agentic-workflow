"""
Agente 2 — Feature Router.

Recibe un location_uuid que ha pasado el Quality Gate y decide qué fuentes
de datos aplican según país, ciudad y tenant. Devuelve una lista de fuentes
activas y el motivo de cada decisión para que quede trazable en los logs.

Fuentes gestionadas:
    weather        Open-Meteo (clima histórico + forecast)
    open_holidays  Festivos públicos por país
    ticketmaster   Eventos TM (conciertos, festivales)
    agenda_es      Agenda cultural ES
    thesportsdb    Eventos deportivos internacionales
    cruceros       Puerto de Málaga — solo Málaga
    esri           ArcGIS GeoEnrichment — requiere ESRI_KEY + coordenadas
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Países con cobertura en OpenHolidays API
_PAISES_FESTIVOS = {"ES", "MX", "US", "FR", "DE", "GB", "IT", "PT", "BE", "NL", "AT", "CH"}

# Países con cobertura útil en Ticketmaster
_PAISES_TICKETMASTER = {"ES", "MX", "US", "FR", "DE", "GB"}

# Palabras clave que identifican Málaga en el campo ciudad
_MALAGA_KEYS = {"malaga", "málaga"}


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
        "SELECT nombre, ciudad, pais_codigo, lat, lon "
        "FROM dim_ubicaciones WHERE location_uuid = ?",
        [location_uuid],
    ).fetchone()

    if not row:
        return RoutingResult(
            location_uuid=location_uuid,
            nombre="?",
            excluidas={"*": f"location_uuid '{location_uuid}' no encontrado"},
        )

    nombre, ciudad, pais_codigo, lat, lon = row
    ciudad_lower = (ciudad or "").lower().strip()
    pais = (pais_codigo or "").upper()
    tiene_coords = bool(lat and lon)

    fuentes: list[str] = []
    excluidas: dict[str, str] = {}

    # ── Meteo ─────────────────────────────────────────────────────────────────
    if tiene_coords:
        fuentes.append("weather")
    else:
        excluidas["weather"] = "sin coordenadas"

    # ── Festivos ──────────────────────────────────────────────────────────────
    if pais in _PAISES_FESTIVOS:
        fuentes.append("open_holidays")
    else:
        excluidas["open_holidays"] = f"pais_codigo '{pais}' sin cobertura en OpenHolidays"

    # ── Ticketmaster ──────────────────────────────────────────────────────────
    if pais in _PAISES_TICKETMASTER:
        fuentes.append("ticketmaster")
    else:
        excluidas["ticketmaster"] = f"pais_codigo '{pais}' sin cobertura TM"

    # ── Agenda cultural ES ────────────────────────────────────────────────────
    if pais == "ES":
        fuentes.append("agenda_es")
    else:
        excluidas["agenda_es"] = f"solo ES (pais_codigo='{pais}')"

    # ── Deportes ──────────────────────────────────────────────────────────────
    fuentes.append("thesportsdb")

    # ── Cruceros ──────────────────────────────────────────────────────────────
    if any(k in ciudad_lower for k in _MALAGA_KEYS):
        fuentes.append("cruceros")
    else:
        excluidas["cruceros"] = f"ciudad='{ciudad}' — solo activo en Málaga"

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
