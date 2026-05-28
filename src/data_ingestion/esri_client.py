"""
Cliente Esri GeoEnrichment — llamada real con RingBuffer.

Endpoint: POST https://geoenrich.arcgis.com/arcgis/rest/services/World/
          geoenrichmentserver/Geoenrichment/Enrich
Auth:     token=ESRI_KEY en body (o X-Esri-Authorization: Bearer header)
Área:     RingBuffer 400/800/1200 m como proxy de 5/10/15 min peatonal.
          NetworkServiceArea falla si el privilegio Routing no está activo;
          RingBuffer es el fallback recomendado hasta validar con walking SA.

Privilegios requeridos en la API key (location.arcgis.com):
  - premium:user:geoenrichment   ← para el Enrich endpoint
  - premium:user:networkanalysis ← solo necesario para NetworkServiceArea
  - premium:user:places          ← para fase 2 (competidores/POI)
"""
import json
import os
import random
import urllib.parse
import urllib.request
from pathlib import Path

from src.data_processing.geo_enrichment import (
    ESRI_COLLECTION_MAP,
    ESRI_VAR_MAP,
    GEO_FEATURE_COLS,
)

_ENRICH_URL = (
    "https://geoenrich.arcgis.com/arcgis/rest/services/World/"
    "geoenrichmentserver/Geoenrichment/Enrich"
)
_SERVICE_AREA_URL = (
    "https://route-api.arcgis.com/arcgis/rest/services/World/ServiceAreas/"
    "NAServer/ServiceArea_World/solveServiceArea"
)

# Travel mode JSON explícito para pedestres.
# El parámetro `impedance=WalkTime` no es suficiente — la API usa DriveTime por defecto
# a menos que se especifique travelMode con type="WALK" y useHierarchy=false.
_WALK_TRAVEL_MODE = json.dumps({
    "attributeParameterValues": [],
    "description": "Suitable for pedestrian activity.",
    "distanceAttributeName": "WalkTime",
    "id": "caFAgoThrvUpkFBW",
    "impedanceAttributeName": "WalkTime",
    "name": "Walking",
    "restrictionAttributeNames": [
        "Avoid Roads Unsuitable for Pedestrians",
        "Avoid Roads Prohibited for Pedestrians",
    ],
    "simplificationTolerance": 2,
    "simplificationToleranceUnits": "esriMetersPerUnit",
    "timeAttributeName": "WalkTime",
    "type": "WALK",
    "useHierarchy": False,
    "uturnAtJunctions": "esriNFSBAllowBacktrack",
})

# Ring buffers en metros — proxy para 5/10/15 min peatonal (~80 m/min)
_RING_BUFFERS = [400, 800, 1200]

_UBIC_PATH = Path(__file__).parent.parent / "data" / "todas_las_ubicaciones.json"

# Mock habilitado solo si ESRI_KEY no está en el entorno
USE_MOCK = not bool(os.environ.get("ESRI_KEY", ""))

