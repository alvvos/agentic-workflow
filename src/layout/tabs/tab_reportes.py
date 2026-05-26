from dash import html, dcc
import dash_bootstrap_components as dbc


def _seccion_informe(num, titulo, desc, color_num, nota=None):
    return html.Div([
        html.Div([
            html.Span(num, className=f"badge rounded-pill {color_num.replace('text-','bg-')} me-2 fw-bold",
                      style={"minWidth": "1.6rem", "fontSize": "0.7rem"}),
            html.Span(titulo, className="fw-bold text-dark small"),
        ], className="d-flex align-items-center mb-1"),
        html.P(desc, className="small text-muted mb-0 ms-4"),
        html.P([html.I(className="fas fa-info-circle me-1"), nota],
               className="small text-warning ms-4 mb-0") if nota else None,
    ], className="mb-3")


def build_tab_reportes():
    return dcc.Tab(label='Generador de reportes', value='tab-reportes', className="fw-bold", children=[
        html.Br(),
        dbc.Row([
            dbc.Col([
                html.H4([
                    html.I(className="fas fa-file-code me-2 text-primary"),
                    "Informe HTML"
                ], className="fw-bold mb-1 text-dark"),
                html.P(
                    "Genera un archivo .html con todos los gráficos interactivos y bloques de texto editables. "
                    "Ábrelo en el navegador para editar, y usa Ctrl+P para guardar como PDF.",
                    className="text-muted small mb-3"
                ),

                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="fas fa-sliders-h me-2 text-primary"),
                        html.Span("Filtros activos", className="fw-bold small text-uppercase")
                    ], className="bg-white border-bottom py-2"),
                    dbc.CardBody(
                        html.Div(id="export-resumen-filtros",
                                 children=html.Span("Cargando filtros...", className="text-muted small")),
                        className="py-2 px-3"
                    )
                ], className="border-0 shadow-sm rounded-4 mb-3"),

                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="fas fa-list-ol me-2 text-primary"),
                        html.Span("Estructura del informe", className="fw-bold small text-uppercase")
                    ], className="bg-white border-bottom py-2"),
                    dbc.CardBody(
                        html.Ul([
                            html.Li([html.Strong("Portada"), " — Organización, periodo y ubicaciones"]),
                            html.Li([html.Strong("1. Visión Global"), " — KPIs consolidados, tabla por zona, tendencia mensual"]),
                            html.Li([html.Strong("2. Mes a mes"), " — KPIs, intensidad horaria, calendario de actividad y ratio de atracción por mes"]),
                            html.Li([html.Strong("3. Conclusiones"), " — Síntesis editable"]),
                        ], className="small text-muted ps-3 mb-0")
                    , className="py-2 px-3")
                ], className="border-0 shadow-sm rounded-4"),

            ], xs=12, lg=7, className="mb-4 mb-lg-0"),

            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-file-code",
                                   style={"fontSize": "3.5rem", "color": "#0052CC"}),
                        ], className="text-center mb-3 mt-2"),
                        html.H5("Informe HTML Interactivo",
                                className="fw-bold text-center text-dark mb-1"),
                        html.P("Gráficos interactivos · Texto editable · Imprimible",
                               className="text-muted text-center small mb-4"),
                        dbc.Button([
                            html.I(className="fas fa-code me-2"),
                            "Descargar HTML"
                        ], id="btn-generar-html", color="primary", outline=True,
                           className="w-100 fw-bold rounded-pill shadow-sm mb-2",
                           size="lg"),
                        dbc.Button([
                            html.I(className="fas fa-file-pdf me-2"),
                            "Descargar PDF"
                        ], id="btn-generar-pdf", color="primary",
                           className="w-100 fw-bold rounded-pill shadow-sm mb-2",
                           size="lg"),
                        html.Div(id="error-msg-html",
                                 className="text-danger fw-bold text-center small"),
                        html.Hr(className="my-3"),
                        html.P([
                            html.I(className="fas fa-pencil-alt me-2 text-muted"),
                            "Pasa el cursor por cualquier texto del informe para editarlo."
                        ], className="small text-muted text-center mb-0"),
                    ], className="p-4")
                ], className="border-0 shadow-sm rounded-4 bg-light sticky-top",
                   style={"top": "20px"}),
            ], xs=12, lg=5),

        ], className="align-items-start"),
        dcc.Download(id="download-html-report"),
        dcc.Download(id="download-pdf-report")
    ])
