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
                    html.Div(
                        html.Span(
                            "ZONAS ACTIVAS",
                            className="text-uppercase fw-semibold",
                            style={
                                "fontSize": "0.65rem",
                                "letterSpacing": "1.4px",
                                "color": "#6c757d",
                            },
                        ),
                        className="mb-3",
                    ),
                    dbc.Checklist(
                        id="radar-drop-zonas",
                        options=[],
                        value=[],
                        inline=False,
                        input_class_name="form-check-input",
                        label_class_name="form-check-label ms-2",
                    ),
                    html.Div(id="radar-child-zones-wrapper", className="mt-1"),
                ],
                className="mb-4 px-3 py-3 rounded-4",
                style={
                    "background": "rgba(0,0,0,0.02)",
                    "border": "1px solid rgba(0,0,0,0.07)",
                },
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