_MOCK_RANGES: dict = {
    "poblacion_5min":                  (800,     8_000),
    "poblacion_10min":                 (3_000,  25_000),
    "poblacion_15min":                 (8_000,  60_000),
    "pob_0_4":                         (80,      1_500),
    "pob_5_9":                         (80,      1_500),
    "pob_10_14":                       (80,      1_500),
    "pob_15_19":                       (100,     2_000),
    "pob_20_24":                       (100,     2_000),
    "pob_25_29":                       (100,     2_000),
    "pob_30_34":                       (100,     2_000),
    "pob_35_39":                       (100,     2_000),
    "pob_40_44":                       (120,     2_200),
    "pob_45_49":                       (120,     2_200),
    "pob_50_54":                       (120,     2_200),
    "pob_55_59":                       (110,     2_100),
    "pob_60_64":                       (110,     2_100),
    "pob_65_69":                       (90,      1_800),
    "pob_70_74":                       (80,      1_600),
    "pob_75_79":                       (60,      1_200),
    "pob_80_84":                       (40,        900),
    "pob_85_plus":                     (20,        500),
    "renta_hogar_anual":               (20_000, 55_000),
    "renta_hogar_mensual":             (1_600,   4_500),
    "renta_per_capita":                (8_000,  25_000),
    "n_hogares_total":                 (500,    15_000),
    "tamanio_medio_hogar":             (2.1,      3.2),
    "hogares_renta_alta":              (200,     3_000),
    "hogares_renta_media_alta":        (150,     2_500),
    "hogares_jovenes_solos":           (10,        500),
    "hogares_parejas_jovenes":         (50,        800),
    "hogares_parejas_adultas":         (100,     2_000),
    "hogares_familias_hijos":          (100,     1_500),
    "hogares_monoparentales":          (30,        600),
    "puede_afrontar_imprevistos_pct":  (200,     3_000),
    "llega_mes_con_facilidad_pct":     (100,     2_000),
    "en_riesgo_pobreza_pct":           (50,      1_000),
    "gasto_ropa_calzado":              (800,     2_500),
    "gasto_ropa":                      (550,     1_800),
    "gasto_calzado":                   (200,       700),
    "gasto_cuidado_personal":          (300,     1_200),
    "gasto_ocio_cultura":              (900,     2_800),
    "gasto_vacaciones":                (300,     2_000),
    "gasto_restaurantes":              (1_500,   5_000),
    "gasto_alimentacion":              (3_000,   8_000),
    "gasto_transporte":                (1_000,   4_000),
    "gasto_comunicaciones":            (500,     1_500),
    "tasa_desempleo":                  (200,     3_000),
    "tasa_desempleo_jovenes":          (50,      1_000),
    "empleados_por_hogar":             (100,     2_500),
    "tasa_riesgo_pobreza":             (0.05,     0.35),
    "precio_medio_piso_compra":        (80_000, 500_000),
    "precio_medio_piso_alquiler":      (400,     2_000),
    "pct_compras_online":              (100,     3_000),
    "online_ropa_deporte_pct":         (30,        800),
    "online_ultimo_mes_pct":           (50,      1_500),
    "densidad_comercial_score":        (0.10,     1.00),
    "indice_movilidad_peatonal":       (0.10,     1.00),
    "dist_transporte_min_m":           (50,        800),
    "n_competidores_500m":             (0,          12),
    "dist_competidor_cercano_m":       (30,        500),
}


# ── API pública ───────────────────────────────────────────────────────────────

def fetch_enrich(
    location_uuid: str,
    lat: float = None,
    lon: float = None,
    variables: list = None,
) -> dict:
    """
    Obtiene features geoespaciales de Esri GeoEnrichment para una ubicación.

    Parámetros
    ----------
    location_uuid   UUID de la localización (para identificación en logs).
    lat, lon        Coordenadas WGS-84. Requeridas en modo real; ignoradas en mock.
    variables       Subconjunto de GEO_FEATURE_COLS a obtener. None → todas.

    Retorna
    -------
    Dict con claves en GEO_FEATURE_COLS (o subconjunto). Pásalo directamente a
    ingestar_snapshot_esri() como `valores`.
    """
    cols = variables if variables is not None else GEO_FEATURE_COLS
    if USE_MOCK or not lat or not lon:
        return _mock_enrich(location_uuid, cols)
    return _llamar_enrich_real(location_uuid, lat, lon, cols)


