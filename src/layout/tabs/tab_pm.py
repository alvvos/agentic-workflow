import dash_bootstrap_components as dbc
from dash import dcc, html

_SPINNER = [
    dbc.Spinner(color="primary", size="lg"),
    html.H5("Renderizando...", className="ms-3 mb-0 text-primary fw-bold"),
]

_OVERLAY_STYLE = {
    "display": "none",
    "position": "absolute",
    "top": 0,
    "left": 0,
    "right": 0,
    "bottom": 0,
    "minHeight": "60vh",
    "background": "rgba(255,255,255,0.92)",
    "zIndex": 100,
    "alignItems": "center",
    "justifyContent": "center",
    "flexDirection": "column",
}


def build_tab_pm():
    return dcc.Tab(
        label="Estado",
        value="tab-ejecutivo",
        className="fw-bold h-min-screen",
        children=[
            html.Br(),
            html.Div(
                style={"position": "relative"},
                children=[
                    dcc.Loading(
                        html.Div(id="panel-ejecutivo-content", style={"minHeight": "60vh"}),
                        custom_spinner=html.Div(
                            [
                                dbc.Spinner(color="primary", size="lg"),
                                html.H5(
                                    "Analizando...", className="ms-3 mb-0 text-primary fw-bold"
                                ),
                            ],
                            className="d-flex align-items-center justify-content-center",
                            style={"minHeight": "60vh"},
                        ),
                        delay_show=350,
                        delay_hide=0,
                    ),
                    html.Div(id="pm-render-overlay", style=_OVERLAY_STYLE, children=_SPINNER),
                ],
            ),
        ],
    )
