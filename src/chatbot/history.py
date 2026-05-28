"""
Historial persistente de conversaciones del asistente.
Almacena las últimas MAX_ENTRIES preguntas/respuestas en src/data/chat_history.json.
"""
import json
import os
import time
from pathlib import Path

_HISTORY_PATH = Path(__file__).parent.parent / "data" / "chat_history.json"
MAX_ENTRIES   = 20


def _load() -> list:
    if not _HISTORY_PATH.exists():
        return []
    try:
        with open(_HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(entries: list) -> None:
    tmp = _HISTORY_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _HISTORY_PATH)


def add_entry(
    question:      str,
    answer:        str,
    location_uuid: str | None,
    location_name: str | None,
    cached:        bool = False,
) -> None:
    entries = _load()
    entries.insert(0, {
        "question":      question.strip(),
        "answer":        answer,
        "location_uuid": location_uuid,
        "location_name": location_name or location_uuid,
        "cached":        cached,
        "ts":            time.time(),
    })
    _save(entries[:MAX_ENTRIES])


def get_recent(n: int = 6) -> list[dict]:
    return _load()[:n]
