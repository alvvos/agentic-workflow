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
_CIRCLE_VAR_MAP: dict[str, str] = {
    # Densidad e intensidad de uso del área (KeyFacts, 2025)
    "KeyFacts.POPDENS_CY": "densidad_poblacion",
    "KeyFacts.PPIDX_CY": "indice_poder_compra",
    "KeyFacts.PAGE02_CY": "pob_15_29",
    # Edad — franjas quinquenales (5YearIncrementsAIS, 2023)
    "5YearIncrementsAIS.POPAG00": "pob_0_4",
    "5YearIncrementsAIS.POPAG05": "pob_5_9",
    "5YearIncrementsAIS.POPAG10": "pob_10_14",
    "5YearIncrementsAIS.POPAG15": "pob_15_19",
    "5YearIncrementsAIS.POPAG20": "pob_20_24",
    "5YearIncrementsAIS.POPAG25": "pob_25_29",
    "5YearIncrementsAIS.POPAG30": "pob_30_34",
    "5YearIncrementsAIS.POPAG35": "pob_35_39",
    "5YearIncrementsAIS.POPAG40": "pob_40_44",
    "5YearIncrementsAIS.POPAG45": "pob_45_49",
    "5YearIncrementsAIS.POPAG50": "pob_50_54",
    "5YearIncrementsAIS.POPAG55": "pob_55_59",
    "5YearIncrementsAIS.POPAG60": "pob_60_64",
    "5YearIncrementsAIS.POPAG65": "pob_65_69",
    "5YearIncrementsAIS.POPAG70": "pob_70_74",
    "5YearIncrementsAIS.POPAG75": "pob_75_79",
    "5YearIncrementsAIS.POPAG80": "pob_80_84",
    "5YearIncrementsAIS.POPAG85": "pob_85_plus",
    # Renta y composición del hogar (IncomeTotalsAIS, HouseholdTotalsAIS, HouseholdsByIncomeAIS)
    "IncomeTotalsAIS.NINCHA": "renta_hogar_anual",
    "IncomeTotalsAIS.NINCCA": "renta_per_capita",
    "HouseholdTotalsAIS.HHOLDS": "n_hogares_total",
    "HouseholdsByIncomeAIS.THINC5M": "hogares_renta_alta",
    "HouseholdsByIncomeAIS.THINC4M": "hogares_renta_media_alta",
    "IncomeTotalsAIS.TOTYOSI": "hogares_jovenes_solos",
    "IncomeTotalsAIS.TOTYOCO": "hogares_parejas_jovenes",
    "IncomeTotalsAIS.TOTFUSMA": "hogares_familias_hijos",
    # Salud financiera
    "HouseholdsByIncomeAIS.HORIPOYE": "en_riesgo_pobreza_pct",
    # Gasto de consumidor (transversal — sin ropa/calzado por política de producto)
    "SpendingTotalsAIS.SPPCARE": "gasto_cuidado_personal",
    "EntertainmentAIS.SPLEISU": "gasto_ocio_cultura",
    "EntertainmentAIS.SPLHOLI": "gasto_vacaciones",
    "MiscellaneousAIS.SPHOTRE": "gasto_restaurantes",
    "FoodAndDrinksAIS.SPFOODR": "gasto_alimentacion",
    "TransportationAIS.SPTRANS": "gasto_transporte",
    # Mercado laboral (EmploymentTotalsAIS, 2023)
    "EmploymentTotalsAIS.TOTATC": "trabajadores_zona",
    "EmploymentTotalsAIS.UNERATE": "tasa_desempleo",
    "EmploymentTotalsAIS.UNERATE24": "tasa_desempleo_jovenes",
    # Canal online / omnicanalidad (OnlineShoppingAIS, 2023)
    "OnlineShoppingAIS.PUTHINT": "pct_compras_online",
    "OnlineShoppingAIS.PROPURSPO": "online_ropa_deporte_pct",
    "OnlineShoppingAIS.WHELAIN": "online_ultimo_mes_pct",
}


