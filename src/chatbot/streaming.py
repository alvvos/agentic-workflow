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
import re as _re
import threading
import uuid as _uuid_mod
from pathlib import Path

_UUID_RE = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.I)

import anthropic  # noqa: E402
import diskcache  # noqa: E402

from src.chatbot.cache import set_cached  # noqa: E402
from src.chatbot.client import _TOOL_DEFINITIONS, _system_prompt  # noqa: E402
from src.chatbot.tools import (  # noqa: E402
    compare_locations,
    get_active_features,
    get_anomalies,
    get_cruise_calls,
    get_external_features,
    get_forecast,
    get_gis_data,
    get_hourly_breakdown,
    get_location_info,
    get_model_metrics,
    get_pm_data,
    get_weather_holidays,
)

_CACHE_DIR = Path(__file__).parent.parent / "data" / ".stream_cache"
_dc = diskcache.Cache(str(_CACHE_DIR))

_TOOL_LABELS = {
    "get_pm_data": "Consultando datos de tráfico…",
    "get_gis_data": "Consultando perfil geoespacial…",
    "get_weather_holidays": "Consultando clima y festivos…",
    "get_forecast": "Ejecutando modelo predictivo…",
    "get_anomalies": "Analizando anomalías…",
    "get_hourly_breakdown": "Calculando perfil horario…",
    "compare_locations": "Comparando ubicaciones…",
    "get_location_info": "Consultando datos de la ubicación…",
    "get_active_features": "Consultando features externas activas…",
    "get_external_features": "Consultando series externas…",
    "get_cruise_calls": "Consultando escalas de cruceros…",
    "get_model_metrics": "Consultando métricas del modelo…",
}

