from datetime import datetime

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html, no_update

from src.core.data_master import mapa_tiendas
from src.db.queries import get_df_enriquecido, get_zones_for_loc
from src.layout.components.loaders import loading_section
from src.services.ml_predictivo import ejecutar_auditoria_predictiva

_C_PRIMARY = "#0052CC"
_C_DARK = "#1a1a2e"
_C_MUTED = "#7f8c8d"
_DIAS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
_DIAS_LARGO = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
_CFG = {"displayModeBar": False, "staticPlot": True}


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _fiabilidad(accuracy):
    """Traduce accuracy numérico a label/color/icono legible por el cliente."""
    if accuracy in ("N/A", None):
        return "Datos insuficientes", "secondary", "fas fa-circle-question"
    try:
        v = float(str(accuracy).replace("%", ""))
    except Exception:
        return "Datos insuficientes", "secondary", "fas fa-circle-question"
    if v >= 85:
        return "Alta fiabilidad", "success", "fas fa-circle-check"
    elif v >= 70:
        return "Fiabilidad media", "warning", "fas fa-triangle-exclamation"
    else:
        return "Datos limitados", "secondary", "fas fa-circle-question"


def _color_zona(idx: int) -> str:
    palette = ["#0052CC", "#e67e22", "#27ae60", "#8e44ad", "#e74c3c", "#1abc9c", "#2980b9"]
    return palette[idx % len(palette)]


def _ordenar_zonas_fuera_dentro(zonas: list[dict]) -> list[dict]:
    """Ordena zonas de exterior (sin padre) a interior (con padre) por profundidad BFS.
    Dentro del mismo nivel, alfabéticamente por nombre."""
    by_uuid = {z["zona_id"]: z for z in zonas}
    # Calcula profundidad de cada zona
    depth: dict[str, int] = {}

    def _depth(uuid: str) -> int:
        if uuid in depth:
            return depth[uuid]
        z = by_uuid.get(uuid)
        if z is None or not z.get("parent_zona_id"):
            depth[uuid] = 0
        else:
            depth[uuid] = _depth(z["parent_zona_id"]) + 1
        return depth[uuid]

    for z in zonas:
        _depth(z["zona_id"])
    return sorted(zonas, key=lambda z: (_depth(z["zona_id"]), z["nombre"]))


