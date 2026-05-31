"""
Componente UI del asistente de chat — botón flotante + modal global.
"""
import time

from dash import html, dcc
import dash_bootstrap_components as dbc

from src.chatbot.mentions import get_mention_map

_C_PRIMARY = "#0052CC"
_C_MUTED   = "#6c757d"
_C_GRID    = "#f2f2f2"
_C_AMBER   = "#f39c12"

SUGGESTED_QUESTIONS = [
    "¿Cuántas visitas hubo la última semana?",
    "¿Cuál fue la hora pico del último mes?",
    "¿Qué % de visitantes son nuevos?",
    "¿Cómo es el perfil socioeconómico del área?",
    "Dame un resumen ejecutivo de esta ubicación",
    "¿Cuánta presión omnicanal tiene esta tienda?",
]


# ── Botón flotante ────────────────────────────────────────────────────────────

def build_chat_fab() -> html.Div:
    return html.Div(
        dbc.Button(
            [
                html.I(className="fas fa-robot", style={"fontSize": "1.3rem"}),
                html.Span("Asistente", className="ms-2 fw-bold",
                          style={"fontSize": "0.85rem"}),
            ],
            id="chat-fab",
            n_clicks=0,
            style={
                "position":     "fixed",
                "bottom":       "28px",
                "left":         "28px",
                "zIndex":       1050,
                "background":   f"linear-gradient(135deg, {_C_PRIMARY} 0%, #003d99 100%)",
                "color":        "white",
                "border":       "none",
                "borderRadius": "50px",
                "padding":      "12px 22px",
                "boxShadow":    "0 4px 18px rgba(0,82,204,0.40)",
                "display":      "flex",
                "alignItems":   "center",
                "transition":   "transform 0.15s ease, box-shadow 0.15s ease",
            },
        ),
    )


# ── Modal global ──────────────────────────────────────────────────────────────

def build_chat_modal() -> dbc.Modal:
    return dbc.Modal(
        [
            dbc.ModalHeader(
                html.Div([
                    html.I(className="fas fa-robot me-2",
                           style={"color": _C_PRIMARY}),
                    html.Span("Asistente PM",
                              style={"fontWeight": "700", "fontSize": "1rem"}),
                ], className="d-flex align-items-center"),
                close_button=True,
                style={"borderBottom": f"1px solid {_C_GRID}"},
            ),

            dbc.ModalBody(
                html.Div([
                    # ── Sidebar de conversaciones ─────────────────────────────
                    html.Div([
                        dbc.Button(
                            [html.I(className="fas fa-plus me-1"), "Nueva"],
                            id="chat-new-btn",
                            size="sm",
                            color="primary",
                            outline=True,
                            n_clicks=0,
                            className="w-100 mb-2",
                            style={"fontSize": "0.76rem", "borderRadius": "8px",
                                   "padding": "5px 8px"},
                        ),
                        html.Div(
                            id="chat-conv-list",
                            style={"overflowY": "auto", "flex": "1",
                                   "minHeight": "0"},
                        ),
                    ], style={
                        "width":         "220px",
                        "minWidth":      "220px",
                        "borderRight":   f"2px solid {_C_GRID}",
                        "padding":       "10px 8px",
                        "display":       "flex",
                        "flexDirection": "column",
                        "height":        "65vh",
                    }),

                    # ── Área de chat ──────────────────────────────────────────
                    html.Div(
                        id="chat-history",
                        style={
                            "flex":      "1",
                            "height":    "65vh",
                            "overflowY": "auto",
                            "padding":   "12px 12px 8px 14px",
                        },
                        children=initial_history_content(),
                    ),
                ], style={"display": "flex", "height": "65vh"}),
                style={"padding": "0"},
            ),

            dbc.ModalFooter(
                html.Div([
                    # ── Dropdown de @menciones (aparece encima del input) ─────
                    html.Div(
                        id="chat-mention-dropdown",
                        style={"display": "none"},
                    ),

                    # ── Input + enviar ────────────────────────────────────────
                    html.Div([
                        dbc.Input(
                            id="chat-input",
                            placeholder="Pregunta o escribe @… para mencionar una ubicación",
                            type="text",
                            debounce=False,
                            n_submit=0,
                            style={
                                "fontSize":     "0.88rem",
                                "borderRadius": "8px 0 0 8px",
                                "border":       f"1px solid {_C_GRID}",
                                "borderRight":  "none",
                            },
                        ),
                        dbc.Button(
                            html.I(className="fas fa-paper-plane"),
                            id="chat-send",
                            n_clicks=0,
                            color="primary",
                            style={"borderRadius": "0 8px 8px 0", "padding": "8px 18px"},
                        ),
                        dcc.Loading(
                            html.Div(id="chat-loading-sink",
                                     style={"display": "none"}),
                            type="circle",
                            color=_C_PRIMARY,
                            style={"position": "absolute", "right": "72px",
                                   "bottom": "18px"},
                        ),
                    ], className="d-flex w-100", style={"position": "relative"}),
                ], className="d-flex flex-column w-100"),
                style={"borderTop": f"1px solid {_C_GRID}",
                       "padding": "10px 20px"},
            ),

            dcc.Store(id="chat-messages-store",  data=[]),
            dcc.Store(id="chat-stream-id",       data=None),
            dcc.Store(id="chat-conv-id",         data=None),
            dcc.Store(id="chat-conv-editing",    data=None),
            dcc.Interval(
                id="chat-stream-interval",
                interval=80,
                disabled=True,
                n_intervals=0,
            ),
        ],
        id="chat-modal",
        is_open=False,
        size="xl",
        centered=True,
        backdrop=True,
        scrollable=False,
        contentClassName="chat-modal-content",
    )


