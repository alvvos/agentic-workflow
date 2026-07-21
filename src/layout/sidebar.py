from datetime import datetime, timedelta

import dash_bootstrap_components as dbc
from dash import dcc, html

from src.core.data_master import opciones_orgs

_LABEL_STYLE = {
    "fontSize": "0.68rem",
    "fontWeight": "700",
    "letterSpacing": "0.6px",
    "color": "#8492a6",
    "textTransform": "uppercase",
    "marginBottom": "6px",
    "display": "flex",
    "alignItems": "center",
    "gap": "6px",
}

_SECTION_DIVIDER_STYLE = {
    "borderTop": "1px solid #edf0f5",
    "margin": "16px 0 14px",
}


def _section_label(icon_cls, text):
    return html.Div(
        [html.I(className=f"{icon_cls} text-primary"), html.Span(text)],
        style=_LABEL_STYLE,
    )


def build_sidebar(org_options=None):
    if org_options is None:
        org_options = list(opciones_orgs)
    return html.Div(
        [
            html.Div(
                html.Img(
                    src="/assets/logo.png",
                    style={"maxWidth": "100%", "maxHeight": "56px", "objectFit": "contain"},
                ),
                className="text-center mb-3 px-2",
            ),
            dbc.Card(
                dbc.CardBody(
                    [
                        # ── Encabezado ──────────────────────────────────────
                        html.Div(
                            [
                                html.Div(
                                    style={
                                        "width": "3px",
                                        "height": "18px",
                                        "backgroundColor": "#0052CC",
                                        "borderRadius": "2px",
                                        "flexShrink": 0,
                                    }
                                ),
                                html.Span(
                                    "Filtros",
                                    style={
                                        "fontSize": "0.78rem",
                                        "fontWeight": "700",
                                        "letterSpacing": "0.8px",
                                        "textTransform": "uppercase",
                                        "color": "#2c3e50",
                                    },
                                ),
                            ],
                            className="d-flex align-items-center gap-2 mb-4",
                        ),
                        # ── Organización ─────────────────────────────────────
                        _section_label("fas fa-building", "Organización"),
                        dcc.Dropdown(
                            id="drop-org",
                            options=org_options,
                            value=None,
                            placeholder="Selecciona…",
                            className="mb-3",
                        ),
                        # ── Ubicaciones ──────────────────────────────────────
                        _section_label("fas fa-map-marker-alt", "Ubicaciones"),
                        dcc.Dropdown(id="drop-locs", className="mb-2"),
                        # ── Período ───────────────────────────────────────────
                        html.Div(
                            id="sidebar-periodo-wrapper",
                            children=[
                                html.Div(style=_SECTION_DIVIDER_STYLE),
                                _section_label("fas fa-calendar-alt", "Período"),
                                dbc.RadioItems(
                                    id="tipo-fecha",
                                    options=[
                                        {"label": "Ayer", "value": "ayer"},
                                        {"label": "Últimos 7 días", "value": "7d_rel"},
                                        {"label": "Últimos 28 días", "value": "28d_rel"},
                                        {"label": "Día concreto", "value": "dia"},
                                        {"label": "Rango temporal", "value": "rango"},
                                    ],
                                    value="7d_rel",
                                    className="mb-3",
                                    style={"fontSize": "0.87rem"},
                                ),
                                html.Div(
                                    dcc.DatePickerRange(
                                        id="date-rango",
                                        start_date=(datetime.today() - timedelta(days=90)).date(),
                                        end_date=datetime.today().date(),
                                        display_format="YYYY-MM-DD",
                                        className="w-100",
                                    ),
                                    id="contenedor-rango",
                                    style={"display": "none"},
                                ),
                                html.Div(
                                    dcc.DatePickerSingle(
                                        id="date-dia",
                                        date=datetime.today().date(),
                                        display_format="YYYY-MM-DD",
                                        className="w-100",
                                    ),
                                    id="contenedor-dia",
                                    style={"display": "none"},
                                ),
                            ],
                        ),
                        # ── Ventana PM (visible solo en tab PM) ───────────────
                        html.Div(
                            id="pm-options-wrapper",
                            style={"display": "none"},
                            children=[
                                html.Div(style=_SECTION_DIVIDER_STYLE),
                                _section_label("fas fa-chart-bar", "Ventana"),
                                dbc.RadioItems(
                                    id="pm-ventana",
                                    options=[
                                        {"label": "Últimos 7 días", "value": "semana"},
                                        {"label": "Últimos 28 días", "value": "mes"},
                                    ],
                                    value="semana",
                                    className="mb-1",
                                    style={"fontSize": "0.87rem"},
                                ),
                                html.Small(
                                    "Compara los días del período vs. los mismos días previos.",
                                    className="text-muted d-block mb-2",
                                    style={"fontSize": "0.68rem", "lineHeight": "1.4"},
                                ),
                            ],
                        ),
                        # ── Comparativa BI (visible solo en tab BI) ───────────
                        html.Div(
                            id="bi-comparativa-wrapper",
                            style={"display": "none"},
                            children=[
                                html.Div(style=_SECTION_DIVIDER_STYLE),
                                _section_label("fas fa-exchange-alt", "Comparativa"),
                                dbc.RadioItems(
                                    id="bi-comparativa",
                                    options=[
                                        {"label": "Ninguna", "value": "none"},
                                        {"label": "vs. Semana Ant. (WoW)", "value": "wow"},
                                        {"label": "vs. Mes Ant. (MoM)", "value": "mom"},
                                        {"label": "vs. Año Ant. (YoY)", "value": "yoy"},
                                    ],
                                    value="none",
                                    className="mb-2",
                                    style={"fontSize": "0.87rem"},
                                ),
                            ],
                        ),
                    ],
                    style={"padding": "20px 18px"},
                ),
                className="border-0 shadow-sm sidebar-accent-card",
            ),
        ],
        className="sticky-top",
        style={"top": "30px", "zIndex": 1020},
    )
