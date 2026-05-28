"""
Historial persistente de conversaciones por usuario.
Almacena conversaciones completas en src/data/conversations/<session_id>/.
"""
import json
import os
import time
import uuid
from pathlib import Path

_CONV_ROOT = Path(__file__).parent.parent / "data" / "conversations"
MAX_CONVS  = 50


def _user_dir(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "anonymous"
    d = _CONV_ROOT / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(session_id: str) -> Path:
    return _user_dir(session_id) / "_index.json"


def _conv_path(session_id: str, conv_id: str) -> Path:
    return _user_dir(session_id) / f"{conv_id}.json"


def _load_index(session_id: str) -> list:
    p = _index_path(session_id)
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_index(session_id: str, index: list) -> None:
    p = _index_path(session_id)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def create_conversation(session_id: str, location_uuid: str | None = None) -> str:
    conv_id = uuid.uuid4().hex[:8]
    now = time.time()
    conv = {
        "id":            conv_id,
        "title":         "Nueva conversación",
        "created_at":    now,
        "updated_at":    now,
        "location_uuid": location_uuid,
        "messages":      [],
    }
    _atomic_write(_conv_path(session_id, conv_id), conv)
    index = _load_index(session_id)
    index.insert(0, {
        "id":            conv_id,
        "title":         "Nueva conversación",
        "updated_at":    now,
        "location_uuid": location_uuid,
    })
    _save_index(session_id, index[:MAX_CONVS])
    return conv_id


def update_conversation(
    session_id:    str,
    conv_id:       str,
    messages:      list,
    location_uuid: str | None = None,
) -> None:
    """Persiste el array completo de mensajes. Auto-genera título del primer mensaje de usuario."""
    p = _conv_path(session_id, conv_id)
    now = time.time()
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                conv = json.load(f)
        except Exception:
            conv = {"id": conv_id, "title": "Nueva conversación", "created_at": now}
    else:
        conv = {"id": conv_id, "title": "Nueva conversación", "created_at": now}

    if conv.get("title") == "Nueva conversación":
        first_user = next((m["content"] for m in messages if m["role"] == "user"), None)
        if first_user:
            conv["title"] = first_user[:50].rstrip()

    conv["updated_at"] = now
    conv["messages"]   = messages
    if location_uuid:
        conv["location_uuid"] = location_uuid
    _atomic_write(p, conv)

    index = _load_index(session_id)
    for entry in index:
        if entry["id"] == conv_id:
            entry["title"]      = conv["title"]
            entry["updated_at"] = now
            if location_uuid:
                entry["location_uuid"] = location_uuid
            break
    else:
        index.insert(0, {
            "id":            conv_id,
            "title":         conv["title"],
            "updated_at":    now,
            "location_uuid": location_uuid,
        })
    index.sort(key=lambda e: e["updated_at"], reverse=True)
    _save_index(session_id, index[:MAX_CONVS])


def list_conversations(session_id: str) -> list[dict]:
    return _load_index(session_id)


def load_conversation(session_id: str, conv_id: str) -> dict | None:
    p = _conv_path(session_id, conv_id)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
