from datetime import datetime, timedelta

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
_CFG = {"displayModeBar": False, "staticPlot": False}


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


def _acc_color(acc) -> str:
    if acc in ("N/A", None):
        return _C_MUTED
    try:
        v = float(str(acc).replace("%", ""))
        if v >= 85:
            return "#27ae60"
        if v >= 70:
            return "#e67e22"
        return "#e74c3c"
    except Exception:
        return _C_MUTED


def _unified_chart(res_bt: dict, res_fw: dict, color: str) -> go.Figure:
    g_bt = res_bt["grafica"]
    g_fw = res_fw["grafica"]

    bt_x, bt_real, bt_pred = [], [], []
    for i, f in enumerate(g_bt["fechas"]):
        r = g_bt["reales"][i] if i < len(g_bt["reales"]) else None
        if r is not None:
            bt_x.append(f)
            bt_real.append(float(r))
            bt_pred.append(float(g_bt["predichos"][i]) if i < len(g_bt["predichos"]) else None)

    # Mostrar solo los últimos 7 días del backtest → proporción 50/50 con los 7 días de previsión
    if len(bt_x) > 7:
        bt_x = bt_x[-7:]
        bt_real = bt_real[-7:]
        bt_pred = bt_pred[-7:]

    fw_x = g_fw["fechas"]
    fw_pred = [max(0, int(round(v))) for v in g_fw["predichos"]]
    fw_lower = g_fw.get("lower") or []
    fw_upper = g_fw.get("upper") or []

    all_x = bt_x + fw_x
    all_dates = [pd.to_datetime(x) for x in all_x]
    # Con 14 fechas totales (7 bt + 7 fw) mostramos todas
    tickvals = all_x
    ticktext = [f"{_DIAS_ES[d.dayofweek]}<br>{d.strftime('%d')}" for d in all_dates]

    today_str = fw_x[0] if fw_x else None

    all_vals = [v for v in bt_real + fw_pred + (fw_upper or []) if v is not None]
    y_max = max(all_vals) if all_vals else 1
    y_ceil = y_max * 1.45

    fig = go.Figure()

    if fw_lower and fw_upper:
        fig.add_trace(
            go.Scatter(
                x=fw_x,
                y=fw_lower,
                mode="lines",
                line=dict(width=0),
                name="IC mín",
                showlegend=False,
                hovertemplate="%{y:,}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=fw_x,
                y=fw_upper,
                mode="lines",
                fill="tonexty",
                fillcolor=_rgba(color, 0.13),
                line=dict(width=0),
                name="IC máx",
                showlegend=False,
                hovertemplate="%{y:,}<extra></extra>",
            )
        )

    fig.add_trace(
        go.Scatter(
            x=bt_x,
            y=bt_real,
            mode="lines+markers+text",
            line=dict(color="#b2bec3", width=2),
            marker=dict(size=4, color="#b2bec3"),
            text=[f"{int(v):,}" for v in bt_real],
            textposition="top center",
            textfont=dict(size=7, color="#95a5a6"),
            name="Real",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=bt_x,
            y=bt_pred,
            mode="lines",
            line=dict(color=color, width=1.5, dash="dash"),
            name="Modelo",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=fw_x,
            y=fw_pred,
            mode="lines+markers+text",
            line=dict(color=color, width=3),
            marker=dict(size=7, color="white", symbol="circle", line=dict(color=color, width=2.5)),
            text=[f"{v:,}" for v in fw_pred],
            textposition="top center",
            textfont=dict(size=9, color=_C_DARK, family="monospace"),
            name="Previsión",
            showlegend=False,
            hovertemplate="%{y:,}<extra></extra>",
        )
    )

    shapes = []
    annotations = []
    if today_str:
        if fw_x:
            shapes.append(
                dict(
                    type="rect",
                    xref="x",
                    yref="paper",
                    x0=today_str,
                    x1=fw_x[-1],
                    y0=0,
                    y1=1,
                    fillcolor=_rgba(color, 0.04),
                    line=dict(width=0),
                    layer="below",
                )
            )
        shapes.append(
            dict(
                type="line",
                x0=today_str,
                x1=today_str,
                y0=0,
                y1=1,
                yref="paper",
                line=dict(color="#636e72", width=1.5, dash="dot"),
            )
        )
        annotations.append(
            dict(
                x=today_str,
                y=1.0,
                yref="paper",
                text="hoy",
                showarrow=False,
                font=dict(size=7, color="#636e72"),
                xanchor="left",
                yanchor="bottom",
                xshift=3,
            )
        )

    fig.update_layout(
        height=300,
        margin=dict(t=36, b=24, l=4, r=4),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            type="date",
            tickvals=tickvals,
            ticktext=ticktext,
            tickfont=dict(size=8, color=_C_DARK),
            fixedrange=True,
            showgrid=False,
            showline=False,
            zeroline=False,
        ),
        yaxis=dict(visible=False, fixedrange=True, showgrid=False, range=[0, y_ceil]),
        hovermode="x unified",
        showlegend=True,
        legend=dict(
            font=dict(size=8),
            orientation="h",
            yanchor="top",
            y=1.06,
            xanchor="right",
            x=1.0,
            bgcolor="rgba(0,0,0,0)",
        ),
        shapes=shapes,
        annotations=annotations,
    )
    return fig


