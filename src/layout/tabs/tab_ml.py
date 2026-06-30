from dash import dcc, html

from src.reporting.ml_dashboard import generar_panel_ml


def build_tab_ml():
    return dcc.Tab(
        label="Laboratorio",
        value="tab-ml",
        className="fw-bold text-muted",
        children=[html.Br(), generar_panel_ml()],
    )