def cargar_todas_ubicaciones(
    org_filter: str = None,
    fecha_entrega: str = None,
    dry_run: bool = False,
) -> list[dict]:
    """
    Itera ubicaciones de todas_las_ubicaciones.json y ejecuta fetch_enrich +
    ingestar_snapshot_esri para cada una.

    Parámetros
    ----------
    org_filter      Si se especifica, procesa solo la org cuyo nombre contiene este string.
    fecha_entrega   Fecha ISO 8601 de la entrega. None → hoy.
    dry_run         Si True, imprime qué haría sin escribir nada en el store.
    """
    from src.data_ingestion.ingesta_geo import ingestar_snapshot_esri

    with open(_UBIC_PATH, "r", encoding="utf-8") as f:
        orgs = json.load(f)

    resultados = []
    for org in orgs:
        org_name = org.get("name", "")
        if org_filter and org_filter.lower() not in org_name.lower():
            continue
        for loc in org.get("locations", []):
            uuid   = loc["uuid"]
            nombre = loc.get("name", uuid)
            lat    = loc.get("lat")
            lon    = loc.get("lon")

            valores = fetch_enrich(uuid, lat=lat, lon=lon)

            if dry_run:
                print(f"[dry_run] {nombre} ({uuid})")
                for k, v in valores.items():
                    print(f"  {k}: {v}")
                resultados.append({"location_uuid": uuid, "name": nombre, "valores": valores})
                continue

            resultado = ingestar_snapshot_esri(uuid, valores, fecha_entrega)
            resultado["name"] = nombre
            resultados.append(resultado)
            print(f"[ok] {nombre} — {resultado['snapshots_creados']} snapshot(s), "
                  f"{len(resultado['features_registradas'])} features")

    return resultados


def fetch_service_area_isochrones(lat: float, lon: float) -> list | None:
    """
    Isócronas peatonales reales (5 / 10 / 15 min) vía ArcGIS ServiceArea.

    Retorna lista de 3 dicts [{lats, lons}, ...] ordenados [5 min, 10 min, 15 min]
    (anillo exterior de cada polígono), o None si USE_MOCK está activo o la llamada falla.
    """
    if USE_MOCK:
        return None
    token = os.environ.get("ESRI_KEY", "")
    if not token:
        return None
    return _fetch_service_area_isochrones(lat, lon, token)


# ── Internals ─────────────────────────────────────────────────────────────────