# ── Helpers de conversaciones ─────────────────────────────────────────────────

def _rel_time(ts: float) -> str:
    diff = time.time() - ts
    if diff < 3600:
        return "ahora"
    if diff < 86400:
        return "hoy"
    if diff < 172800:
        return "ayer"
    days = int(diff / 86400)
    return f"hace {days}d"


_BTN_ACTION = {
    "fontSize":   "0.58rem",
    "color":      "#c0c8d8",
    "background": "none",
    "border":     "none",
    "cursor":     "pointer",
    "padding":    "1px 3px",
    "lineHeight": "1",
}


def conv_item(conv: dict, editing: bool = False) -> html.Div:
    cid   = conv["id"]
    title = conv.get("title", "Conversación")
    ts    = conv.get("updated_at", 0)

    if editing:
        body = html.Div([
            dbc.Input(
                id={"type": "conv-rename-input", "id": cid},
                value=title,
                debounce=False,
                n_submit=0,
                size="sm",
                autofocus=True,
                style={"fontSize": "0.74rem", "height": "24px",
                       "padding": "2px 5px", "marginBottom": "3px"},
            ),
            html.Div([
                html.Button(
                    html.I(className="fas fa-check"),
                    id={"type": "conv-rename-confirm", "id": cid},
                    n_clicks=0,
                    style={**_BTN_ACTION, "color": "white",
                           "background": "#28a745", "borderRadius": "4px",
                           "padding": "2px 7px", "marginRight": "3px"},
                ),
                html.Button(
                    html.I(className="fas fa-times"),
                    id={"type": "conv-rename-cancel", "id": cid},
                    n_clicks=0,
                    style={**_BTN_ACTION, "color": "white",
                           "background": "#6c757d", "borderRadius": "4px",
                           "padding": "2px 7px"},
                ),
            ], style={"display": "flex"}),
        ], style={"padding": "4px 6px"})
    else:
        body = html.Div([
            html.Div([
                # Área clickable — sólo el título, separada de los botones
                html.Div(title,
                    id={"type": "conv-item", "id": cid},
                    n_clicks=0,
                    style={
                        "fontSize":     "0.77rem",
                        "color":        "#2c3e50",
                        "overflow":     "hidden",
                        "textOverflow": "ellipsis",
                        "whiteSpace":   "nowrap",
                        "lineHeight":   "1.3",
                        "flex":         "1",
                        "minWidth":     "0",
                        "cursor":       "pointer",
                        "paddingRight": "2px",
                    }),
                # Botones de acción — hermanos del título, sin bubbling
                html.Div([
                    html.Button(html.I(className="fas fa-pen"),
                        id={"type": "conv-rename-btn", "id": cid},
                        n_clicks=0, title="Renombrar", style=_BTN_ACTION),
                    html.Button(html.I(className="fas fa-trash"),
                        id={"type": "conv-delete-btn", "id": cid},
                        n_clicks=0, title="Eliminar",
                        style={**_BTN_ACTION, "color": "#e8b4b8"}),
                ], className="conv-actions",
                   style={"display": "flex", "flexShrink": "0"}),
            ], style={"display": "flex", "alignItems": "center"}),
            html.Div(_rel_time(ts), style={
                "fontSize":  "0.66rem",
                "color":     _C_MUTED,
                "marginTop": "1px",
            }),
        ])

    return html.Div(body,
        style={
            "padding":      "5px 6px",
            "borderRadius": "6px",
            "borderLeft":   "3px solid transparent",
            "marginBottom": "2px",
        },
        className="chat-conv-item",
    )


def build_conv_list(convs: list[dict], editing_id: str | None = None) -> list:
    if not convs:
        return [html.Div("Sin conversaciones", style={
            "fontSize":  "0.74rem",
            "color":     _C_MUTED,
            "textAlign": "center",
            "marginTop": "20px",
        })]
    return [conv_item(c, editing=(c["id"] == editing_id)) for c in convs]


# ── Helpers internos ──────────────────────────────────────────────────────────

