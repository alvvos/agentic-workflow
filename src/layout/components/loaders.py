import dash_bootstrap_components as dbc
from dash import dcc, html


def _modal_spinner(label: str) -> html.Div:
    """Backdrop blur + centered card. Identical appearance everywhere."""
    return html.Div(
        [
            html.Div(className="loader-backdrop"),
            html.Div(
                [
                    dbc.Spinner(color="primary", size="lg"),
                    html.H5(label, className="ms-3 mb-0 text-primary fw-bold"),
                ],
                className="loader-card",
            ),
        ]
    )


def loading_zone(
    child,
    label: str = "Cargando...",
    min_height: str = "400px",
    delay_show: int = 350,
    floating: bool = False,
) -> dcc.Loading:
    return dcc.Loading(
        child,
        custom_spinner=_modal_spinner(label),
        delay_show=delay_show,
        delay_hide=0,
    )


def render_overlay(overlay_id: str, min_height: str = "60vh") -> html.Div:
    return html.Div(
        id=overlay_id,
        style={"display": "none"},
        children=_modal_spinner("Renderizando..."),
    )


def loading_section(
    child,
    label: str,
    overlay_id: str,
    min_height: str = "60vh",
    delay_show: int = 350,
    floating: bool = False,
) -> html.Div:
    return html.Div(
        style={"position": "relative"},
        children=[
            loading_zone(child, label, min_height, delay_show),
            render_overlay(overlay_id),
        ],
    )