_TOOL_FN = {
    "get_pm_data": lambda args: get_pm_data(**args),
    "get_gis_data": lambda args: get_gis_data(**args),
    "get_weather_holidays": lambda args: get_weather_holidays(**args),
    "get_forecast": lambda args: get_forecast(**args),
    "get_anomalies": lambda args: get_anomalies(**args),
    "get_hourly_breakdown": lambda args: get_hourly_breakdown(**args),
    "compare_locations": lambda args: compare_locations(**args),
    "get_location_info": lambda args: get_location_info(**args),
    "get_active_features": lambda args: get_active_features(**args),
    "get_external_features": lambda args: get_external_features(**args),
    "get_cruise_calls": lambda args: get_cruise_calls(**args),
    "get_model_metrics": lambda args: get_model_metrics(**args),
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


# Injection sets — defined once at module level, not per-loop-iteration
_TOOLS_UUID_PARAM = {
    "get_gis_data",
    "get_forecast",
    "get_anomalies",
    "get_hourly_breakdown",
    "get_location_info",
    "get_active_features",
    "get_external_features",
    "get_cruise_calls",
    "get_model_metrics",
}
_TOOLS_ID_PARAM = {"get_pm_data", "get_weather_holidays"}
_TOOLS_SESSION = {
    "get_pm_data",
    "get_forecast",
    "get_anomalies",
    "get_hourly_breakdown",
    "compare_locations",
}
_TOOLS_ZONE_INJECT = {
    "get_forecast",
    "get_anomalies",
    "get_hourly_breakdown",
    "get_pm_data",
    "get_model_metrics",
}


class _NumpySafeEncoder(json.JSONEncoder):
    def default(self, o):
        try:
            import numpy as np

            if isinstance(o, (np.integer,)):
                return int(o)
            if isinstance(o, (np.floating,)):
                return float(o)
            if isinstance(o, np.ndarray):
                return o.tolist()
        except ImportError:
            pass
        try:
            return super().default(o)
        except TypeError:
            return str(o)


def _safe_json(obj) -> str:
    """Serialize obj to JSON, coercing numpy types and falling back gracefully."""
    try:
        return json.dumps(obj, ensure_ascii=False, cls=_NumpySafeEncoder)
    except Exception as exc:
        return json.dumps({"error": f"Serialization error: {exc}"}, ensure_ascii=False)


def _exec_tool(block, location_uuid, zone_uuid, session_id: str) -> str:
    """Execute a single tool_use block and return its JSON result string."""
    try:
        fn = _TOOL_FN.get(block.name)
        args = dict(block.input)

        if location_uuid:
            if block.name in _TOOLS_UUID_PARAM:
                if not _UUID_RE.match(str(args.get("location_uuid", ""))):
                    args["location_uuid"] = location_uuid
            elif block.name in _TOOLS_ID_PARAM:
                if not _UUID_RE.match(str(args.get("location_id", ""))):
                    args["location_id"] = location_uuid

        if block.name in _TOOLS_SESSION:
            args.setdefault("session_id", session_id)

        if zone_uuid and block.name in _TOOLS_ZONE_INJECT:
            args.setdefault("zone_uuid", zone_uuid)

        if fn is None:
            return _safe_json({"error": f"Herramienta desconocida: {block.name}"})

        result = fn(args)
        return _safe_json(result)

    except Exception as exc:
        return _safe_json({"error": f"Error ejecutando {block.name}: {exc}"})


def _run(
    sid: str,
    messages: list,
    location_uuid,
    zone_uuid,
    session_id: str,
    api_key: str,
    extra_mentions=None,
) -> None:
    client = anthropic.Anthropic(api_key=api_key)
    history = list(messages)
    system = _system_prompt(location_uuid, zone_uuid, extra_mentions)
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    last_text = ""  # preserves partial answer across turns

    try:
        for _turn in range(6):
            if _dc.get(f"{sid}_cancel"):
                _set(sid, status="done", text=last_text or "Cancelado.", tool=None)
                return

            accumulated = ""

            try:
                with client.messages.stream(
                    model="claude-sonnet-4-6",
                    max_tokens=2048,
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
                                if accumulated:
                                    last_text = accumulated
                                _set(sid, status="streaming", text=accumulated, tool=None)

                    final_msg = stream.get_final_message()

            except Exception as api_exc:
                # API-level error — surface partial text if we have any
                err_msg = _humanize_error(api_exc)
                if last_text:
                    err_msg = f"{last_text}\n\n---\n*{err_msg}*"
                _set(sid, status="error", text=err_msg, tool=None)
                return

            stop = final_msg.stop_reason

            if stop == "end_turn":
                parts = [b.text for b in final_msg.content if hasattr(b, "text")]
                answer = "\n".join(parts).strip() or last_text
                try:
                    set_cached(last_user, location_uuid, answer)
                except Exception:
                    pass
                _set(sid, status="done", text=answer, tool=None)
                return

            if stop == "tool_use":
                history.append({"role": "assistant", "content": final_msg.content})
                results = [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": _exec_tool(block, location_uuid, zone_uuid, session_id),
                    }
                    for block in final_msg.content
                    if block.type == "tool_use"
                ]
                history.append({"role": "user", "content": results})
                _set(sid, status="streaming", tool=None)
                continue

            # Unexpected stop_reason — stop gracefully
            break

        # Loop ended without end_turn (max turns or unexpected stop)
        fallback = last_text or "No se pudo completar la respuesta. Intenta reformular la pregunta."
        _set(sid, status="done", text=fallback, tool=None)

    except Exception as e:
        err_msg = _humanize_error(e)
        if last_text:
            err_msg = f"{last_text}\n\n---\n*{err_msg}*"
        _set(sid, status="error", text=err_msg, tool=None)


def start(
    messages: list,
    location_uuid=None,
    zone_uuid=None,
    session_id: str = "local_dev",
    extra_mentions=None,
) -> str | None:
    """Lanza el stream en background. Devuelve stream_id o None si no hay API key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    sid = _uuid_mod.uuid4().hex
    _dc.set(sid, {"status": "pending", "text": "", "tool": None}, expire=300)
    threading.Thread(
        target=_run,
        args=(sid, messages, location_uuid, zone_uuid, session_id, api_key, extra_mentions),
        daemon=True,
    ).start()
    return sid


def get_state(sid: str) -> dict:
    return _dc.get(sid) or {"status": "error", "text": "Sesión expirada.", "tool": None}


def cancel(sid: str) -> None:
    _dc.set(f"{sid}_cancel", True, expire=60)