def _zona_card(nombre: str, res: dict, color: str) -> dbc.Col:
    fechas = res["grafica"]["fechas"]
    predichos = [max(0, int(round(v))) for v in res["grafica"]["predichos"]]
    reales = res["grafica"]["reales"]
    lowers = res["grafica"].get("lower")
    uppers = res["grafica"].get("upper")
    m = res["metricas"]

    fiab_txt, fiab_color, fiab_icon = _fiabilidad(m.get("accuracy"))

    # Headline: primer día predicho
    primera_fecha = pd.to_datetime(fechas[0]) if fechas else None
    primera_val = predichos[0] if predichos else 0
    dia_lbl = _DIAS_LARGO[primera_fecha.dayofweek] if primera_fecha else ""
    fecha_lbl = primera_fecha.strftime("%d/%m") if primera_fecha else ""

    # Tendencia: predicho próximos 7 días vs reales 7 días anteriores disponibles
    reales_val = [r for r in (reales or []) if r is not None]
    tendencia_el = html.Span()
    if reales_val and predichos:
        media_real = sum(reales_val) / len(reales_val)
        media_pred = sum(predichos) / len(predichos)
        if media_real > 0:
            pct = (media_pred - media_real) / media_real * 100
            if abs(pct) < 3:
                tendencia_el = html.Span(
                    "= Sin cambios significativos",
                    className="text-muted",
                    style={"fontSize": "0.72rem"},
                )
            else:
                flecha = "▲" if pct > 0 else "▼"
                col_t = "#27ae60" if pct > 0 else "#e74c3c"
                tendencia_el = html.Span(
                    f"{flecha} {abs(pct):.0f}% vs período anterior",
                    style={"color": col_t, "fontSize": "0.72rem", "fontWeight": "600"},
                )

    # Mini gráfico 7 días — línea + banda de confianza
    x_labels = []
    for f in fechas:
        dt = pd.to_datetime(f)
        x_labels.append(f"{_DIAS_ES[dt.dayofweek]}<br>{dt.strftime('%d')}")

    max_v = max(predichos, default=1) or 1
    band_top = max(uppers) if uppers else max_v
    y_ceil = band_top * 1.45
    y_floor = max(0, min(lowers) * 0.6) if lowers else 0

    fig = go.Figure()

    # Banda IC90% sombreada
    if lowers and uppers:
        fig.add_trace(
            go.Scatter(
                x=x_labels + x_labels[::-1],
                y=uppers + lowers[::-1],
                fill="toself",
                fillcolor=_rgba(color, 0.12),
                line=dict(width=0),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    # Línea principal de predicción
    fig.add_trace(
        go.Scatter(
            x=x_labels,
            y=predichos,
            mode="lines+markers+text",
            line=dict(color=color, width=2, shape="spline", smoothing=0.8),
            marker=dict(color="white", size=7, symbol="circle", line=dict(color=color, width=2)),
            text=[f"{v:,}" for v in predichos],
            textposition="top center",
            textfont=dict(size=8, color=_C_DARK, family="monospace"),
            hovertemplate="%{x}: <b>%{y:,}</b> visitas<extra></extra>",
            showlegend=False,
        )
    )

    fig.update_layout(
        height=170,
        margin=dict(t=28, b=4, l=4, r=4),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            showgrid=False,
            tickfont=dict(size=9, color=_C_DARK),
            fixedrange=True,
            showline=False,
            zeroline=False,
        ),
        yaxis=dict(visible=False, fixedrange=True, range=[y_floor, y_ceil]),
        showlegend=False,
    )

    return dbc.Col(
        dbc.Card(
            [
                dbc.CardBody(
                    [
                        # Cabecera zona
                        html.Div(
                            [
                                html.Span(
                                    nombre,
                                    className="fw-bold text-dark",
                                    style={
                                        "fontSize": "0.82rem",
                                        "textTransform": "uppercase",
                                        "letterSpacing": "0.6px",
                                    },
                                ),
                            ],
                            className="d-flex align-items-center justify-content-between mb-3",
                        ),
                        # Número grande: próximo día
                        html.Div(
                            [
                                html.Div(
                                    f"{dia_lbl} {fecha_lbl}",
                                    className="text-muted mb-0",
                                    style={"fontSize": "0.72rem"},
                                ),
                                html.Div(
                                    f"{primera_val:,}",
                                    className="fw-bold text-dark lh-1",
                                    style={"fontSize": "1.9rem"},
                                ),
                                *(
                                    [
                                        dbc.Badge(
                                            f"IC90%  {lowers[0]:,} – {uppers[0]:,}",
                                            color="light",
                                            text_color="primary",
                                            className="border border-primary-subtle fw-normal mt-1",
                                            style={
                                                "fontSize": "0.63rem",
                                                "cursor": "default",
                                                "letterSpacing": "0.3px",
                                            },
                                            title=(
                                                "Intervalo de confianza conformal al 90 %.\n"
                                                "El modelo estima que el número real de visitas caerá\n"
                                                "dentro de este rango en 9 de cada 10 días.\n"
                                                "Se calcula a partir de los residuos históricos del propio modelo."
                                            ),
                                        )
                                    ]
                                    if lowers and uppers
                                    else []
                                ),
                                html.Div(
                                    "visitas previstas",
                                    className="text-muted mb-1",
                                    style={"fontSize": "0.70rem"},
                                ),
                                tendencia_el,
                            ],
                            className="mb-3",
                        ),
                        # Mini gráfico
                        dcc.Graph(
                            figure=fig, config=_CFG, style={"height": "170px", "marginX": "-4px"}
                        ),
                    ],
                    className="p-3",
                ),
            ],
            className="border-0 shadow-sm rounded-4 h-100 bg-white",
        ),
        xs=12,
        sm=6,
        lg=4,
        className="mb-3",
    )


def _empty_state(msg: str = "") -> html.Div:
    return html.Div(
        [
            html.P(
                msg or "Selecciona una ubicación en el panel izquierdo para ver la previsión.",
                className="text-muted",
            ),
        ],
        className="text-center py-5",
    )


def _zona_card_insuficiente(nombre: str, color: str) -> dbc.Col:
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(
                        html.Span(
                            nombre,
                            className="fw-bold text-dark",
                            style={
                                "fontSize": "0.82rem",
                                "textTransform": "uppercase",
                                "letterSpacing": "0.6px",
                            },
                        ),
                        className="mb-3",
                    ),
                    html.Div(
                        [
                            html.Span(
                                "Datos insuficientes para generar previsión.",
                                className="text-muted small",
                            ),
                        ]
                    ),
                    html.P(
                        "Se necesitan al menos 30 días de historial.",
                        className="text-muted",
                        style={"fontSize": "0.72rem"},
                    ),
                ],
                className="p-3",
            ),
            className="border-0 shadow-sm rounded-4 h-100 bg-white",
            style={"borderLeft": f"3px solid {color}"},
        ),
        xs=12,
        sm=6,
        lg=4,
        className="mb-3",
    )


