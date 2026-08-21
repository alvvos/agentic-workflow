import dash_bootstrap_components as dbc
import flask
from dash import dcc, html

from src.core.config import MODO_DESARROLLO
from src.layout.admin.page_pois import build_page_pois
from src.layout.admin.page_ubicaciones import build_page_ubicaciones
from src.layout.admin.page_usuarios import build_page_usuarios

_NAV_ITEMS = [
    ("fas fa-users", "Usuarios", "/admin/usuarios", "admin-nav-usuarios"),
    ("fas fa-building", "Ubicaciones", "/admin/ubicaciones", "admin-nav-ubicaciones"),
    ("fas fa-map-pin", "POIs", "/admin/pois", "admin-nav-pois"),
]


def build_admin_shell():
    session_id = "local_dev" if MODO_DESARROLLO else flask.session.get("user", "")

    header = html.Div(
        dbc.Container(
            dbc.Row(
                [
                    dbc.Col(
                        dcc.Link(
                            [html.I(className="fas fa-arrow-left me-2"), "Dashboard"],
                            href="/",
                            className="btn btn-outline-secondary btn-sm rounded-3 fw-bold",
                        ),
                        width="auto",
                        className="d-flex align-items-center",
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                html.I(className="fas fa-shield-halved me-2 text-primary"),
                                html.Span("Admin", className="fw-bold fs-5"),
                            ],
                            className="d-flex align-items-center",
                        ),
                    ),
                    dbc.Col(
                        html.Span(
                            [
                                html.I(className="fas fa-circle-user me-2 text-muted"),
                                session_id,
                            ],
                            className="text-muted small",
                        ),
                        width="auto",
                        className="d-flex align-items-center",
                    ),
                ],
                align="center",
                className="g-3",
            ),
            fluid=True,
        ),
        className="bg-white border-bottom py-3 px-2 d-print-none",
        style={
            "position": "sticky",
            "top": 0,
            "zIndex": 1000,
            "boxShadow": "0 1px 4px rgba(0,0,0,.06)",
        },
    )

    nav = html.Div(
        [
            html.Div(
                "Secciones",
                className="text-uppercase mb-3 px-3 opacity-50",
                style={
                    "fontSize": "0.65rem",
                    "fontWeight": "700",
                    "letterSpacing": "0.1em",
                    "color": "#fff",
                },
            ),
            *[
                html.A(
                    [html.I(className=f"{icon} me-3"), label],
                    id=nav_id,
                    href=href,
                    className="admin-nav-link d-flex align-items-center px-3 py-2 mb-1 rounded-3 text-decoration-none",
                )
                for icon, label, href, nav_id in _NAV_ITEMS
            ],
        ],
        style={
            "width": "210px",
            "minWidth": "210px",
            "background": "#1a1a2e",
            "height": "100%",
            "overflowY": "auto",
            "padding": "24px 10px",
            "flexShrink": 0,
        },
    )

    pages = html.Div(
        [
            html.Div(
                id="admin-page-usuarios",
                children=build_page_usuarios(),
                style={"display": "none"},
            ),
            html.Div(
                id="admin-page-ubicaciones",
                children=build_page_ubicaciones(),
                style={"display": "none"},
            ),
            html.Div(
                id="admin-page-pois",
                children=build_page_pois(),
                style={"display": "none"},
            ),
        ],
        style={"flex": "1", "overflowY": "auto", "overflowX": "hidden"},
    )

    return html.Div(
        id="admin-container",
        style={"display": "none"},
        children=[
            dcc.Store(id="admin-crud-signal", data=0),
            dcc.Store(id="admin-pending-delete", data=None),
            dcc.Store(id="admin-zone-edit-loc", data=None),
            dcc.Store(id="admin-access-modal-user", data=None),
            dcc.Store(id="admin-poi-edit-id", data=None),
            header,
            html.Div(
                [nav, pages],
                className="d-flex",
                style={"height": "calc(100vh - 57px)", "overflow": "hidden"},
            ),
        ],
    )
