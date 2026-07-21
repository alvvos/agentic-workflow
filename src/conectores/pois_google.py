"""
Conector para consultar POIs via Google Maps Places API (Nearby Search v1).

Interfaz pública:
    TIPO = "pois_google"
    sync(ubicacion_id, cfg, verbose) -> int
    sync_google_places_location(location_uuid, params, verbose) -> int   ← desde admin_pois y onboarding
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

TIPO = "pois_google"

_BASE_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

# (google_type, categoria_interna, valor_relativo)
# El orden importa: se usa la primera categoría que coincide con el place_id visto
_TYPE_MAP: list[tuple[str, str, float]] = [
    ("subway_station", "metro", 0.90),
    ("train_station", "metro", 0.90),
    ("transit_station", "metro", 0.85),
    ("bus_station", "transporte_bus", 0.70),
    ("tourist_attraction", "tourist_poi", 0.80),
    ("museum", "tourist_poi", 0.75),
    ("art_gallery", "tourist_poi", 0.65),
    ("stadium", "event_venue", 0.80),
    ("movie_theater", "event_venue", 0.70),
    ("amusement_park", "event_venue", 0.75),
    ("night_club", "event_venue", 0.65),
    ("shopping_mall", "ancla", 0.90),
    ("supermarket", "ancla", 0.80),
    ("department_store", "competitor", 0.85),
    ("clothing_store", "competitor", 0.80),
    ("restaurant", "restauracion", 0.60),
    ("cafe", "restauracion", 0.55),
    ("bar", "restauracion", 0.55),
    ("store", "competitor", 0.60),
]

_TYPE_TO_CAT: dict[str, tuple[str, float]] = {t: (c, v) for t, c, v in _TYPE_MAP}
_GOOGLE_TYPES: list[str] = [t for t, _, _ in _TYPE_MAP]


def sync(ubicacion_id: str, cfg: dict, verbose: bool = True) -> int:
    token = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not token:
        if verbose:
            print(f"  [pois_google] {ubicacion_id}: GOOGLE_MAPS_API_KEY no configurada, omitido")
        return 0
    return sync_google_places_location(ubicacion_id, cfg, verbose)


def sync_google_places_location(
    location_uuid: str,
    params: dict | None = None,
    verbose: bool = True,
) -> int:
    """
    Consulta Google Maps Places Nearby Search y upsertea POIs en puntos_interes.
    Itera por tipo de lugar para maximizar cobertura con la API legacy.
    Devuelve el número de POIs procesados.
    """
    from src.db.queries import upsert_poi
    from src.db.store import get_conn

    token = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not token:
        if verbose:
            print(f"  [pois_google] {location_uuid}: GOOGLE_MAPS_API_KEY no configurada, omitido")
        return 0

    params = params or {}
    radio_m = int(params.get("radio_m", 1200))
    max_res = int(params.get("max_resultados", 200))

    row = (
        get_conn()
        .execute(
            "SELECT lat, lon, org_id FROM ubicaciones WHERE ubicacion_id = ? AND lat IS NOT NULL",
            [location_uuid],
        )
        .fetchone()
    )
    if not row:
        if verbose:
            print(f"  [pois_google] {location_uuid}: sin coordenadas, omitido")
        return 0

    lat, lon, org_id = row[0], row[1], row[2]

    def _call_api(google_type: str, page_token: str | None = None) -> dict:
        p: dict = {
            "location": f"{lat},{lon}",
            "radius": radio_m,
            "type": google_type,
            "key": token,
        }
        if page_token:
            p["pagetoken"] = page_token
        url = _BASE_URL + "?" + urllib.parse.urlencode(p)
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as resp:
            return json.loads(resp.read())

    def _fetch_type(google_type: str) -> list[dict]:
        results: list[dict] = []
        page_token = None
        while len(results) < max_res:
            if page_token:
                time.sleep(2)  # Google requiere espera antes de usar page_token
            try:
                data = _call_api(google_type, page_token)
            except Exception as e:
                if verbose:
                    print(f"  [pois_google] {location_uuid}/{google_type} ERROR — {e}")
                break
            status = data.get("status", "")
            if status not in ("OK", "ZERO_RESULTS"):
                if verbose:
                    print(f"  [pois_google] {location_uuid}/{google_type} status={status}")
                break
            results.extend(data.get("results", []))
            page_token = data.get("next_page_token")
            if not page_token:
                break
        return results

    seen_place_ids: set[str] = set()
    n = 0

    for google_type in _GOOGLE_TYPES:
        default_cat, default_val = _TYPE_TO_CAT[google_type]
        places = _fetch_type(google_type)

        for place in places:
            pid = place.get("place_id", "")
            if pid in seen_place_ids:
                continue
            if pid:
                seen_place_ids.add(pid)

            name = (place.get("name") or "").strip()
            if not name:
                continue
            geo = place.get("geometry", {}).get("location", {})
            p_lat = geo.get("lat")
            p_lon = geo.get("lng")
            if p_lat is None or p_lon is None:
                continue

            # Refinar categoría con los tipos propios del lugar
            resolved_cat, resolved_val = default_cat, default_val
            for pt in place.get("types", []):
                if pt in _TYPE_TO_CAT and pt != google_type:
                    resolved_cat, resolved_val = _TYPE_TO_CAT[pt]
                    break

            place_types = place.get("types", [])
            detalle = " · ".join(t.replace("_", " ") for t in place_types[:3]) or None

            try:
                upsert_poi(
                    ubicacion_id=location_uuid,
                    org_id=org_id,
                    fuente="google_places",
                    nombre=name,
                    lat=p_lat,
                    lon=p_lon,
                    categoria=resolved_cat,
                    valor_relativo=resolved_val,
                    detalle=detalle,
                    radio_m=radio_m,
                )
                n += 1
            except Exception as e:
                if verbose:
                    print(f"  [pois_google] upsert error '{name}': {e}")

    if verbose:
        print(
            f"  [pois_google] {location_uuid}: {n} POIs procesados "
            f"({len(seen_place_ids)} únicos encontrados)"
        )
    return n
