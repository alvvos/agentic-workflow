"""
Historial persistente de conversaciones por usuario.
Tablas: chat_conversaciones, chat_mensajes
"""

import json
import logging
import re as _re
import time
import uuid
from datetime import datetime
from typing import Optional

from src.db.store import get_conn

MAX_CONVS = 50
_log = logging.getLogger(__name__)
_UUID_PAT = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.I)


def _safe_uuid(val) -> Optional[str]:
    """Return val if it is a valid UUID string, else None."""
    if val is None:
        return None
    if isinstance(val, str) and _UUID_PAT.match(val.strip()):
        return val.strip()
    return None


def _ts_to_epoch(ts) -> float:
    if ts is None:
        return time.time()
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        return ts.timestamp()
    except Exception:
        return time.time()


def _serialize(content) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False)
    except Exception:
        return str(content)


def _deserialize(text: Optional[str]):
    if text is None:
        return ""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, (list, dict)):
            return parsed
    except Exception:
        pass
    return text


def create_conversation(session_id: str, location_uuid: Optional[str] = None) -> str:
    conv_id = uuid.uuid4().hex[:8]
    try:
        get_conn().execute(
            "INSERT INTO chat_conversaciones (conv_id, user_id, title, location_uuid)"
            " VALUES (?, ?, 'Nueva conversación', ?)",
            [conv_id, session_id or "anonymous", _safe_uuid(location_uuid)],
        )
    except Exception as exc:
        _log.error("create_conversation failed: %s", exc)
    return conv_id


def update_conversation(
    session_id: str,
    conv_id: str,
    messages: list,
    location_uuid: Optional[str] = None,
) -> None:
    safe_loc = _safe_uuid(location_uuid)
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT title FROM chat_conversaciones WHERE conv_id = ?", [conv_id]
        ).fetchone()

        new_title = row[0] if row else "Nueva conversación"
        if new_title == "Nueva conversación":
            first_user = next(
                (
                    m["content"]
                    for m in (messages or [])
                    if m.get("role") == "user" and isinstance(m.get("content"), str)
                ),
                None,
            )
            if first_user:
                new_title = first_user[:50].rstrip()

        now = datetime.now()
        if row:
            conn.execute(
                "UPDATE chat_conversaciones"
                " SET title = ?, updated_at = ?, location_uuid = COALESCE(?, location_uuid)"
                " WHERE conv_id = ?",
                [new_title, now, safe_loc, conv_id],
            )
        else:
            conn.execute(
                "INSERT INTO chat_conversaciones"
                " (conv_id, user_id, title, location_uuid, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [conv_id, session_id or "anonymous", new_title, safe_loc, now],
            )

        conn.execute("DELETE FROM chat_mensajes WHERE conv_id = ?", [conv_id])
        if messages:
            conn.executemany(
                "INSERT INTO chat_mensajes (conv_id, seq, role, content)" " VALUES (?, ?, ?, ?)",
                [
                    (conv_id, i, m.get("role", "user"), _serialize(m.get("content", "")))
                    for i, m in enumerate(messages)
                ],
            )
    except Exception as exc:
        _log.error("update_conversation failed for conv_id=%s: %s", conv_id, exc)


def rename_conversation(session_id: str, conv_id: str, new_title: str) -> None:
    try:
        get_conn().execute(
            "UPDATE chat_conversaciones SET title = ? WHERE conv_id = ? AND user_id = ?",
            [new_title.strip() or "Conversación", conv_id, session_id],
        )
    except Exception as exc:
        _log.error("rename_conversation failed: %s", exc)


def delete_conversation(session_id: str, conv_id: str) -> None:
    try:
        get_conn().execute(
            "DELETE FROM chat_conversaciones WHERE conv_id = ? AND user_id = ?",
            [conv_id, session_id],
        )
    except Exception as exc:
        _log.error("delete_conversation failed: %s", exc)


def list_conversations(session_id: str) -> list[dict]:
    try:
        rows = (
            get_conn()
            .execute(
                "SELECT conv_id, title, updated_at, location_uuid"
                " FROM chat_conversaciones WHERE user_id = ?"
                " ORDER BY updated_at DESC LIMIT ?",
                [session_id, MAX_CONVS],
            )
            .fetchall()
        )
        return [
            {
                "id": r[0],
                "title": r[1] or "Nueva conversación",
                "updated_at": _ts_to_epoch(r[2]),
                "location_uuid": r[3],
            }
            for r in rows
        ]
    except Exception as exc:
        _log.error("list_conversations failed: %s", exc)
        return []


def load_conversation(session_id: str, conv_id: str) -> Optional[dict]:
    try:
        conn = get_conn()
        conv_row = conn.execute(
            "SELECT conv_id, title, created_at, updated_at, location_uuid"
            " FROM chat_conversaciones WHERE conv_id = ? AND user_id = ?",
            [conv_id, session_id],
        ).fetchone()
        if conv_row is None:
            return None

        msg_rows = conn.execute(
            "SELECT role, content FROM chat_mensajes WHERE conv_id = ? ORDER BY seq",
            [conv_id],
        ).fetchall()

        return {
            "id": conv_row[0],
            "title": conv_row[1] or "Nueva conversación",
            "created_at": _ts_to_epoch(conv_row[2]),
            "updated_at": _ts_to_epoch(conv_row[3]),
            "location_uuid": conv_row[4],
            "messages": [{"role": r[0], "content": _deserialize(r[1])} for r in msg_rows],
        }
    except Exception as exc:
        _log.error("load_conversation failed: %s", exc)
        return None
