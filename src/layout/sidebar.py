from datetime import datetime
from dash import html, dcc
import dash_bootstrap_components as dbc
from src.core.data_master import opciones_orgs


def build_sidebar():
    return html.Div([
        html.Div(
            html.Img(src="/assets/logo.png", style={"maxWidth": "100%", "maxHeight": "70px", "objectFit": "contain"}),
            className="text-center mb-3 px-2"
        ),
        dbc.Card([
            dbc.CardBody([
                html.H5([html.I(className="fas fa-sliders-h me-2 text-primary"), "Filtros Globales"], className="fw-bold mb-4 text-dark"),

                html.Label("Organización", className="fw-bold text-muted small text-uppercase mb-1"),
                dcc.Dropdown(id="drop-org", options=opciones_orgs, value=None, placeholder="Selecciona una organización...", className="mb-3 shadow-sm"),

                html.Label("Ubicaciones", className="fw-bold text-muted small text-uppercase mb-1 mt-2"),
                dcc.Dropdown(id="drop-locs", multi=True, className="mb-4 shadow-sm"),

                html.Div(id="sidebar-periodo-wrapper", children=[
                    html.Hr(className="text-muted"),
                    html.Label("Período a visualizar", className="fw-bold text-muted small text-uppercase mb-3 mt-3"),
                    dbc.RadioItems(
                        id="tipo-fecha",
                        options=[
                            {"label": "Ayer", "value": "ayer"},
                            {"label": "Últimos 7 días", "value": "7d_rel"},
                            {"label": "Últimos 28 días", "value": "28d_rel"},
                            {"label": "Día concreto", "value": "dia"},
                            {"label": "Rango temporal", "value": "rango"}
                        ],
                        value="7d_rel",
                        className="mb-3"
                    ),
                    html.Div(
                        dcc.DatePickerRange(
                            id='date-rango', start_date=datetime(2025, 9, 1).date(), end_date=datetime.today().date(),
                            display_format='YYYY-MM-DD', className="w-100 shadow-sm"
                        ), id="contenedor-rango", style={"display": "none"}
                    ),
                    html.Div(
                        dcc.DatePickerSingle(
                            id='date-dia', date=datetime.today().date(), display_format='YYYY-MM-DD',
                            className="w-100 shadow-sm"
                        ), id="contenedor-dia", style={"display": "none"}
                    ),
                ]),

                # ── Panel PM — visible only on tab-ejecutivo ──────────────
                html.Div(id="pm-options-wrapper", style={"display": "none"}, children=[
                    html.Hr(className="text-muted"),
                    html.Label("Ventana de análisis",
                               className="fw-bold text-muted small text-uppercase mb-2 mt-2"),
                    dbc.RadioItems(
                        id="pm-ventana",
                        options=[
                            {"label": "Semana (7 días)", "value": "semana"},
                            {"label": "Mes (28 días)",   "value": "mes"},
                        ],
                        value="semana",
                        className="mb-1",
                    ),
                    html.Small(
                        "Mes compara los últimos 28 días vs el mes anterior.",
                        className="text-muted d-block mb-2",
                        style={"fontSize": "0.68rem", "lineHeight": "1.4"},
                    ),
                ]),

                # ── BI comparativa — visible only on tab-auditoria ────────
                html.Div(id="bi-comparativa-wrapper", style={"display": "none"}, children=[
                    html.Hr(className="text-muted"),
                    html.Label("Comparativa temporal",
                               className="fw-bold text-muted small text-uppercase mb-2 mt-2"),
                    dbc.RadioItems(
                        id="bi-comparativa",
                        options=[
                            {"label": "Ninguna",               "value": "none"},
                            {"label": "vs. Semana Ant. (WoW)", "value": "wow"},
                            {"label": "vs. Mes Ant. (MoM)",    "value": "mom"},
                            {"label": "vs. Año Ant. (YoY)",    "value": "yoy"},
                        ],
                        value="none",
                        className="mb-2",
                    ),
                ]),

            ])
        ], className="border-0 shadow-sm rounded-4")
    ], className="sticky-top", style={"top": "30px", "zIndex": 1020})
