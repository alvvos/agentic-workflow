from dash import html, dcc
import dash_bootstrap_components as dbc


def build_tab_pm():
    return dcc.Tab(label='Panel PM', value='tab-ejecutivo', className="fw-bold h-min-screen", children=[
        html.Br(),
        dbc.Row([
            dbc.Col([
                html.Label([html.I(className="fas fa-filter me-2 text-primary"), "Zonas analíticas (Last Zones):"], className="fw-bold mb-3 text-secondary"),
                dbc.Checklist(
                    id="ejecutivo-drop-zonas", options=[], value=[], inline=True,
                    input_class_name="btn-check", label_class_name="btn btn-outline-primary mb-2 me-2 fw-bold shadow-sm rounded-pill"
                )
            ], xs=12, md=9),

            dbc.Col([], xs=12, md=3)

        ], className="mb-4 align-items-center"),

        dcc.Loading(
            html.Div(id="panel-ejecutivo-content",
                     style={"minHeight": "420px"}),
            custom_spinner=html.Div(
                [
                    dbc.Spinner(color="primary", size="lg"),
                    html.H5("Analizando...", className="ms-3 mb-0 text-primary fw-bold"),
                ],
                className="d-flex align-items-center justify-content-center loading-spinner-body",
            ),
            delay_show=350,
            delay_hide=80,
        )
    ])
