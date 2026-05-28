"""
Callbacks del asistente de chat.
"""
import os
import re

from dash import Input, Output, State, ALL, callback, no_update

from src.chatbot.cache import get_cached
from src.chatbot.chat_panel import render_history, streaming_bubble, mention_option
from src.chatbot.history import add_entry
from src.chatbot.mentions import parse_mention, get_mention_map
from src.chatbot.tools import _find_location

_DROPDOWN_VISIBLE = {
    "display":      "block",
    "maxHeight":    "200px",
    "overflowY":    "auto",
    "background":   "white",
    "border":       "1px solid #b3c8f5",
    "borderRadius": "10px",
    "boxShadow":    "0 -4px 16px rgba(0,82,204,0.12)",
    "marginBottom": "6px",
}
_DROPDOWN_HIDDEN = {"display": "none"}


# ── Abrir / cerrar modal ──────────────────────────────────────────────────────

@callback(
    Output("chat-modal", "is_open"),
    Input("chat-fab",   "n_clicks"),
    State("chat-modal", "is_open"),
    prevent_initial_call=True,
)
def toggle_modal(n, is_open):
    return not is_open


# ── Dropdown de @menciones — mostrar/filtrar al escribir @ ───────────────────

@callback(
    Output("chat-mention-dropdown", "style"),
    Output("chat-mention-dropdown", "children"),
    Input("chat-input", "value"),
    prevent_initial_call=True,
)
def update_mention_dropdown(value):
    if not value:
        return _DROPDOWN_HIDDEN, []

    match = re.search(r"@([A-Za-z0-9_]*)$", value)
    if not match:
        return _DROPDOWN_HIDDEN, []

    query = match.group(1).lower()
    try:
        mmap = get_mention_map()
    except Exception:
        return _DROPDOWN_HIDDEN, []

    options = [
        mention_option(slug, entry.get("name", ""), entry.get("org", ""))
        for slug, entry in mmap.items()
        if not query or query in slug.lower()
    ][:8]

    if not options:
        return _DROPDOWN_HIDDEN, []

    return _DROPDOWN_VISIBLE, options


# ── Selección en el dropdown — insertar slug en input ────────────────────────

@callback(
    Output("chat-input", "value", allow_duplicate=True),
    Input({"type": "mention-option", "slug": ALL}, "n_clicks"),
    State("chat-input", "value"),
    prevent_initial_call=True,
)
def select_mention_option(n_clicks_list, current_value):
    if not any(n_clicks_list):
        return no_update
    from dash import ctx
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update
    slug = triggered.get("slug", "")
    new_value = re.sub(r"@[A-Za-z0-9_]*$", f"@{slug} ", current_value or "")
    return new_value


# ── Chips de sugerencias — insertar en input ──────────────────────────────────

@callback(
    Output("chat-input", "value", allow_duplicate=True),
    Input({"type": "suggestion-chip", "q": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def insert_suggestion(n_clicks_list):
    if not any(n_clicks_list):
        return no_update
    from dash import ctx
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update
    return triggered.get("q", "")


# ── Enviar mensaje ────────────────────────────────────────────────────────────

@callback(
    Output("chat-history",          "children"),
    Output("chat-messages-store",   "data"),
    Output("chat-input",            "value"),
    Output("chat-loading-sink",     "children"),
    Output("chat-stream-interval",  "disabled"),
    Output("chat-stream-id",        "data"),
    Input("chat-send",  "n_clicks"),
    Input("chat-input", "n_submit"),
    State("chat-input",          "value"),
    State("chat-messages-store", "data"),
    State("drop-locs",           "value"),
    State("session-id",          "data"),
    prevent_initial_call=True,
)
def on_send(n_clicks, n_submit, user_text, history, locs, session_id):
    if not user_text or not user_text.strip():
        return no_update, no_update, no_update, no_update, no_update, no_update

    raw_text = user_text.strip()
    history  = history or []

    clean_text, mention_uuid = parse_mention(raw_text)
    dropdown_uuid = locs[0] if isinstance(locs, list) and locs else locs
    location_uuid = mention_uuid or dropdown_uuid

    loc_info      = _find_location(location_uuid) if location_uuid else None
    location_name = loc_info.get("name") if loc_info else None
    display_text  = clean_text if mention_uuid else raw_text

    history.append({"role": "user", "content": display_text})
    api_messages = [{"role": m["role"], "content": m["content"]} for m in history]

    # Cache hit → respuesta inmediata sin streaming
    cached = get_cached(display_text, location_uuid)
    if cached:
        respuesta = f"⚡ {cached}"
        history.append({"role": "assistant", "content": respuesta})
        add_entry(
            question=display_text,
            answer=cached,
            location_uuid=location_uuid,
            location_name=location_name,
            cached=True,
        )
        return render_history(history), history, "", None, True, None

    # Sin API key → error legible
    if not os.environ.get("ANTHROPIC_API_KEY", ""):
        err = "Configura ANTHROPIC_API_KEY en el entorno para activar el asistente."
        history.append({"role": "assistant", "content": err})
        return render_history(history), history, "", None, True, None

    # Iniciar stream en background
    from src.chatbot import streaming
    sid = streaming.start(api_messages, location_uuid, session_id or "local_dev")

    meta = {
        "sid":           sid,
        "location_uuid": location_uuid,
        "location_name": location_name,
        "question":      display_text,
    }
    partial = render_history(history) + [streaming_bubble("", None)]
    return partial, history, "", None, False, meta


# ── Polling del stream ────────────────────────────────────────────────────────

@callback(
    Output("chat-history",          "children",  allow_duplicate=True),
    Output("chat-messages-store",   "data",      allow_duplicate=True),
    Output("chat-stream-interval",  "disabled",  allow_duplicate=True),
    Output("chat-stream-id",        "data",      allow_duplicate=True),
    Input("chat-stream-interval",   "n_intervals"),
    State("chat-stream-id",         "data"),
    State("chat-messages-store",    "data"),
    prevent_initial_call=True,
)
def poll_stream(n_intervals, meta, history):
    if not meta or not meta.get("sid"):
        return no_update, no_update, True, None

    from src.chatbot import streaming
    state  = streaming.get_state(meta["sid"])
    status = state.get("status", "error")
    text   = state.get("text", "")
    tool   = state.get("tool")
    history = history or []

    if status in ("pending", "streaming", "tool"):
        partial = render_history(history) + [streaming_bubble(text, tool)]
        return partial, no_update, False, meta

    # done o error — finalizar
    answer = text or "No se pudo generar la respuesta."
    history.append({"role": "assistant", "content": answer})

    if status == "done":
        add_entry(
            question=meta.get("question", ""),
            answer=answer,
            location_uuid=meta.get("location_uuid"),
            location_name=meta.get("location_name"),
            cached=False,
        )

    return render_history(history), history, True, None