def _loc_section(loc_nombre: str, zona_cols: list) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        loc_nombre, className="fw-bold text-dark", style={"fontSize": "1rem"}
                    ),
                ],
                className="d-flex align-items-center mb-3",
            ),
            dbc.Row(zona_cols, className="g-3"),
        ],
        className="mb-5",
    )


# ── Layout ─────────────────────────────────────────────────────────────────────


def build_tab_prediccion_cliente(role: str = "viewer"):
    is_admin = role == "admin"

    if is_admin:
        tab_content = html.Div(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.H4(
                                    "Previsión de visitas",
                                    className="fw-bold mb-1 text-dark",
                                ),
                                html.P(
                                    "Próximos 7 días · pulsa Aplicar tras seleccionar ubicación.",
                                    className="text-muted small mb-0",
                                ),
                            ],
                            width=12,
                        ),
                    ],
                    className="mb-4",
                ),
                loading_section(
                    html.Div(
                        id="pred-publica-content",
                        children=_empty_state(),
                        style={"minHeight": "60vh"},
                    ),
                    label="Calculando previsión...",
                    overlay_id="pred-render-overlay",
                    min_height="60vh",
                ),
            ],
            className="p-3",
        )
    else:
        tab_content = html.Div(
            [
                html.Div(id="pred-publica-content", style={"display": "none"}),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Div(
                                    style={
                                        "width": "48px",
                                        "height": "4px",
                                        "backgroundColor": _C_PRIMARY,
                                        "borderRadius": "2px",
                                        "margin": "0 auto 24px",
                                    }
                                ),
                                html.H5(
                                    "Predicción de afluencia",
                                    className="fw-bold text-dark mb-2",
                                ),
                                html.P(
                                    "Esta funcionalidad está en desarrollo.",
                                    className="text-muted mb-1",
                                    style={"fontSize": "0.95rem"},
                                ),
                                html.P(
                                    "Próximamente dispondrás de previsiones de visitas para los próximos 7 días "
                                    "con intervalos de confianza basados en histórico, climatología y festivos.",
                                    className="text-muted",
                                    style={
                                        "fontSize": "0.82rem",
                                        "maxWidth": "420px",
                                        "margin": "0 auto",
                                    },
                                ),
                            ],
                            className="text-center",
                        )
                    ],
                    className="d-flex align-items-center justify-content-center",
                    style={"minHeight": "55vh"},
                ),
            ]
        )

    return dcc.Tab(
        label="Predicción",
        value="tab-prediccion-publica",
        className="fw-bold",
        children=[tab_content],
    )


# ── Callback ───────────────────────────────────────────────────────────────────


@callback(
    Output("pred-publica-content", "children"),
    Input("tabs-panel", "value"),
    Input("loc-loaded", "data"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def actualizar_prediccion_publica(tab, locs, session_id):
    if tab != "tab-prediccion-publica":
        return no_update
    if not locs:
        return _empty_state()

    falso_hoy = datetime.today().strftime("%Y-%m-%d")
    secciones = []

    locs_list = [locs] if isinstance(locs, str) else (locs or [])
    for loc_uuid in locs_list:
        df_e = get_df_enriquecido(loc_uuid, session_id=session_id or "")
        if df_e.empty:
            continue
        loc_nombre = mapa_tiendas.get(loc_uuid, loc_uuid)
        zonas = [z for z in get_zones_for_loc(loc_uuid) if not z.get("oculta")]

        zonas_ordenadas = _ordenar_zonas_fuera_dentro(zonas)
        zona_cols = []
        for idx, z in enumerate(zonas_ordenadas):
            res = ejecutar_auditoria_predictiva(df_e, loc_uuid, z["zona_id"], falso_hoy, 7)
            if res.get("status") != "success":
                zona_cols.append(_zona_card_insuficiente(z["nombre"], _color_zona(idx)))
                continue
            zona_cols.append(_zona_card(z["nombre"], res, _color_zona(idx)))

        if zona_cols:
            secciones.append(_loc_section(loc_nombre, zona_cols))

    if not secciones:
        return _empty_state(
            "No se pudieron calcular previsiones. Asegúrate de que los datos estén sincronizados."
        )

    return html.Div(
        [
            # Nota metodológica discreta
            html.Div(
                [
                    html.Span(
                        "Las previsiones se basan en el histórico disponible y factores como climatología, "
                        "festivos y patrones de comportamiento. Son orientativas.",
                        className="text-muted",
                        style={"fontSize": "0.72rem"},
                    ),
                ],
                className="mb-4 p-3 rounded-3",
                style={"background": "#f8f9fa"},
            ),
            html.Div(secciones),
        ]
    )
