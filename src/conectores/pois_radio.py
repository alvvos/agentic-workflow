"""
Conector para consultar POIs en un radio via Esri ArcGIS Places API.

Interfaz pública:
    TIPO = "pois_radio"
    sync(ubicacion_id, cfg, verbose) -> int
    sync_esri_places_location(location_uuid, params, verbose) -> int   ← llamada desde admin_pois.py
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

TIPO = "pois_radio"


def sync(ubicacion_id: str, cfg: dict, verbose: bool = True) -> int:
    """
    Consulta Esri Places API y upsertea POIs en puntos_interes.

    ubicacion_id: UUID de la ubicación.
    cfg: config efectiva — puede sobrescribir radio_m, max_resultados y categorias.
    No llama a is_fresh() ni write_sync_marker() — los gestiona el orquestador.
    Devuelve el número de POIs procesados.
    """
    token = os.environ.get("ESRI_KEY", "")
    if not token:
        if verbose:
            print(f"  [pois_radio] {ubicacion_id}: ESRI_KEY no encontrado, omitido")
        return 0
    return sync_esri_places_location(ubicacion_id, cfg, verbose)


def sync_esri_places_location(
    location_uuid: str,
    params: dict | None = None,
    verbose: bool = True,
) -> int:
    """
    Llama a Esri Places, upsertea resultados en puntos_interes.
    Expuesta públicamente para uso desde src/callbacks/admin_pois.py
    y para la compatibilidad en sync_mensual.py.
    Devuelve número de POIs procesados.
    """
    from src.data_ingestion._common import get_source_config
    from src.db.queries import upsert_poi
    from src.db.store import get_conn

    token = os.environ.get("ESRI_KEY", "")
    if not token:
        if verbose:
            print(f"  [pois_radio] {location_uuid}: ESRI_KEY no encontrado, omitido")
        return 0

    params = params or {}
    cfg = get_source_config("esri_places", params)
    base_url = cfg["base_url"]
    near_point_url = base_url + "/places/near-point"
    radio_m_default = int(cfg.get("radio_m", 1200))
    page_size = int(cfg.get("page_size", 20))
    max_cat_per_call = int(cfg.get("max_category_ids_per_call", 10))
    cat_map_raw = cfg.get("categorias", {})
    cat_map_default: dict[str, tuple[str, str]] = {k: tuple(v) for k, v in cat_map_raw.items()}  # type: ignore[misc]
    valores_cat: dict[str, float] = cfg.get("valores_categoria", {"otro": 0.50})

    def _get_loc_coords():
        row = (
            get_conn()
            .execute(
                "SELECT lat, lon FROM ubicaciones WHERE ubicacion_id = ? AND lat IS NOT NULL",
                [location_uuid],
            )
            .fetchone()
        )
        return (row[0], row[1]) if row else None

    def _get_org_uuid():
        row = (
            get_conn()
            .execute(
                "SELECT org_id FROM ubicaciones WHERE ubicacion_id = ?",
                [location_uuid],
            )
            .fetchone()
        )
        return row[0] if row else None

    def _call_near_point(
        lat: float,
        lon: float,
        radio_m: int,
        category_ids: list[str],
        page_token: str | None = None,
    ) -> dict:
        p: dict = {
            "y": lat,
            "x": lon,
            "radius": radio_m,
            "categoryIds": ",".join(category_ids),
            "pageSize": page_size,
            "f": "json",
            "token": token,
        }
        if page_token:
            p["pageToken"] = page_token
        url = near_point_url + "?" + urllib.parse.urlencode(p)
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def _fetch_page_batch(
        lat: float,
        lon: float,
        radio_m: int,
        category_ids: list[str],
        max_resultados: int,
    ) -> list[dict]:
        results = []
        page_token = None
        while len(results) < max_resultados:
            try:
                data = _call_near_point(lat, lon, radio_m, category_ids, page_token)
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
            parsed = urllib.parse.urlparse(next_url)
            qs = urllib.parse.parse_qs(parsed.query)
            page_token = qs.get("pageToken", [None])[0]
            if not page_token:
                break
        return results

    def _fetch_all_places(
        lat: float, lon: float, radio_m: int, category_ids: list[str], max_resultados: int
    ) -> list[dict]:
        seen: set[str] = set()
        results: list[dict] = []
        batches = [
            category_ids[i : i + max_cat_per_call]
            for i in range(0, len(category_ids), max_cat_per_call)
        ]
        for batch in batches:
            for place in _fetch_page_batch(lat, lon, radio_m, batch, max_resultados):
                pid = place.get("placeId", "")
                if pid and pid in seen:
                    continue
                if pid:
                    seen.add(pid)
                results.append(place)
                if len(results) >= max_resultados:
                    return results
        return results

    def _place_to_poi(place: dict, cat_map: dict) -> dict | None:
        name = (place.get("name") or "").strip()
        if not name:
            return None
        loc = place.get("location", {})
        lon = loc.get("x")
        lat = loc.get("y")
        if lat is None or lon is None:
            return None
        cats = place.get("categories", [])
        categoria = "otro"
        valor = valores_cat.get("otro", 0.50)
        for c in cats:
            cid = str(c.get("categoryId", ""))
            if cid in cat_map:
                categoria, _ = cat_map[cid]
                valor = valores_cat.get(categoria, 0.5)
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

    coords = _get_loc_coords()
    if not coords:
        if verbose:
            print(f"  [pois_radio] {location_uuid}: sin coordenadas, omitido")
        return 0

    org_uuid = _get_org_uuid()
    if not org_uuid:
        return 0

    lat, lon = coords
    radio_m = int(params.get("radio_m", radio_m_default))
    max_res = int(params.get("max_resultados", 200))

    cat_ids_cfg = params.get("categorias")
    if cat_ids_cfg:
        cat_map: dict[str, tuple[str, str]] = {
            cid: cat_map_default.get(cid, ("otro", cid)) for cid in cat_ids_cfg
        }
    else:
        cat_map = cat_map_default.copy()

    try:
        places = _fetch_all_places(lat, lon, radio_m, list(cat_map.keys()), max_res)
    except RuntimeError as e:
        if verbose:
            print(f"  [pois_radio] {location_uuid} ERROR — {e}")
        return 0

    n = 0
    for place in places:
        poi = _place_to_poi(place, cat_map)
        if poi is None:
            continue
        try:
            upsert_poi(
                ubicacion_id=location_uuid,
                org_id=org_uuid,
                fuente="esri_places",
                **poi,
            )
            n += 1
        except Exception as e:
            if verbose:
                print(f"  [pois_radio] upsert error '{poi['nombre']}': {e}")

    if verbose:
        print(f"  [pois_radio] {location_uuid}: {n} POIs sincronizados ({len(places)} encontrados)")
    return n
