from dash import dcc, html

from src.layout.components.loaders import loading_section


def build_tab_pm():
    return dcc.Tab(
        label="Estado",
        value="tab-ejecutivo",
        className="fw-bold h-min-screen",
        children=[
            html.Br(),
            loading_section(
                html.Div(id="panel-ejecutivo-content", style={"minHeight": "60vh"}),
                label="Analizando...",
                overlay_id="pm-render-overlay",
                min_height="60vh",
                floating=True,
            ),
        ],
    )
