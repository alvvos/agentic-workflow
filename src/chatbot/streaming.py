"""
Stream de respuestas con hilo background y diskcache como buffer compartido.

Estado en caché (TTL 5 min):
    {
        "status": "pending" | "streaming" | "tool" | "done" | "error",
        "text":   str,        # texto acumulado
        "tool":   str | None  # etiqueta del tool activo
    }
"""
import json
import os
import threading
import uuid as _uuid_mod
from pathlib import Path

import anthropic
import diskcache

from src.chatbot.cache import set_cached
from src.chatbot.client import _TOOL_DEFINITIONS, _system_prompt
from src.chatbot.tools import get_pm_data, get_gis_data, get_weather_holidays

_CACHE_DIR = Path(__file__).parent.parent / "data" / ".stream_cache"
_dc = diskcache.Cache(str(_CACHE_DIR))

_TOOL_LABELS = {
    "get_pm_data":          "Consultando datos de tráfico…",
    "get_gis_data":         "Consultando perfil geoespacial…",
    "get_weather_holidays": "Consultando clima y festivos…",
}

_TOOL_FN = {
    "get_pm_data":          lambda args: get_pm_data(**args),
    "get_gis_data":         lambda args: get_gis_data(**args),
    "get_weather_holidays": lambda args: get_weather_holidays(**args),
}


def _humanize_error(e: Exception) -> str:
    msg = str(e).lower()
    if "authentication" in msg or "api_key" in msg or "401" in msg:
        return "No se pudo autenticar con el servicio. Contacta con el administrador."
    if "rate" in msg or "429" in msg:
        return "Se han realizado demasiadas consultas. Espera unos segundos e inténtalo de nuevo."
    if "timeout" in msg or "timed out" in msg:
        return "La consulta tardó demasiado. Inténtalo de nuevo."
    if "connection" in msg or "network" in msg:
        return "No se pudo conectar con el servicio. Comprueba tu conexión."
    return "No se pudo generar la respuesta. Intenta reformular la pregunta."


def _set(sid: str, **kw) -> None:
    cur = _dc.get(sid) or {}
    cur.update(kw)
    _dc.set(sid, cur, expire=300)


def _run(sid: str, messages: list, location_uuid, session_id: str, api_key: str) -> None:
    client  = anthropic.Anthropic(api_key=api_key)
    history = list(messages)
    system  = _system_prompt(location_uuid)
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

    try:
        for _turn in range(5):
            if _dc.get(f"{sid}_cancel"):
                break

            accumulated = ""

            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system,
                tools=_TOOL_DEFINITIONS,
                messages=history,
            ) as stream:
                for event in stream:
                    if _dc.get(f"{sid}_cancel"):
                        break
                    etype = getattr(event, "type", "")
                    if etype == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", "") == "tool_use":
                            label = _TOOL_LABELS.get(getattr(block, "name", ""), "Consultando…")
                            _set(sid, status="tool", tool=label)
                    elif etype == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta and getattr(delta, "type", "") == "text_delta":
                            accumulated += getattr(delta, "text", "")
                            _set(sid, status="streaming", text=accumulated, tool=None)

                final_msg = stream.get_final_message()

            stop = final_msg.stop_reason

            if stop == "end_turn":
                parts = [b.text for b in final_msg.content if hasattr(b, "text")]
                answer = "\n".join(parts).strip()
                set_cached(last_user, location_uuid, answer)
                _set(sid, status="done", text=answer, tool=None)
                return

            if stop == "tool_use":
                history.append({"role": "assistant", "content": final_msg.content})
                results = []
                for block in final_msg.content:
                    if block.type != "tool_use":
                        continue
                    fn   = _TOOL_FN.get(block.name)
                    args = {**block.input}
                    if block.name == "get_pm_data":
                        args.setdefault("session_id", session_id)
                    res  = fn(args) if fn else {"error": f"Herramienta desconocida: {block.name}"}
                    results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     json.dumps(res, ensure_ascii=False),
                    })
                history.append({"role": "user", "content": results})
                _set(sid, status="streaming", tool=None)
                continue

            break

        if (_dc.get(sid) or {}).get("status") not in ("done", "error"):
            _set(sid, status="done", tool=None)

    except Exception as e:
        _set(sid, status="error", text=_humanize_error(e), tool=None)


def start(messages: list, location_uuid=None, session_id: str = "local_dev") -> str | None:
    """Lanza el stream en background. Devuelve stream_id o None si no hay API key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    sid = _uuid_mod.uuid4().hex
    _dc.set(sid, {"status": "pending", "text": "", "tool": None}, expire=300)
    threading.Thread(
        target=_run, args=(sid, messages, location_uuid, session_id, api_key), daemon=True
    ).start()
    return sid


def get_state(sid: str) -> dict:
    return _dc.get(sid) or {"status": "error", "text": "Sesión expirada.", "tool": None}


def cancel(sid: str) -> None:
    _dc.set(f"{sid}_cancel", True, expire=60)