def _geoenrich_call(
    lat: float,
    lon: float,
    buffer_radii: list[int],
    analysis_variables: list[str],
    token: str,
    return_geometry: bool = False,
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
            "returnGeometry": "true" if return_geometry else "false",
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
    if return_geometry:
        return [f.get("geometry", {}) for f in feature_sets[0].get("features", [])]
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


_RING_RADII = [400, 800, 1200]

_SERVICE_AREA_URL = (
    "https://route.arcgis.com/arcgis/rest/services/World/ServiceAreas/"
    "NAServer/ServiceArea_World/solveServiceArea"
)

# Travel mode "Walking Time" de ArcGIS Online — id estable para red peatonal mundial
_WALK_TRAVEL_MODE = json.dumps(
    {
        "attributeParameterValues": [],
        "description": "Pedestrian",
        "distanceAttributeName": "Meters",
        "id": "caFAgoThrvUpkFBW",
        "impedanceAttributeName": "WalkTime",
        "name": "Walking Time",
        "restrictionAttributeNames": ["Avoid Roads Unsuitable for Pedestrians"],
        "timeAttributeName": "WalkTime",
        "type": "WALK",
        "useHierarchy": False,
        "uturnAtJunctions": "esriNFSBAllowBacktrack",
    }
)

# minutos → radio_m equivalente para la capa visual (≈5 km/h peatonal)
_MIN_TO_RADIO = {5: 400, 10: 800, 15: 1200}


def fetch_anillos_captacion(ubicacion_id: str, lat: float, lon: float) -> dict | None:
    """
    Obtiene isócronas peatonales reales [5, 10, 15 min] usando ArcGIS Network Analysis
    (Service Area — Walking Time). Devuelve GeoJSON FeatureCollection con la propiedad
    'radio_m' (equivalente en metros) y 'minutos' para compatibilidad con la capa visual.
    """
    token = os.environ.get("ESRI_KEY", "")
    if not token:
        raise RuntimeError("ESRI_KEY no encontrado en el entorno")

    facilities = json.dumps(
        {
            "type": "features",
            "features": [{"geometry": {"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}}],
        }
    )
    params = urllib.parse.urlencode(
        {
            "facilities": facilities,
            "defaultBreaks": "5,10,15",
            "travelMode": _WALK_TRAVEL_MODE,
            "outputType": "esriNAOutputServiceAreaPolygons",
            "returnPolygons": "true",
            "polygonDetail": "esriNAOutputPolygonHigh",
            "f": "json",
            "token": token,
        }
    )
    req = urllib.request.Request(_SERVICE_AREA_URL, data=params.encode(), method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.loads(r.read())
    except Exception as exc:
        log.error("[%s] fetch_anillos_captacion FAILED — %s", ubicacion_id, exc)
        return None

    if "error" in data:
        log.error("[%s] Service Area error — %s", ubicacion_id, data["error"])
        return None

    polys = data.get("saPolygons", {}).get("features", [])
    if not polys:
        log.warning("[%s] fetch_anillos_captacion: sin polígonos en respuesta", ubicacion_id)
        return None

    features = []
    for poly in polys:
        attrs = poly.get("attributes", {})
        minutos = int(attrs.get("ToBreak", 0))
        radio = _MIN_TO_RADIO.get(minutos, minutos * 80)
        rings = poly.get("geometry", {}).get("rings", [])
        if not rings:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {"radio_m": radio, "minutos": minutos},
                "geometry": {"type": "Polygon", "coordinates": rings},
            }
        )

    if not features:
        log.warning("[%s] fetch_anillos_captacion: sin geometría válida", ubicacion_id)
        return None

    # Ordenar de mayor a menor (15→10→5) para pintar capas correctamente
    features.sort(key=lambda f: f["properties"]["minutos"], reverse=True)
    return {"type": "FeatureCollection", "features": features}


def write_anillos_captacion(ubicacion_id: str, lat: float, lon: float) -> bool:
    """
    Obtiene isócronas peatonales de red [5/10/15 min] y las persiste en
    ubicaciones.anillos_captacion. Devuelve True si se escribió correctamente.
    """
    geojson = fetch_anillos_captacion(ubicacion_id, lat, lon)
    if not geojson:
        return False

    from src.db.store import get_conn

    get_conn().execute(
        "UPDATE ubicaciones SET anillos_captacion = %s::jsonb WHERE ubicacion_id = %s",
        [json.dumps(geojson, ensure_ascii=False), ubicacion_id],
    )
    log.info("[%s] anillos_captacion escritos (%d anillos)", ubicacion_id, len(geojson["features"]))
    return True
