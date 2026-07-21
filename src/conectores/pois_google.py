"""
Conector para consultar POIs via Google Maps Places API (New — Nearby Search v1).

Usa la API nueva (places.googleapis.com/v1) porque la legacy
(maps.googleapis.com/api/place) requiere activación manual separada.

Interfaz pública:
    TIPO = "pois_google"
    sync(ubicacion_id, cfg, verbose) -> int
    sync_google_places_location(location_uuid, params, verbose) -> int
"""

from __future__ import annotations

import json
import os
import urllib.request

TIPO = "pois_google"

_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"

# Campos a solicitar — price_level no existe en v1; resto son estables
_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.location",
        "places.types",
        "places.primaryType",
        "places.primaryTypeDisplayName",
        "places.rating",
        "places.userRatingCount",
        "places.formattedAddress",
    ]
)

# (google_type, categoria_interna, valor_relativo)
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
    Consulta Google Maps Places API (New) con Nearby Search y upsertea POIs.
    Itera por tipo de lugar para maximizar cobertura (max 20 resultados por tipo).
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
    radio_m = float(params.get("radio_m", 1200))
    max_per_type = min(int(params.get("max_resultados", 200)), 20)  # API new: max 20/llamada

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

    lat, lon, org_id = float(row[0]), float(row[1]), row[2]

    def _call(google_type: str, page_token: str | None = None) -> dict:
        body: dict = {
            "includedTypes": [google_type],
            "maxResultCount": max_per_type,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": radio_m,
                }
            },
        }
        if page_token:
            body["pageToken"] = page_token
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            _NEARBY_URL,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": token,
                "X-Goog-FieldMask": _FIELD_MASK,
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def _fetch_type(google_type: str) -> list[dict]:
        results: list[dict] = []
        page_token = None
        while True:
            try:
                data = _call(google_type, page_token)
            except Exception as e:
                if verbose:
                    print(f"  [pois_google] {location_uuid}/{google_type} ERROR — {e}")
                break
            if "error" in data:
                if verbose:
                    code = data["error"].get("code", "?")
                    msg = data["error"].get("message", "")
                    print(f"  [pois_google] {location_uuid}/{google_type} API error {code}: {msg}")
                break
            results.extend(data.get("places", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return results

    def _build_detalle(place: dict) -> str | None:
        parts = []
        ptdn = place.get("primaryTypeDisplayName", {})
        if isinstance(ptdn, dict):
            t = ptdn.get("text", "")
        else:
            t = str(ptdn)
        if t:
            parts.append(t)
        rating = place.get("rating")
        n_ratings = place.get("userRatingCount")
        if rating is not None:
            r_str = f"★{rating:.1f}"
            if n_ratings:
                r_str += f" ({n_ratings:,})"
            parts.append(r_str)
        addr = place.get("formattedAddress", "")
        if addr:
            # Solo calle + ciudad, sin código postal largo
            parts.append(addr.split(",")[0])
        return " · ".join(parts) if parts else None

    seen_ids: set[str] = set()
    n = 0

    for google_type in _GOOGLE_TYPES:
        default_cat, default_val = _TYPE_TO_CAT[google_type]
        places = _fetch_type(google_type)

        for place in places:
            pid = place.get("id", "")
            if pid in seen_ids:
                continue
            if pid:
                seen_ids.add(pid)

            name_obj = place.get("displayName", {})
            name = (
                name_obj.get("text", "") if isinstance(name_obj, dict) else str(name_obj)
            ).strip()
            if not name:
                continue

            loc = place.get("location", {})
            p_lat = loc.get("latitude")
            p_lon = loc.get("longitude")
            if p_lat is None or p_lon is None:
                continue

            # Refinar categoría con los tipos propios del lugar
            resolved_cat, resolved_val = default_cat, default_val
            for pt in place.get("types", []):
                if pt in _TYPE_TO_CAT and pt != google_type:
                    resolved_cat, resolved_val = _TYPE_TO_CAT[pt]
                    break

            detalle = _build_detalle(place)

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
                    radio_m=int(radio_m),
                )
                n += 1
            except Exception as e:
                if verbose:
                    print(f"  [pois_google] upsert error '{name}': {e}")

    if verbose:
        print(
            f"  [pois_google] {location_uuid}: {n} POIs procesados "
            f"({len(seen_ids)} únicos encontrados)"
        )
    return n