def _fetch_service_area_isochrones(lat: float, lon: float, token: str) -> list | None:
    """
    Llama a ArcGIS ServiceArea con impedance=WalkTime para 5/10/15 min.

    Retorna lista de 3 dicts [{lats, lons}] ordenados [5 min, 10 min, 15 min]
    (anillo exterior de cada polígono, sin huecos), o None en caso de error.
    """
    params = urllib.parse.urlencode({
        "facilities":      json.dumps({"features": [{"geometry": {"x": lon, "y": lat}}]}),
        "defaultBreaks":   "5,10,15",
        "travelDirection": "esriNATravelDirectionToFacility",
        "travelMode":      _WALK_TRAVEL_MODE,
        "returnPolygons":  "true",
        "outSR":           "4326",
        "f":               "json",
        "token":           token,
    }).encode("utf-8")

    req = urllib.request.Request(_SERVICE_AREA_URL, data=params, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None

    if "error" in data:
        return None

    polys    = data.get("saPolygons") or data.get("polygons") or {}
    features = polys.get("features", []) if isinstance(polys, dict) else []
    if len(features) != 3:
        return None

    features_sorted = sorted(features, key=lambda f: f.get("attributes", {}).get("ToBreak", 0))

    rings = []
    for feat in features_sorted:
        geom_rings = feat.get("geometry", {}).get("rings", [])
        if not geom_rings:
            rings.append(None)
            continue
        outer = geom_rings[0]
        rings.append({
            "lons": [pt[0] for pt in outer],
            "lats": [pt[1] for pt in outer],
        })

    return rings if any(r is not None for r in rings) else None


def _mock_enrich(location_uuid: str, variables: list) -> dict:
    rng = random.Random(location_uuid)
    result = {}
    for col in variables:
        if col not in _MOCK_RANGES:
            result[col] = None
            continue
        lo, hi = _MOCK_RANGES[col]
        result[col] = round(rng.uniform(lo, hi), 4) if isinstance(lo, float) else rng.randint(lo, hi)
    return result


def _llamar_enrich_real(
    location_uuid: str,
    lat: float,
    lon: float,
    variables: list,
) -> dict:
    """
    Llama al endpoint Enrich de ArcGIS con RingBuffer 400/800/1200 m.

    Extrae los valores según ESRI_VAR_MAP:
      - radius_index 0 → feature del buffer 400 m (≈ 5 min peatonal)
      - radius_index 1 → feature del buffer 800 m (≈ 10 min peatonal)
      - radius_index 2 → feature del buffer 1 200 m (≈ 15 min peatonal)

    Las features sin entrada en ESRI_VAR_MAP (fase 2: Places/Routing) se devuelven
    como None sin generar petición.
    """
    token = os.environ.get("ESRI_KEY", "")
    if not token:
        raise RuntimeError("ESRI_KEY no encontrado en el entorno")

    # Solo features con fuente en GeoEnrichment
    geo_cols = [c for c in variables if ESRI_VAR_MAP.get(c) is not None]
    if not geo_cols:
        return {c: None for c in variables}

    # Lista ordenada y deduplicada de IDs Esri → analysisVariables
    seen: set = set()
    analysis_vars: list = []
    for col in geo_cols:
        var_id, _ = ESRI_VAR_MAP[col]
        qualified = f"{ESRI_COLLECTION_MAP[var_id]}.{var_id}"
        if qualified not in seen:
            seen.add(qualified)
            analysis_vars.append(qualified)

    study_areas = json.dumps([{
        "geometry": {"x": lon, "y": lat},
        "areaType": "RingBuffer",
        "bufferUnits": "Meters",
        "bufferRadii": _RING_BUFFERS,
    }])

    def _call_enrich(vars_list: list) -> dict:
        params = urllib.parse.urlencode({
            "studyAreas":        study_areas,
            "analysisVariables": json.dumps(vars_list),
            "returnGeometry":    "true",
            "f":                 "json",
            "token":             token,
        }).encode("utf-8")
        req = urllib.request.Request(_ENRICH_URL, data=params, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())

    data = _call_enrich(analysis_vars)

    if "error" in data:
        raise RuntimeError(f"Esri API error [{location_uuid}]: {data['error']}")

    msgs = data.get("messages", [])
    errors = [m for m in msgs if m.get("type") == "esriJobMessageTypeError"]
    if errors:
        desc = errors[0].get("description", "")
        # Algunas variables no existen para ciertos países — reintento sin ellas
        import re as _re2
        undefined = _re2.findall(r"\w+\.\w+", desc)
        if undefined and "not defined" in desc.lower():
            pruned = [v for v in analysis_vars if v not in undefined]
            if pruned and pruned != analysis_vars:
                data = _call_enrich(pruned)
                msgs2 = data.get("messages", [])
                errors2 = [m for m in msgs2 if m.get("type") == "esriJobMessageTypeError"]
                if errors2:
                    raise RuntimeError(f"Esri error [{location_uuid}]: {errors2[0].get('description')}")
            else:
                raise RuntimeError(f"Esri error [{location_uuid}]: {desc}")
        else:
            raise RuntimeError(f"Esri error [{location_uuid}]: {desc}")

    features = data["results"][0]["value"]["FeatureSet"][0]["features"]

    result: dict = {}
    for col in variables:
        entry = ESRI_VAR_MAP.get(col)
        if entry is None:
            result[col] = None   # fase 2, no disponible aún
            continue
        var_id, radius_idx = entry
        attrs = features[radius_idx]["attributes"]
        val = attrs.get(var_id)
        result[col] = round(val, 2) if isinstance(val, float) else val

    # Isócronas peatonales: preferir ServiceArea (red viaria real) sobre RingBuffer
    sa_rings = _fetch_service_area_isochrones(lat, lon, token)
    if sa_rings is not None:
        result["_catchment_rings"] = sa_rings
    else:
        # Fallback: geometría del RingBuffer devuelta por GeoEnrichment
        catchment_rings = []
        for feat in features:
            geom = feat.get("geometry")
            if geom and "rings" in geom and geom["rings"]:
                outer = geom["rings"][0]
                catchment_rings.append({
                    "lons": [pt[0] for pt in outer],
                    "lats": [pt[1] for pt in outer],
                })
            else:
                catchment_rings.append(None)
        if any(r is not None for r in catchment_rings):
            result["_catchment_rings"] = catchment_rings

    return result
