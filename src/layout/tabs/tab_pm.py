from dash import html, dcc
import dash_bootstrap_components as dbc

def build_tab_pm():
    return dcc.Tab(label='Estado', value='tab-ejecutivo', className="fw-bold h-min-screen", children=[
        html.Br(),
        dcc.Loading(
            html.Div(id="panel-ejecutivo-content", style={"minHeight": "60vh"}),
            custom_spinner=html.Div(
                [
                    dbc.Spinner(color="primary", size="lg"),
                    html.H5("Analizando...", className="ms-3 mb-0 text-primary fw-bold"),
                ],
                className="d-flex align-items-center justify-content-center",
                style={"minHeight": "60vh"},
            ),
            delay_show=350,
            delay_hide=500,
        ),
    ])
