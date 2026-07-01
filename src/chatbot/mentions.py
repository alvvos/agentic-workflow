"""
Sistema de @menciones para el asistente.

Formato:
  @Org_Location           → selecciona una ubicación
  @Org_Location_Zone      → selecciona una zona concreta

Funciones públicas:
    get_mention_map()             → {slug: {uuid, type, label, org, name, ...}}
    parse_mention(text)           → (clean_text, location_uuid | None, zone_uuid | None)
    slug_for(uuid)                → "@slug" | None
"""

import re
import time
import unicodedata

_mention_map_cache: dict = {}
_mention_map_ts: float = 0.0
_MENTION_TTL = 30.0


def _normalize(text: str) -> str:
    """Elimina acentos y devuelve solo alfanuméricos, primer token en CamelCase."""
    nfd = unicodedata.normalize("NFD", text)
    ascii_ = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    token = re.split(r"[\s\-_/]+", ascii_.strip())[0]
    return re.sub(r"[^a-zA-Z0-9]", "", token).capitalize()


def get_mention_map() -> dict:
    """
    Devuelve {slug: entry} construido desde DuckDB (caché TTL 30 s).
    Tipos de entry:
      location: {type, uuid, label, org, name}
      zone:     {type, uuid, location_uuid, label, org, name, location_name}
    """
    global _mention_map_cache, _mention_map_ts
    if time.time() - _mention_map_ts < _MENTION_TTL and _mention_map_cache:
        return _mention_map_cache

    try:
        from src.db.queries import get_all_orgs, get_locs_for_org, get_zones_for_loc
    except Exception:
        return _mention_map_cache

    result: dict = {}
    seen_slugs: dict = {}

    def _unique_slug(base: str) -> str:
        if base not in seen_slugs:
            seen_slugs[base] = 0
            return base
        seen_slugs[base] += 1
        return f"{base}{seen_slugs[base]}"

    try:
        for org in get_all_orgs():
            org_token = _normalize(org["nombre"])
            for loc in get_locs_for_org(org["org_id"]):
                loc_uuid = loc["ubicacion_id"]
                loc_token = _normalize(loc["nombre"])
                if not loc_uuid or not loc_token:
                    continue

                loc_slug = _unique_slug(f"{org_token}_{loc_token}")
                result[loc_slug] = {
                    "type": "location",
                    "uuid": loc_uuid,
                    "label": f"@{loc_slug}",
                    "org": org["nombre"],
                    "name": loc["nombre"],
                }

                for zone in get_zones_for_loc(loc_uuid):
                    if zone["hidden"]:
                        continue
                    zone_uuid = zone["zona_id"]
                    zone_name = zone["nombre"]
                    zone_token = _normalize(zone_name)
                    if not zone_uuid or not zone_token:
                        continue

                    zone_slug = _unique_slug(f"{org_token}_{loc_token}_{zone_token}")
                    result[zone_slug] = {
                        "type": "zone",
                        "uuid": zone_uuid,
                        "location_uuid": loc_uuid,
                        "label": f"@{zone_slug}",
                        "org": org["nombre"],
                        "name": zone_name,
                        "location_name": loc["nombre"],
                    }
    except Exception:
        return _mention_map_cache

    _mention_map_cache = result
    _mention_map_ts = time.time()
    return result


def parse_all_mentions(text: str) -> tuple[str, list[dict]]:
    """
    Resuelve TODAS las @menciones en text.

    Returns:
        clean_text  — texto con cada @Slug reemplazado por [Nombre · Zona]
        mentions    — lista de dicts {location_uuid, zone_uuid, name, type}
                      en orden de aparición; solo menciones reconocidas
    """
    mention_map = get_mention_map()
    mentions: list[dict] = []
    clean = text

    for match in re.finditer(r"@([A-Za-z0-9_]+)", text):
        slug = match.group(1)
        entry = mention_map.get(slug)
        if not entry:
            continue

        if entry["type"] == "zone":
            display = f"{entry['location_name']} · {entry['name']}"
            mentions.append(
                {
                    "location_uuid": entry["location_uuid"],
                    "zone_uuid": entry["uuid"],
                    "name": display,
                    "type": "zone",
                }
            )
        else:
            display = entry["name"]
            mentions.append(
                {
                    "location_uuid": entry["uuid"],
                    "zone_uuid": None,
                    "name": display,
                    "type": "location",
                }
            )

        clean = clean.replace(match.group(0), f"[{display}]", 1)

    return clean.strip(), mentions


def parse_mention(text: str) -> tuple[str, str | None, str | None]:
    """Compatibilidad: resuelve solo la primera @mención. Usa parse_all_mentions internamente."""
    clean, mentions = parse_all_mentions(text)
    if not mentions:
        return text, None, None
    first = mentions[0]
    return clean, first["location_uuid"], first["zone_uuid"]


def slug_for(location_uuid: str) -> str | None:
    """Devuelve '@Slug' para un uuid dado, o None si no existe."""
    for slug, entry in get_mention_map().items():
        if entry["uuid"] == location_uuid:
            return f"@{slug}"
    return None
