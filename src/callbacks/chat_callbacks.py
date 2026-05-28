"""
Callbacks del asistente de chat.
"""
import os
import re

from dash import Input, Output, State, ALL, callback, no_update

from src.chatbot.cache import get_cached
from src.chatbot.chat_panel import (
    render_history, streaming_bubble, mention_option,
    build_conv_list, initial_history_content,
)
from src.chatbot.history import (
    create_conversation, update_conversation,
    list_conversations, load_conversation,
)
from src.chatbot.mentions import parse_all_mentions, get_mention_map
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


# ── Cargar lista de conversaciones al abrir el modal ─────────────────────────

@callback(
    Output("chat-conv-list", "children"),
    Input("chat-modal", "is_open"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def on_modal_open(is_open, session_id):
    if not is_open:
        return no_update
    return build_conv_list(list_conversations(session_id or "anonymous"))


# ── Nueva conversación ────────────────────────────────────────────────────────

@callback(
    Output("chat-conv-id",          "data"),
    Output("chat-messages-store",   "data",     allow_duplicate=True),
    Output("chat-history",          "children", allow_duplicate=True),
    Output("chat-conv-list",        "children", allow_duplicate=True),
    Input("chat-new-btn", "n_clicks"),
    State("session-id",   "data"),
    prevent_initial_call=True,
)
def on_new_conversation(n_clicks, session_id):
    if not n_clicks:
        return no_update, no_update, no_update, no_update
    sid   = session_id or "anonymous"
    convs = list_conversations(sid)
    return None, [], initial_history_content(), build_conv_list(convs)


# ── Seleccionar conversación existente ────────────────────────────────────────

@callback(
    Output("chat-conv-id",        "data",     allow_duplicate=True),
    Output("chat-messages-store", "data",     allow_duplicate=True),
    Output("chat-history",        "children", allow_duplicate=True),
    Input({"type": "conv-item", "id": ALL}, "n_clicks"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def on_select_conversation(n_clicks_list, session_id):
    if not any(n_clicks_list):
        return no_update, no_update, no_update
    from dash import ctx
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update, no_update, no_update
    conv_id = triggered.get("id")
    conv = load_conversation(session_id or "anonymous", conv_id)
    if not conv:
        return no_update, no_update, no_update
    messages = conv.get("messages", [])
    return conv_id, messages, render_history(messages)


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

    at_pos = value.rfind("@")
    if at_pos == -1:
        return _DROPDOWN_HIDDEN, []
    fragment = value[at_pos:]
    if " " in fragment:
        return _DROPDOWN_HIDDEN, []
    query = fragment[1:].lower()

    try:
        mmap = get_mention_map()
    except Exception:
        return _DROPDOWN_HIDDEN, []

    options = [
        mention_option(slug, entry)
        for slug, entry in mmap.items()
        if not query or query in slug.lower()
    ][:10]

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
    Output("chat-conv-id",          "data",     allow_duplicate=True),
    Output("chat-conv-list",        "children", allow_duplicate=True),
    Input("chat-send",  "n_clicks"),
    Input("chat-input", "n_submit"),
    State("chat-input",          "value"),
    State("chat-messages-store", "data"),
    State("drop-locs",           "value"),
    State("session-id",          "data"),
    State("chat-conv-id",        "data"),
    prevent_initial_call=True,
)
def on_send(n_clicks, n_submit, user_text, history, locs, session_id, conv_id):
    _nu8 = (no_update,) * 8
    if not user_text or not user_text.strip():
        return _nu8

    raw_text = user_text.strip()
    history  = history or []
    sid      = session_id or "anonymous"

    clean_text, all_mentions = parse_all_mentions(raw_text)
    primary       = all_mentions[0] if all_mentions else None
    dropdown_uuid = locs[0] if isinstance(locs, list) and locs else locs
    location_uuid = (primary["location_uuid"] if primary else None) or dropdown_uuid
    zone_uuid     = primary["zone_uuid"] if primary else None
    extra_mentions = [
        m for m in all_mentions[1:]
        if m["location_uuid"] != location_uuid
    ]

    loc_info      = _find_location(location_uuid) if location_uuid else None
    location_name = loc_info.get("name") if loc_info else None
    display_text  = clean_text if all_mentions else raw_text

    # Create conversation if this is the first message
    if not conv_id:
        conv_id = create_conversation(sid, location_uuid)

    history.append({"role": "user", "content": display_text})
    api_messages = [{"role": m["role"], "content": m["content"]} for m in history]

    # Persist user message immediately
    update_conversation(sid, conv_id, history, location_uuid)
    conv_list = build_conv_list(list_conversations(sid))

    # Cache hit → respuesta inmediata sin streaming
    cached = get_cached(display_text, location_uuid)
    if cached:
        respuesta = f"⚡ {cached}"
        history.append({"role": "assistant", "content": respuesta})
        update_conversation(sid, conv_id, history, location_uuid)
        conv_list = build_conv_list(list_conversations(sid))
        return (render_history(history), history, "", None, True, None,
                conv_id, conv_list)

    # Sin API key → error legible
    if not os.environ.get("ANTHROPIC_API_KEY", ""):
        err = "Configura ANTHROPIC_API_KEY en el entorno para activar el asistente."
        history.append({"role": "assistant", "content": err})
        update_conversation(sid, conv_id, history, location_uuid)
        return (render_history(history), history, "", None, True, None,
                conv_id, conv_list)

    # Iniciar stream en background
    from src.chatbot import streaming
    stream_sid = streaming.start(
        api_messages,
        location_uuid=location_uuid,
        zone_uuid=zone_uuid,
        session_id=session_id or "local_dev",
        extra_mentions=extra_mentions or None,
    )

    meta = {
        "sid":            stream_sid,
        "session_id":     sid,
        "conv_id":        conv_id,
        "location_uuid":  location_uuid,
        "location_name":  location_name,
        "question":       display_text,
        "extra_mentions": extra_mentions or [],
    }
    partial = render_history(history) + [streaming_bubble("", None)]
    return partial, history, "", None, False, meta, conv_id, conv_list


# ── Polling del stream ────────────────────────────────────────────────────────

@callback(
    Output("chat-history",          "children",  allow_duplicate=True),
    Output("chat-messages-store",   "data",      allow_duplicate=True),
    Output("chat-stream-interval",  "disabled",  allow_duplicate=True),
    Output("chat-stream-id",        "data",      allow_duplicate=True),
    Output("chat-conv-list",        "children",  allow_duplicate=True),
    Input("chat-stream-interval",   "n_intervals"),
    State("chat-stream-id",         "data"),
    State("chat-messages-store",    "data"),
    State("session-id",             "data"),
    prevent_initial_call=True,
)
def poll_stream(n_intervals, meta, history, session_id):
    if not meta or not meta.get("sid"):
        return no_update, no_update, True, None, no_update

    from src.chatbot import streaming
    state  = streaming.get_state(meta["sid"])
    status = state.get("status", "error")
    text   = state.get("text", "")
    tool   = state.get("tool")
    history = history or []

    if status in ("pending", "streaming", "tool"):
        partial = render_history(history) + [streaming_bubble(text, tool)]
        return partial, no_update, False, meta, no_update

    # done o error — finalizar
    answer = text or "No se pudo generar la respuesta."
    history.append({"role": "assistant", "content": answer})

    conv_list = no_update
    if status == "done":
        sid     = meta.get("session_id") or session_id or "anonymous"
        conv_id = meta.get("conv_id")
        if conv_id:
            update_conversation(sid, conv_id, history, meta.get("location_uuid"))
            conv_list = build_conv_list(list_conversations(sid))

    return render_history(history), history, True, None, conv_list