def _zona_card(nombre: str, res: dict, color: str, res_bt=None) -> dbc.Col:
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

    has_bt = res_bt is not None and res_bt.get("status") == "success"

    if has_bt:
        m_bt = res_bt["metricas"]
        acc_bt = m_bt.get("accuracy")
        mae_bt = m_bt.get("mae")
        wmape_bt = m_bt.get("wmape_pct")

        acc_display = f"{float(acc_bt):.1f}%" if acc_bt not in ("N/A", None) else "—"
        mae_display = f"{int(round(float(mae_bt))):,}" if mae_bt not in ("N/A", None) else "—"
        wmape_display = f"{float(wmape_bt):.1f}%" if wmape_bt not in ("N/A", None) else "—"
        kpi_color = _acc_color(acc_bt)

        metrics_row = html.Div(
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Div(
                                acc_display,
                                className="fw-bold lh-1",
                                style={"fontSize": "1.35rem", "color": kpi_color},
                            ),
                            html.Div(
                                "Precisión",
                                style={
                                    "fontSize": "0.65rem",
                                    "color": _C_MUTED,
                                    "marginTop": "2px",
                                },
                            ),
                        ],
                        className="text-center",
                    ),
                    dbc.Col(
                        [
                            html.Div(
                                mae_display,
                                className="fw-bold text-dark lh-1",
                                style={"fontSize": "1.35rem"},
                            ),
                            html.Div(
                                "MAE · visitas",
                                style={
                                    "fontSize": "0.65rem",
                                    "color": _C_MUTED,
                                    "marginTop": "2px",
                                },
                            ),
                        ],
                        className="text-center",
                    ),
                    dbc.Col(
                        [
                            html.Div(
                                wmape_display,
                                className="fw-bold text-dark lh-1",
                                style={"fontSize": "1.35rem"},
                            ),
                            html.Div(
                                "Error relativo",
                                style={
                                    "fontSize": "0.65rem",
                                    "color": _C_MUTED,
                                    "marginTop": "2px",
                                },
                            ),
                        ],
                        className="text-center",
                    ),
                ],
                className="g-0",
            ),
            className="py-2 px-3 mb-3 rounded-3",
            style={"background": "#f8f9fa"},
        )
        chart_el = dcc.Graph(
            figure=_unified_chart(res_bt, res, color),
            config=_CFG,
            style={"height": "300px", "margin": "0 -4px"},
        )
    else:
        metrics_row = html.Span()
        chart_el = dcc.Graph(figure=fig, config=_CFG, style={"height": "200px", "marginX": "-4px"})

    manana_el = html.Div(
        [
            html.Span(
                f"{dia_lbl} {fecha_lbl} · {primera_val:,} vis",
                className="fw-semibold text-dark",
                style={"fontSize": "0.80rem"},
            ),
            *(
                [
                    html.Span(
                        f"  IC90% {lowers[0]:,}–{uppers[0]:,}",
                        style={"fontSize": "0.70rem", "color": _C_PRIMARY, "marginLeft": "6px"},
                        title=(
                            "Intervalo de confianza conformal al 90 %.\n"
                            "El modelo estima que el número real de visitas caerá\n"
                            "dentro de este rango en 9 de cada 10 días."
                        ),
                    )
                ]
                if lowers and uppers
                else []
            ),
            html.Div(tendencia_el, style={"marginTop": "2px"}),
        ],
        style={"marginTop": "10px"},
    )

    return dbc.Card(
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
                metrics_row,
                chart_el,
                manana_el,
            ],
            className="p-3",
        ),
        className="border-0 shadow-sm rounded-4 bg-white",
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


