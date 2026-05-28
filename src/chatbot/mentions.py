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
import unicodedata
from functools import lru_cache
from pathlib import Path
import json

_UBIC_PATH = Path(__file__).parent.parent / "data" / "todas_las_ubicaciones.json"


def _normalize(text: str) -> str:
    """Elimina acentos y devuelve solo alfanuméricos, primer token en CamelCase."""
    nfd = unicodedata.normalize("NFD", text)
    ascii_ = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    token = re.split(r"[\s\-_/]+", ascii_.strip())[0]
    return re.sub(r"[^a-zA-Z0-9]", "", token).capitalize()


@lru_cache(maxsize=1)
def get_mention_map() -> dict:
    """
    Devuelve {slug: entry}.
    Tipos de entry:
      location: {type, uuid, label, org, name}
      zone:     {type, uuid, location_uuid, label, org, name, location_name}
    """
    try:
        with open(_UBIC_PATH, encoding="utf-8") as f:
            orgs = json.load(f)
    except Exception:
        return {}

    result: dict     = {}
    seen_slugs: dict = {}

    def _unique_slug(base: str) -> str:
        if base not in seen_slugs:
            seen_slugs[base] = 0
            return base
        seen_slugs[base] += 1
        return f"{base}{seen_slugs[base]}"

    for org in orgs:
        org_token = _normalize(org.get("name", "Org"))
        for loc in org.get("locations", []):
            loc_uuid  = loc.get("uuid")
            loc_token = _normalize(loc.get("name", "Loc"))
            if not loc_uuid or not loc_token:
                continue

            # ── Ubicación ────────────────────────────────────────────────────
            loc_slug = _unique_slug(f"{org_token}_{loc_token}")
            result[loc_slug] = {
                "type":  "location",
                "uuid":  loc_uuid,
                "label": f"@{loc_slug}",
                "org":   org.get("name", ""),
                "name":  loc.get("name", ""),
            }

            # ── Zonas (solo visibles) ─────────────────────────────────────────
            for zone in loc.get("zones", []):
                if zone.get("hidden"):
                    continue
                zone_uuid = zone.get("uuid")
                zone_name = zone.get("zoneName", "")
                zone_token = _normalize(zone_name)
                if not zone_uuid or not zone_token:
                    continue

                zone_slug = _unique_slug(f"{org_token}_{loc_token}_{zone_token}")
                result[zone_slug] = {
                    "type":          "zone",
                    "uuid":          zone_uuid,
                    "location_uuid": loc_uuid,
                    "label":         f"@{zone_slug}",
                    "org":           org.get("name", ""),
                    "name":          zone_name,
                    "location_name": loc.get("name", ""),
                }

    return result


def parse_mention(text: str) -> tuple[str, str | None, str | None]:
    """
    Busca el primer @Slug en text y devuelve
    (texto_limpio, location_uuid, zone_uuid).
    Para ubicaciones zone_uuid es None.
    Para zonas location_uuid es el de la ubicación padre.
    Si no hay mención válida devuelve (texto_original, None, None).
    """
    mention_map = get_mention_map()
    match = re.search(r"@([A-Za-z0-9_]+)", text)
    if not match:
        return text, None, None

    slug  = match.group(1)
    entry = mention_map.get(slug)
    if not entry:
        return text, None, None

    display_name = entry["name"]
    if entry["type"] == "zone":
        display_name = f"{entry['location_name']} · {entry['name']}"

    clean = text.replace(match.group(0), f"[{display_name}]").strip()

    if entry["type"] == "zone":
        return clean, entry["location_uuid"], entry["uuid"]
    return clean, entry["uuid"], None


def slug_for(location_uuid: str) -> str | None:
    """Devuelve '@Slug' para un uuid dado, o None si no existe."""
    for slug, entry in get_mention_map().items():
        if entry["uuid"] == location_uuid:
            return f"@{slug}"
    return None