def mention_option(slug: str, entry: dict) -> html.Div:
    """Una fila del dropdown de @menciones (ubicación o zona)."""
    is_zone   = entry.get("type") == "zone"
    slug_color = "#4a6fa5" if is_zone else _C_PRIMARY

    if is_zone:
        detail = f"{entry.get('location_name', '')} · {entry.get('name', '')}"
    else:
        detail = f"{entry.get('name', '')} · {entry.get('org', '')}"

    return html.Div(
        [
            html.Span(
                "◎ " if is_zone else "",
                style={"fontSize": "0.70rem", "color": slug_color, "marginRight": "2px"},
            ),
            html.Span(f"@{slug}",
                      style={"fontWeight": "600", "color": slug_color,
                             "fontSize": "0.82rem", "marginRight": "8px"}),
            html.Span(detail,
                      style={"fontSize": "0.79rem", "color": _C_MUTED}),
        ],
        id={"type": "mention-option", "slug": slug},
        n_clicks=0,
        className="mention-option-item",
        style={"padding": "7px 14px", "cursor": "pointer",
               "borderBottom": f"1px solid {_C_GRID}"},
    )


def _suggestion_chips() -> html.Div:
    chips = []
    for q in SUGGESTED_QUESTIONS:
        chips.append(
            dbc.Button(
                q,
                id={"type": "suggestion-chip", "q": q},
                size="sm",
                color="light",
                className="border text-start",
                n_clicks=0,
                style={
                    "fontSize":     "0.78rem",
                    "borderRadius": "20px",
                    "padding":      "4px 12px",
                    "color":        "#2c3e50",
                    "borderColor":  _C_GRID,
                    "whiteSpace":   "normal",
                    "textAlign":    "left",
                },
            )
        )
    return html.Div([
        html.Small("Preguntas sugeridas:", className="text-muted d-block mb-2",
                   style={"fontSize": "0.72rem"}),
        html.Div(chips, className="d-flex flex-wrap gap-2"),
    ], style={"marginTop": "12px", "padding": "12px",
              "background": "#fafbff", "borderRadius": "10px",
              "border": f"1px solid {_C_GRID}"})


def initial_history_content() -> list:
    return [_welcome_message(), _suggestion_chips()]


def _welcome_message() -> html.Div:
    return _bubble(
        "assistant",
        "Hola. Soy tu asistente de análisis. Puedo consultarte datos de tráfico "
        "y del entorno geoespacial de la ubicación activa. ¿En qué te ayudo?",
    )


def _bubble(role: str, text: str) -> html.Div:
    is_user  = role == "user"
    is_cache = not is_user and text.startswith("⚡")
    label    = None
    if is_cache:
        label = html.Span("⚡ caché", style={
            "fontSize": "0.65rem", "color": _C_AMBER,
            "fontWeight": "600", "display": "block", "marginBottom": "2px",
        })
        text = text[1:].strip()

    if is_user:
        inner = html.Span(text)
    else:
        inner = dcc.Markdown(
            text,
            className="chat-markdown",
            dangerously_allow_html=False,
        )

    content = []
    if label:
        content.append(label)
    content.append(inner)

    return html.Div(
        html.Div(
            content,
            style={
                "display":      "inline-block",
                "background":   "#0052CC" if is_user else "white",
                "color":        "white"   if is_user else "#2c3e50",
                "border":       "none"    if is_user else f"1px solid {_C_GRID}",
                "borderRadius": "16px 16px 4px 16px" if is_user else "16px 16px 16px 4px",
                "padding":      "8px 14px",
                "maxWidth":     "82%",
                "fontSize":     "0.86rem",
                "lineHeight":   "1.55",
                "boxShadow":    "0 1px 4px rgba(0,0,0,0.07)",
                "whiteSpace":   "pre-wrap" if is_user else "normal",
            },
        ),
        className=f"d-flex {'justify-content-end' if is_user else 'justify-content-start'} mb-2",
    )


def streaming_bubble(text: str, tool: str | None) -> html.Div:
    """Burbuja del asistente en estado streaming (texto parcial o indicador de tool)."""
    content = []

    if tool:
        content.append(html.Div(
            [
                dbc.Spinner(
                    size="sm",
                    color="primary",
                    spinner_style={"width": "12px", "height": "12px", "marginRight": "6px"},
                ),
                html.Span(tool, style={"fontSize": "0.78rem", "color": _C_MUTED}),
            ],
            className="d-flex align-items-center mb-1",
        ))

    if text:
        display = text if tool else text + " ▍"
        content.append(dcc.Markdown(
            display,
            className="chat-markdown",
            dangerously_allow_html=False,
        ))
    elif not tool:
        content.append(html.Span("▍", className="stream-cursor"))

    return html.Div(
        html.Div(
            content,
            style={
                "display":      "inline-block",
                "background":   "white",
                "color":        "#2c3e50",
                "border":       f"1px solid {_C_GRID}",
                "borderRadius": "16px 16px 16px 4px",
                "padding":      "8px 14px",
                "maxWidth":     "82%",
                "fontSize":     "0.86rem",
                "lineHeight":   "1.55",
                "boxShadow":    "0 1px 4px rgba(0,0,0,0.07)",
                "minWidth":     "44px",
            },
        ),
        className="d-flex justify-content-start mb-2",
    )


def render_history(messages: list[dict]) -> list:
    """Convierte [{role, content}] en burbujas Dash, sin sugerencias."""
    bubbles = [_welcome_message()]
    for msg in messages:
        bubbles.append(_bubble(msg["role"], msg["content"]))
    return bubbles
