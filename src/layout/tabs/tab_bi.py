from dash import html, dcc
import dash_bootstrap_components as dbc

_SPINNER = [
    dbc.Spinner(color="primary", size="lg"),
    html.H5("Renderizando...", className="ms-3 mb-0 text-primary fw-bold"),
]

_OVERLAY_STYLE = {
    "display": "none",
    "position": "absolute",
    "top": 0, "left": 0, "right": 0, "bottom": 0,
    "minHeight": "420px",
    "background": "rgba(255,255,255,0.92)",
    "zIndex": 100,
    "alignItems": "center",
    "justifyContent": "center",
    "flexDirection": "column",
}

def build_tab_bi():
    return dcc.Tab(label='Analítica', value='tab-auditoria', className="fw-bold", children=[
        html.Br(),

        dcc.Store(id="zonas-activas-combined"),

        html.Div(id="bi-status-visor", className="mb-4 p-3 bg-light rounded-4 border-start border-primary border-4 shadow-sm"),

        dbc.Row([
            dbc.Col([
                html.Label([html.I(className="fas fa-filter me-2 text-primary"), "Zonas activas:"], className="fw-bold mb-3 text-secondary"),
                dbc.Checklist(
                    id="radar-drop-zonas", options=[], value=[], inline=True,
                    input_class_name="btn-check", label_class_name="btn btn-outline-primary mb-2 me-2 fw-bold shadow-sm rounded-3"
                ),
                html.Div(id="radar-child-zones-wrapper"),
            ], width=12)
        ], className="mb-4"),

        dbc.Row([
            dbc.Col([
                dbc.Button([html.I(className="fas fa-file-archive me-2"), "Descargar todos (.png)"], id="btn-download-all-bi", color="secondary", outline=True, className="mt-2 w-100 rounded-3 fw-bold shadow-sm"),
                dcc.Download(id="download-bi-zip"),
            ], xs=12, className="text-end mb-4")
        ]),

        html.Div(style={"position": "relative"}, children=[
            dcc.Loading(
                html.Div(id="bi-dynamic-content", style={"minHeight": "420px"}),
                custom_spinner=html.Div(
                    [
                        dbc.Spinner(color="primary", size="lg"),
                        html.H5("Cargando análisis...", className="ms-3 mb-0 text-primary fw-bold"),
                    ],
                    className="d-flex align-items-center justify-content-center loading-spinner-body",
                ),
                delay_show=350,
                delay_hide=0,
            ),
            html.Div(id="bi-render-overlay", style=_OVERLAY_STYLE, children=_SPINNER),
        ]),

        html.Hr(className="text-muted my-5"),
        dbc.Row([
            dbc.Col(
                dbc.Button([html.I(className="fas fa-file-excel me-2"), "Descargar Excel"], id="btn-dl-auditoria", color="success", outline=True, className="rounded-3 fw-bold shadow-sm"),
                xs=12, className="text-end mb-3"
            )
        ]),
        dcc.Download(id="download-auditoria"),
        html.Div(id="audit-results")
    ])
