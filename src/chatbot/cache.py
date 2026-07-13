"""
Caché persistente de respuestas del asistente — tabla cache_chatbot en PostgreSQL.
Clave: MD5(pregunta_normalizada + "|" + ubicacion_id).
TTL: 7 días (campo expires_at, limpiado con DELETE en get_cached / clear_cache).
"""

import hashlib
from datetime import datetime, timedelta, timezone

from src.db.store import get_conn

_TTL_SECS = 7 * 24 * 3600


def _key(question: str, location_uuid: str | None) -> str:
    raw = f"{question.strip().lower()}|{location_uuid or ''}"
    return hashlib.md5(raw.encode()).hexdigest()


def get_cached(question: str, location_uuid: str | None) -> str | None:
    """Devuelve la respuesta cacheada o None si no existe / caducó."""
    k = _key(question, location_uuid)
    conn = get_conn()
    row = conn.execute(
        "SELECT respuesta FROM cache_chatbot WHERE clave_cache = %s AND expira_en > NOW()",
        [k],
    ).fetchone()
    if not row:
        return None
    conn.execute(
        "UPDATE cache_chatbot SET aciertos = aciertos + 1 WHERE clave_cache = %s",
        [k],
    )
    return row[0]


def set_cached(question: str, location_uuid: str | None, answer: str) -> None:
    """Almacena o actualiza una respuesta en caché."""
    k = _key(question, location_uuid)
    expires = datetime.now(tz=timezone.utc) + timedelta(seconds=_TTL_SECS)
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO cache_chatbot (clave_cache, pregunta, ubicacion_id, respuesta, expira_en)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (clave_cache) DO UPDATE SET
            respuesta  = EXCLUDED.respuesta,
            creado_en  = CURRENT_TIMESTAMP,
            expira_en  = EXCLUDED.expira_en,
            aciertos   = 0
        """,
        [k, question.strip(), location_uuid, answer, expires],
    )


def clear_cache() -> int:
    """Elimina toda la caché. Devuelve el número de entradas borradas."""
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM cache_chatbot").fetchone()[0]
    conn.execute("DELETE FROM cache_chatbot")
    return n


def purge_expired() -> int:
    """Borra entradas caducadas. Llamar periódicamente o al arrancar."""
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM cache_chatbot WHERE expira_en <= NOW()").fetchone()[0]
    conn.execute("DELETE FROM cache_chatbot WHERE expira_en <= NOW()")
    return n
