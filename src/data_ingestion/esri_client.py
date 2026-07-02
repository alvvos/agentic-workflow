"""
Cliente GeoEnrichment Esri — obtiene variables demográficas y de gasto por radio.

fetch_geoenrich(ubicacion_id, lat, lon) → dict[str, float | None]
  Hace 2 llamadas al API de GeoEnrichment:
    1. Ring buffer [400, 800, 1200]m → población acumulada por isócrona peatonal.
    2. Círculo 800m → demografía, renta, gasto, empleo, compras online, inmobiliario.
  Devuelve {señal_id: valor} listo para ingestar en snapshots_geo.

Requiere ESRI_KEY en el entorno (.env o variable de sistema).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger("esri_client")

_GEO_ENRICH_URL = (
    "https://geoenrich.arcgis.com/arcgis/rest/services/"
    "World/geoenrichmentserver/GeoEnrichment/enrich"
)

# {esri_collection.variable → señal_id}  — círculo 800m
# Solo variables que explican flujo de personas, no perfil demográfico.
_CIRCLE_VAR_MAP: dict[str, str] = {
    # Densidad e intensidad de uso del área (KeyFacts, 2025)
    "KeyFacts.POPDENS_CY": "densidad_poblacion",
    "KeyFacts.PPIDX_CY": "indice_poder_compra",
    "KeyFacts.PAGE02_CY": "pob_15_29",
    # Proxy de población diurna — activos laborales residentes (EmploymentTotalsAIS, 2023)
    "EmploymentTotalsAIS.TOTATC": "trabajadores_zona",
}


def _geoenrich_call(
    lat: float,
    lon: float,
    buffer_radii: list[int],
    analysis_variables: list[str],
    token: str,
) -> list[dict]:
    """Llama al GeoEnrichment API y devuelve una lista de atributos (uno por anillo)."""
    study_areas = json.dumps(
        [
            {
                "geometry": {"x": lon, "y": lat, "spatialReference": {"wkid": 4326}},
                "areaType": "RingBuffer",
                "bufferUnits": "esriMeters",
                "bufferRadii": buffer_radii,
            }
        ]
    )
    params = urllib.parse.urlencode(
        {
            "studyAreas": study_areas,
            "analysisVariables": ",".join(analysis_variables),
            "returnGeometry": "false",
            "f": "json",
            "token": token,
        }
    )
    req = urllib.request.Request(_GEO_ENRICH_URL, data=params.encode(), method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    if "error" in data:
        raise RuntimeError(f"GeoEnrichment error: {data['error']}")
    feature_sets = data.get("results", [{}])[0].get("value", {}).get("FeatureSet", [])
    if not feature_sets:
        return []
    return [f.get("attributes", {}) for f in feature_sets[0].get("features", [])]


def fetch_geoenrich(ubicacion_id: str, lat: float, lon: float) -> dict[str, float | None]:
    """
    Consulta Esri GeoEnrichment y devuelve {señal_id: valor} para insertar
    en snapshots_geo.

    Call 1 — Ring buffer [400, 800, 1200]m con KeyFacts.TOTPOP_CY:
      Devuelve población por anillo (bandas anulares). Se acumula para obtener
      la población dentro de cada isócrona peatonal.

    Call 2 — Círculo 800m con todas las variables AIS + KeyFacts:
      Demografía por edad, renta, composición de hogar, gasto retail,
      empleo, compras online, precios inmobiliarios y poder de compra.
    """
    token = os.environ.get("ESRI_KEY", "")
    if not token:
        raise RuntimeError("ESRI_KEY no encontrado en el entorno")

    resultado: dict[str, float | None] = {}

    # ── Call 1: Isócronas peatonales ─────────────────────────────────────────
    try:
        rings = _geoenrich_call(
            lat,
            lon,
            buffer_radii=[400, 800, 1200],
            analysis_variables=["KeyFacts.TOTPOP_CY"],
            token=token,
        )
        if len(rings) >= 3:
            r0 = float(rings[0].get("TOTPOP_CY") or 0)
            r1 = float(rings[1].get("TOTPOP_CY") or 0)
            r2 = float(rings[2].get("TOTPOP_CY") or 0)
            resultado["poblacion_5min"] = r0
            resultado["poblacion_10min"] = r0 + r1
            resultado["poblacion_15min"] = r0 + r1 + r2
        else:
            log.warning(
                "[%s] ring call devolvió %d features (esperadas 3)",
                ubicacion_id,
                len(rings),
            )
    except Exception as exc:
        log.error("[%s] ring call FAILED — %s", ubicacion_id, exc)

    # ── Call 2: Variables AIS + KeyFacts en círculo 800m ─────────────────────
    try:
        circle = _geoenrich_call(
            lat,
            lon,
            buffer_radii=[800],
            analysis_variables=list(_CIRCLE_VAR_MAP.keys()),
            token=token,
        )
        if circle:
            attrs = circle[0]
            for esri_spec, señal_id in _CIRCLE_VAR_MAP.items():
                var_name = esri_spec.split(".")[-1]
                val = attrs.get(var_name)
                resultado[señal_id] = float(val) if val is not None else None
        else:
            log.warning("[%s] circle call devolvió 0 features", ubicacion_id)
    except Exception as exc:
        log.error("[%s] circle call FAILED — %s", ubicacion_id, exc)

    return resultado