def _zona_card_insuficiente(nombre: str, color: str) -> dbc.Card:
    return dbc.Card(
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
                html.Span(
                    "Datos insuficientes para generar previsión.",
                    className="text-muted small",
                ),
                html.P(
                    "Se necesitan al menos 30 días de historial.",
                    className="text-muted",
                    style={"fontSize": "0.72rem"},
                ),
            ],
            className="p-3",
        ),
        className="border-0 shadow-sm rounded-4 bg-white",
        style={"borderLeft": f"3px solid {color}"},
    )


def _build_zone_tree(zonas: list[dict]) -> tuple[list, dict]:
    children_map: dict[str, list] = {z["zona_id"]: [] for z in zonas}
    roots: list = []
    for z in zonas:
        pid = z.get("parent_zona_id")
        if pid and pid in children_map:
            children_map[pid].append(z)
        else:
            roots.append(z)
    for zid in children_map:
        children_map[zid].sort(key=lambda z: z.get("nombre", ""))
    return roots, children_map


def _assign_colors(roots: list, children_map: dict) -> dict:
    color_map: dict = {}
    counter = [0]

    def dfs(zones):
        for z in zones:
            color_map[z["zona_id"]] = _color_zona(counter[0])
            counter[0] += 1
            dfs(children_map.get(z["zona_id"], []))

    dfs(roots)
    return color_map


def _render_zona_node(
    zone: dict, color: str, zona_results: dict, children_map: dict, color_map: dict
) -> html.Div:
    zid = zone["zona_id"]
    res, res_bt = zona_results.get(zid, (None, None))
    card = (
        _zona_card_insuficiente(zone["nombre"], color)
        if res is None
        else _zona_card(zone["nombre"], res, color, res_bt)
    )
    children = children_map.get(zid, [])
    if not children:
        return html.Div(card, className="mb-3")
    child_nodes = [
        _render_zona_node(c, color_map[c["zona_id"]], zona_results, children_map, color_map)
        for c in children
    ]
    return html.Div(
        [
            html.Div(card, className="mb-2"),
            html.Div(
                child_nodes,
                className="ps-4 ms-2",
                style={"borderLeft": f"3px solid {color}"},
            ),
        ],
        className="mb-3",
    )


def _loc_section(loc_nombre: str, tree_nodes: list) -> html.Div:
    return html.Div(
        [
            html.Div(
                html.Span(loc_nombre, className="fw-bold text-dark", style={"fontSize": "1rem"}),
                className="d-flex align-items-center mb-3",
            ),
            html.Div(tree_nodes),
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
                                    "Próximos 7 días · validación retrospectiva incluida.",
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

        falso_hoy_bt = (datetime.today() - timedelta(days=14)).strftime("%Y-%m-%d")
        roots, children_map = _build_zone_tree(zonas)
        color_map = _assign_colors(roots, children_map)

        zona_results: dict = {}
        for z in zonas:
            zid = z["zona_id"]
            res = ejecutar_auditoria_predictiva(df_e, loc_uuid, zid, falso_hoy, 7)
            if res.get("status") != "success":
                zona_results[zid] = (None, None)
            else:
                res_bt = ejecutar_auditoria_predictiva(df_e, loc_uuid, zid, falso_hoy_bt, 14)
                zona_results[zid] = (res, res_bt)

        tree_nodes = [
            _render_zona_node(
                root, color_map[root["zona_id"]], zona_results, children_map, color_map
            )
            for root in roots
        ]
        if tree_nodes:
            secciones.append(_loc_section(loc_nombre, tree_nodes))

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
