"""
Caché persistente de respuestas del asistente.
Clave: MD5(pregunta_normalizada + "|" + location_uuid).
TTL: 7 días. Almacenamiento: src/data/chat_cache.json.
"""
import hashlib
import json
import os
import time
from pathlib import Path

_CACHE_PATH = Path(__file__).parent.parent / "data" / "chat_cache.json"
_TTL_SECS   = 7 * 24 * 3600


def _key(question: str, location_uuid: str | None) -> str:
    raw = f"{question.strip().lower()}|{location_uuid or ''}"
    return hashlib.md5(raw.encode()).hexdigest()


def _load() -> dict:
    if not _CACHE_PATH.exists():
        return {}
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict) -> None:
    tmp = _CACHE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _CACHE_PATH)


def get_cached(question: str, location_uuid: str | None) -> str | None:
    """Devuelve la respuesta cacheada o None si no existe / caducó."""
    data   = _load()
    entry  = data.get(_key(question, location_uuid))
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > _TTL_SECS:
        return None
    # Incrementar hits
    entry["hits"] = entry.get("hits", 0) + 1
    _save(data)
    return entry["answer"]


def set_cached(question: str, location_uuid: str | None, answer: str) -> None:
    """Almacena una nueva respuesta en caché."""
    data  = _load()
    k     = _key(question, location_uuid)
    data[k] = {
        "question":      question.strip(),
        "location_uuid": location_uuid,
        "answer":        answer,
        "ts":            time.time(),
        "hits":          0,
    }
    _save(data)


def clear_cache() -> int:
    """Elimina toda la caché. Devuelve el número de entradas borradas."""
    data = _load()
    n    = len(data)
    _save({})
    return n
