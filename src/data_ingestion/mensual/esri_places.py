"""
Esri ArcGIS Places API — descubrimiento mensual de POIs por ubicación.

Endpoint:  GET https://places-api.arcgis.com/arcgis/rest/services/places-service/v1/places/near-point
Auth:      token={ESRI_KEY}  (requiere privilegio premium:user:places en la API key)
Créditos:  ~1 crédito ArcGIS por cada 5 places devueltos.

Radio de búsqueda: 1 200 m (≈ isócrona peatonal 15 min) por defecto.
Configurable en location_source_config (source = 'esri_places').

Categorías buscadas por defecto (taxonomy ArcGIS Places v1):
  19044  Transit Station   → metro / subway / bus station
  19045  Train Station     → estaciones de cercanías / AVE
  16036  Tourist Attraction → monumentos, museos, landmarks
  10000  Arts & Entertainment → teatros, salas de concierto, cines
  17060  Clothing Store    → competidores directos (moda/textil)

Para descubrir el árbol completo de categorías:
  GET https://places-api.arcgis.com/arcgis/rest/services/places-service/v1/categories?token={key}

Configuración en location_source_config (source = 'esri_places') — OPCIONAL:
  {
    "radio_m":       1200,
    "categorias":    ["19044", "16036", "10000"],
    "max_resultados": 100
  }

Escribe en location_pois con fuente='esri_places'.
No escribe en store_features_ext — los POIs son datos estructurales, no series temporales.

CLI:
    python -m src.data_ingestion.mensual.esri_places
    python -m src.data_ingestion.mensual.esri_places --list-categories
    python -m src.data_ingestion.mensual.esri_places --loc <uuid>
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.db.queries import upsert_poi
from src.db.store import get_conn

# ── Declaraciones de paquete mensual ─────────────────────────────────────────

SOURCE = "esri_places"

CATALOG_PAISES = ["ES", "MX", "PT"]

CATALOG_ENTRY = {
    "feature_key_template": None,  # no escribe series — escribe POIs en location_pois
    "source": SOURCE,
    "categoria": "contexto_espacial",
    "periodicidad": "mensual",
    "descripcion": (
        "Puntos de interés del entorno (metro, monumentos, salas de eventos, competidores) "
        "obtenidos de la ArcGIS Places API de Esri. Actualización mensual de la tabla "
        "location_pois. Requiere privilegio premium:user:places en la API key."
    ),
    "url_referencia": ("https://developers.arcgis.com/rest/places/places-service/near-point/"),
    "granularidad": "POI individual (radio configurable, defecto 1 200 m)",
    "cobertura_desde": None,
    "latencia_dias": 0,
    "notas_tecnicas": (
        "No genera filas en store_features_ext. Upsertea directamente en location_pois. "
        "Solo activa si ESRI_KEY está en el entorno. Sin key no hace nada (no hay mock). "
        "Categorías configurables en location_source_config['categorias']."
    ),
}

_PLACES_BASE = "https://places-api.arcgis.com/arcgis/rest/services/places-service/v1"
_NEAR_POINT_URL = f"{_PLACES_BASE}/places/near-point"
_CATEGORIES_URL = f"{_PLACES_BASE}/categories"

_TIMEOUT = 30
_DEFAULT_RADIO_M = 1200
_DEFAULT_PAGE_SIZE = 20  # máximo permitido por la API

# Taxonomía ArcGIS Places v1
# Referencia: https://developers.arcgis.com/rest/places/categories/
_DEFAULT_CATEGORIES: dict[str, tuple[str, str]] = {
    "19044": ("metro", "Transit Station"),
    "19045": ("metro", "Train Station"),
    "16036": ("tourist_poi", "Tourist Attraction"),
    "16003": ("tourist_poi", "Museum"),
    "16005": ("tourist_poi", "Historic Site"),
    "10000": ("event_venue", "Arts and Entertainment"),
    "10041": ("event_venue", "Concert Hall"),
    "10002": ("event_venue", "Movie Theater"),
    "17060": ("competitor", "Clothing Store"),
    "17069": ("competitor", "Department Store"),
}

# Relevancia por categoría (0-1)
_DEFAULT_VALOR: dict[str, float] = {
    "metro": 0.85,
    "tourist_poi": 0.70,
    "event_venue": 0.65,
    "competitor": 0.80,
    "otro": 0.50,
}


# ── Config desde location_source_config ──────────────────────────────────────


def _get_configured_locations() -> list[tuple[str, dict]]:
    rows = (
        get_conn()
        .execute(
            "SELECT location_uuid, params "
            "FROM location_source_config "
            "WHERE source = 'esri_places' AND activo = TRUE"
        )
        .fetchall()
    )
    result = []
    for loc_uuid, params_raw in rows:
        params = params_raw if isinstance(params_raw, dict) else json.loads(params_raw or "{}")
        result.append((loc_uuid, params))
    return result


def _get_loc_coords(location_uuid: str) -> tuple[float, float] | None:
    row = (
        get_conn()
        .execute(
            "SELECT lat, lon FROM dim_ubicaciones WHERE location_uuid = ? AND lat IS NOT NULL",
            [location_uuid],
        )
        .fetchone()
    )
    return (row[0], row[1]) if row else None


def _get_org_uuid(location_uuid: str) -> str | None:
    row = (
        get_conn()
        .execute(
            "SELECT org_uuid FROM dim_ubicaciones WHERE location_uuid = ?",
            [location_uuid],
        )
        .fetchone()
    )
    return row[0] if row else None


# ── Llamada a la API ──────────────────────────────────────────────────────────


def _call_places_near_point(
    lat: float,
    lon: float,
    radio_m: int,
    category_ids: list[str],
    token: str,
    page_token: str | None = None,
) -> dict:
    params: dict = {
        "y": lat,
        "x": lon,
        "radius": radio_m,
        "categoryIds": ",".join(category_ids),
        "pageSize": _DEFAULT_PAGE_SIZE,
        "f": "json",
        "token": token,
    }
    if page_token:
        params["pageToken"] = page_token

    url = _NEAR_POINT_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read())


def _fetch_all_places(
    lat: float,
    lon: float,
    radio_m: int,
    category_ids: list[str],
    token: str,
    max_resultados: int = 200,
) -> list[dict]:
    """Itera páginas hasta agotar resultados o alcanzar max_resultados."""
    results = []
    page_token = None
    while len(results) < max_resultados:
        try:
            data = _call_places_near_point(lat, lon, radio_m, category_ids, token, page_token)
        except Exception as e:
            raise RuntimeError(f"Error llamando Places API: {e}") from e

        if "error" in data:
            raise RuntimeError(f"Esri Places error: {data['error']}")

        batch = data.get("results", [])
        results.extend(batch)

        pagination = data.get("pagination", {})
        next_url = pagination.get("nextUrl")
        if not next_url or not batch:
            break
        # extraer pageToken del nextUrl
        parsed = urllib.parse.urlparse(next_url)
        qs = urllib.parse.parse_qs(parsed.query)
        page_token = qs.get("pageToken", [None])[0]
        if not page_token:
            break

    return results[:max_resultados]


# ── Escritura en location_pois ────────────────────────────────────────────────


def _place_to_poi(place: dict, cat_map: dict[str, tuple[str, str]]) -> dict | None:
    """Convierte un resultado de Places API al formato de upsert_poi."""
    name = (place.get("name") or "").strip()
    if not name:
        return None

    loc = place.get("location", {})
    lon = loc.get("x")
    lat = loc.get("y")
    if lat is None or lon is None:
        return None

    # Categoría más específica que tengamos en nuestro mapa
    cats = place.get("categories", [])
    categoria = "otro"
    valor = _DEFAULT_VALOR["otro"]
    for c in cats:
        cid = str(c.get("categoryId", ""))
        if cid in cat_map:
            categoria, _ = cat_map[cid]
            valor = _DEFAULT_VALOR.get(categoria, 0.5)
            break

    cat_labels = [c.get("label", "") for c in cats if c.get("label")]
    detalle = " · ".join(cat_labels[:3]) if cat_labels else None

    return {
        "nombre": name,
        "lat": lat,
        "lon": lon,
        "categoria": categoria,
        "valor_relativo": valor,
        "detalle": detalle,
    }


# ── Sync principal ────────────────────────────────────────────────────────────


def sync_location(
    location_uuid: str,
    params: dict | None = None,
    verbose: bool = True,
) -> int:
    """
    Llama a Esri Places, upsertea resultados en location_pois.
    Devuelve número de POIs procesados.
    """
    token = os.environ.get("ESRI_KEY", "")
    if not token:
        if verbose:
            print(f"  [esri_places] {location_uuid}: ESRI_KEY no encontrado, omitido")
        return 0

    params = params or {}
    coords = _get_loc_coords(location_uuid)
    if not coords:
        if verbose:
            print(f"  [esri_places] {location_uuid}: sin coordenadas, omitido")
        return 0

    org_uuid = _get_org_uuid(location_uuid)
    if not org_uuid:
        return 0

    lat, lon = coords
    radio_m = int(params.get("radio_m", _DEFAULT_RADIO_M))
    max_res = int(params.get("max_resultados", 200))

    # Categorías configuradas o las por defecto
    cat_ids_cfg = params.get("categorias")
    if cat_ids_cfg:
        cat_map = {cid: _DEFAULT_CATEGORIES.get(cid, ("otro", cid)) for cid in cat_ids_cfg}
    else:
        cat_map = _DEFAULT_CATEGORIES.copy()

    try:
        places = _fetch_all_places(lat, lon, radio_m, list(cat_map.keys()), token, max_res)
    except RuntimeError as e:
        if verbose:
            print(f"  [esri_places] {location_uuid} ERROR — {e}")
        return 0

    n = 0
    for place in places:
        poi = _place_to_poi(place, cat_map)
        if poi is None:
            continue
        try:
            upsert_poi(
                location_uuid=location_uuid,
                org_uuid=org_uuid,
                fuente="esri_places",
                **poi,
            )
            n += 1
        except Exception as e:
            if verbose:
                print(f"  [esri_places] upsert error '{poi['nombre']}': {e}")

    if verbose:
        print(
            f"  [esri_places] {location_uuid}: {n} POIs sincronizados ({len(places)} encontrados)"
        )
    return n


def sync(jobs: list, fecha: date) -> int:
    """Interfaz estándar para sync_mensual."""
    locations = _get_configured_locations()
    total = 0
    for loc_uuid, params in locations:
        try:
            total += sync_location(loc_uuid, params, verbose=True)
        except Exception as e:
            print(f"  [esri_places] {loc_uuid} ERROR — {e}")
    return total


def run(
    location_uuid: str | None = None,
    max_age_hours: float = 720,
    verbose: bool = True,
) -> dict[str, int]:
    """Interfaz nightly. Mensual es suficiente para datos de infraestructura."""
    from src.data_ingestion.prefetch._common import is_fresh, write_sync_marker

    locations = _get_configured_locations()
    if location_uuid:
        locations = [(lu, p) for lu, p in locations if lu == location_uuid]

    result: dict[str, int] = {}
    for loc_uuid, params in locations:
        if is_fresh(loc_uuid, SOURCE, max_age_hours):
            result[loc_uuid] = 0
            continue
        n = sync_location(loc_uuid, params, verbose)
        write_sync_marker(loc_uuid, SOURCE)
        result[loc_uuid] = n
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Esri Places — sincronización de POIs")
    parser.add_argument("--loc", metavar="UUID", help="Ubicación concreta")
    parser.add_argument("--radio", type=int, default=_DEFAULT_RADIO_M)
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="Lista el árbol de categorías de Places y sale",
    )
    args = parser.parse_args()

    token = os.environ.get("ESRI_KEY", "")
    if not token:
        print("[esri_places] ESRI_KEY no encontrado en el entorno.")
        sys.exit(1)

    if args.list_categories:
        url = f"{_CATEGORIES_URL}?f=json&token={token}"
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as r:
            cats = json.loads(r.read())
        for c in cats.get("categories", []):
            print(f"  {c.get('categoryId'):8s}  {c.get('fullLabel', c.get('label', ''))}")
        sys.exit(0)

    if args.loc:
        sync_location(args.loc, {"radio_m": args.radio}, verbose=True)
    else:
        locations = _get_configured_locations()
        if not locations:
            print("[esri_places] No hay ubicaciones en location_source_config.")
        for loc_uuid, params in locations:
            params["radio_m"] = params.get("radio_m", args.radio)
            sync_location(loc_uuid, params, verbose=True)
