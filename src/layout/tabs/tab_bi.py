import dash_bootstrap_components as dbc
from dash import dcc, html

from src.layout.components.loaders import loading_section


def build_tab_bi():
    return dcc.Tab(
        label="Analítica",
        value="tab-auditoria",
        className="fw-bold",
        children=[
            html.Br(),
            dcc.Store(id="zonas-activas-combined"),
            html.Div(id="bi-status-visor", className="mb-4"),
            html.Div(
                [
                    dbc.Checklist(
                        id="radar-drop-zonas",
                        options=[],
                        value=[],
                        style={"display": "none"},
                    ),
                    html.Div(id="radar-child-zones-wrapper", style={"display": "none"}),
                ],
                style={"display": "none"},
            ),
            loading_section(
                html.Div(id="bi-dynamic-content", style={"minHeight": "420px"}),
                label="Cargando análisis...",
                overlay_id="bi-render-overlay",
                min_height="420px",
            ),
            html.Hr(className="text-muted my-5"),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Button(
                            "Descargar Excel",
                            id="btn-dl-auditoria",
                            color="success",
                            outline=True,
                            className="rounded-3 fw-bold shadow-sm",
                        ),
                        xs=12,
                        className="text-end mb-3",
                    )
                ]
            ),
            dcc.Download(id="download-auditoria"),
            html.Div(id="audit-results"),
        ],
    )
