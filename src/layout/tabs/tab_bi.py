from dash import html, dcc
import dash_bootstrap_components as dbc


def build_tab_bi():
    return dcc.Tab(label='Panel BI', value='tab-auditoria', className="fw-bold", children=[
        html.Br(),

        html.Div(id="bi-status-visor", className="mb-4 p-3 bg-light rounded-4 border-start border-primary border-4 shadow-sm"),

        dbc.Row([
            dbc.Col([
                html.Label([html.I(className="fas fa-filter me-2 text-primary"), "Zonas activas:"], className="fw-bold mb-3 text-secondary"),
                dbc.Checklist(
                    id="radar-drop-zonas", options=[], value=[], inline=True,
                    input_class_name="btn-check", label_class_name="btn btn-outline-primary mb-2 me-2 fw-bold shadow-sm rounded-pill"
                )
            ], width=12)
        ], className="mb-4"),

        dbc.Row([
            dbc.Col([
                html.Label([html.I(className="fas fa-balance-scale me-2 text-primary"), "Comparativa temporal:"], className="fw-bold mb-2 mt-2 text-secondary"),
                dbc.RadioItems(
                    id="bi-comparativa",
                    options=[
                        {"label": "Ninguna", "value": "none"},
                        {"label": "vs. Semana Ant. (WoW)", "value": "wow"},
                        {"label": "vs. Mes Ant. (MoM)", "value": "mom"},
                        {"label": "vs. Año Ant. (YoY)", "value": "yoy"}
                    ],
                    value="none", inline=True, className="mb-2"
                )
            ], xs=12, lg=7),
            dbc.Col([
                dbc.Button([html.I(className="fas fa-file-archive me-2"), "Descargar todos (.png)"], id="btn-download-all-bi", color="secondary", outline=True, className="mt-lg-4 mt-2 w-100 rounded-pill fw-bold shadow-sm"),
                dcc.Download(id="download-bi-zip"),
            ], xs=12, lg=5)
        ], className="align-items-center mb-4"),

        dcc.Loading(
            html.Div(id="bi-dynamic-content",
                     style={"minHeight": "420px"}),
            custom_spinner=html.Div(
                [
                    dbc.Spinner(color="primary", size="lg"),
                    html.H5("Cargando análisis...", className="ms-3 mb-0 text-primary fw-bold"),
                ],
                className="d-flex align-items-center justify-content-center loading-spinner-body",
            ),
            delay_show=350,
            delay_hide=80,
        ),
        html.Hr(className="text-muted my-5"),
        dbc.Row([
            dbc.Col(
                dbc.Button([html.I(className="fas fa-file-excel me-2"), "Descargar Excel"], id="btn-dl-auditoria", color="success", outline=True, className="rounded-pill fw-bold shadow-sm"),
                xs=12, className="text-end mb-3"
            )
        ]),
        dcc.Download(id="download-auditoria"),
        html.Div(id="audit-results")
    ])
