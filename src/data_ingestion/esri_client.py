"""
Cliente Esri GeoEnrichment.

HOY  (mock): fetch_enrich() devuelve datos simulados con la misma estructura
             que la respuesta real del endpoint Enrich de ArcGIS.

MAÑANA (con tarjeta + API key): cambiar solo el cuerpo de _llamar_enrich_real().
             La firma pública, el mapeo de campos y el script de carga no cambian.

Privilegios requeridos en la API key (location.arcgis.com):
  - premium:user:geoenrichment
  - premium:user:networkanalysis   ← IMPRESCINDIBLE para walk-time (NetworkServiceArea)
  - premium:user:places            ← para fase 2 (competidores/POI)
"""
import json
import random
from pathlib import Path

from src.data_processing.geo_enrichment import GEO_FEATURE_COLS

# Rangos realistas por feature para retail urbano español
_MOCK_RANGES: dict = {
    "poblacion_5min":              (800,   8_000),
    "poblacion_10min":             (3_000, 25_000),
    "poblacion_15min":             (8_000, 60_000),
    "densidad_comercial_score":    (0.10,  1.00),
    "indice_movilidad_peatonal":   (0.10,  1.00),
    "dist_transporte_min_m":       (50,    800),
    "n_competidores_500m":         (0,     12),
    "dist_competidor_cercano_m":   (30,    500),
    "renta_media_cp":              (14_000, 45_000),
    "poblacion_cp":                (5_000, 80_000),
}

# Cambiar a False cuando haya API key real y pay-as-you-go activado
USE_MOCK = True

_UBIC_PATH = Path(__file__).parent.parent / "data" / "todas_las_ubicaciones.json"


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def fetch_enrich(
    location_uuid: str,
    lat: float = None,
    lon: float = None,
    variables: list = None,
    areas: list = None,
) -> dict:
    """
    Obtiene features geoespaciales para una ubicación.

    Parámetros
    ----------
    location_uuid   UUID de la localización.
    lat, lon        Coordenadas del punto. Requeridas para llamada real; ignoradas en mock.
    variables       Subconjunto de GEO_FEATURE_COLS a obtener. None → todas.
    areas           Radios de service area en minutos, p.ej. [5, 10, 15].
                    Solo aplica a features de isócrona; ignorado en mock.

    Retorna
    -------
    Dict con claves de GEO_FEATURE_COLS (o el subconjunto indicado en `variables`).
    El dict puede pasarse directamente a ingestar_snapshot_esri() como `valores`.
    """
    cols = variables if variables is not None else GEO_FEATURE_COLS
    if USE_MOCK:
        return _mock_enrich(location_uuid, cols)
    return _llamar_enrich_real(location_uuid, lat, lon, cols, areas or [5, 10, 15])


def cargar_todas_ubicaciones(
    fecha_entrega: str = None,
    dry_run: bool = False,
) -> list[dict]:
    """
    Itera todas las localizaciones de todas_las_ubicaciones.json y ejecuta
    fetch_enrich() + ingestar_snapshot_esri() para cada una.

    Parámetros
    ----------
    fecha_entrega   Fecha ISO 8601 de la entrega. None → hoy.
    dry_run         Si True, imprime qué haría sin escribir nada en el store.

    Retorna
    -------
    Lista de dicts con el resultado de cada ingesta (o preview en dry_run).
    """
    from src.data_ingestion.ingesta_geo import ingestar_snapshot_esri

    with open(_UBIC_PATH, "r", encoding="utf-8") as f:
        orgs = json.load(f)

    resultados = []
    for org in orgs:
        for loc in org.get("locations", []):
            uuid = loc["uuid"]
            nombre = loc.get("name", uuid)
            valores = fetch_enrich(uuid)

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


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _mock_enrich(location_uuid: str, variables: list) -> dict:
    rng = random.Random(location_uuid)  # seed determinista por UUID → resultados reproducibles
    result = {}
    for col in variables:
        lo, hi = _MOCK_RANGES[col]
        if isinstance(lo, float) or isinstance(hi, float):
            result[col] = round(rng.uniform(lo, hi), 4)
        else:
            result[col] = rng.randint(lo, hi)
    return result


def _llamar_enrich_real(
    location_uuid: str,
    lat: float,
    lon: float,
    variables: list,
    areas: list,
) -> dict:
    """
    Sustituir este cuerpo cuando haya tarjeta y API key.

    Endpoint: https://geoenrich.arcgis.com/arcgis/rest/services/World/
              geoenrichmentserver/Geoenrichment/Enrich
    Auth:     X-Esri-Authorization: Bearer <ESRI_ACCESS_TOKEN>

    Walk-time service areas: areaType=NetworkServiceArea, bufferUnits=Minutes,
    bufferRadii=[5,10,15], travel_mode=Walking.
    TRAMPA: NetworkServiceArea requiere privilegio Routing además de GeoEnrichment.
    Validar primero con RingBuffer (1 variable) antes de activar NetworkServiceArea.
    """
    raise NotImplementedError(
        "Llamada real a Esri no implementada todavía. "
        "Pasos: activar pay-as-you-go en location.arcgis.com, crear API key con "
        "GeoEnrichment + Routing + Places, añadir ESRI_ACCESS_TOKEN a .env, "
        "y reemplazar este cuerpo con la llamada HTTP real."
    )
