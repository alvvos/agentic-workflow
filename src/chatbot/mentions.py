"""
Sistema de @menciones para el asistente.

Formato: @Org_Location  (ej. @Miniso_Malaga, @Barcelo_Royal)
- Primer token de la org  (sin acentos, sin espacios)
- Primer token del nombre de ubicación (sin acentos, sin espacios)

Funciones públicas:
    get_mention_map()  → {slug: {uuid, label, org}}
    parse_mention(text) → (clean_text, location_uuid | None)
    slug_for(uuid)      → "@slug" | None
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
    token = re.split(r"[\s\-_]+", ascii_.strip())[0]
    return re.sub(r"[^a-zA-Z0-9]", "", token).capitalize()


@lru_cache(maxsize=1)
def get_mention_map() -> dict:
    """
    Devuelve {slug: {"uuid": ..., "label": ..., "org": ...}}.
    Resultado cacheado en memoria (lru_cache) — releer llamando get_mention_map.cache_clear().
    """
    try:
        with open(_UBIC_PATH, encoding="utf-8") as f:
            orgs = json.load(f)
    except Exception:
        return {}

    result   = {}
    seen_slugs: dict[str, int] = {}

    for org in orgs:
        org_token = _normalize(org.get("name", "Org"))
        for loc in org.get("locations", []):
            uuid      = loc.get("uuid")
            loc_token = _normalize(loc.get("name", "Loc"))
            if not uuid or not loc_token:
                continue

            base_slug = f"{org_token}_{loc_token}"
            # Desambiguar duplicados añadiendo sufijo numérico
            if base_slug in seen_slugs:
                seen_slugs[base_slug] += 1
                slug = f"{base_slug}{seen_slugs[base_slug]}"
            else:
                seen_slugs[base_slug] = 0
                slug = base_slug

            result[slug] = {
                "uuid":  uuid,
                "label": f"@{slug}",
                "org":   org.get("name", ""),
                "name":  loc.get("name", ""),
            }

    return result


def parse_mention(text: str) -> tuple[str, str | None]:
    """
    Busca el primer @Slug en text y devuelve (texto_limpio, location_uuid).
    Si no hay mención válida, devuelve (texto_original, None).
    """
    mention_map = get_mention_map()
    match = re.search(r"@([A-Za-z0-9_]+)", text)
    if not match:
        return text, None

    slug  = match.group(1)
    entry = mention_map.get(slug)
    if not entry:
        return text, None

    clean = text.replace(match.group(0), f"[{entry['name']}]").strip()
    return clean, entry["uuid"]


def slug_for(location_uuid: str) -> str | None:
    """Devuelve '@Slug' para un uuid dado, o None si no existe."""
    for slug, entry in get_mention_map().items():
        if entry["uuid"] == location_uuid:
            return f"@{slug}"
    return None
