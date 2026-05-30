from dash import html, dcc
from src.reporting.ml_dashboard import generar_panel_ml


def build_tab_ml():
    return dcc.Tab(label='Forecasting', value='tab-ml', className="fw-bold", children=[
        html.Br(),
        generar_panel_ml()
    ])
