from datetime import datetime

import dash_bootstrap_components as dbc
import flask
from dash import dcc, html

from src.chatbot.chat_panel import build_chat_fab, build_chat_modal
from src.core import data_master
from src.core.auth import get_current_org_access, get_current_role
from src.core.config import MODO_DESARROLLO
from src.layout.sidebar import build_sidebar
from src.layout.tabs.tab_admin import build_admin_content
from src.layout.tabs.tab_bi import build_tab_bi
from src.layout.tabs.tab_ml import build_tab_ml
from src.layout.tabs.tab_pm import build_tab_pm
from src.layout.tabs.tab_prediccion_cliente import build_tab_prediccion_cliente


def serve_layout():
    session_id = "local_dev" if MODO_DESARROLLO else flask.session.get("user", "")
    role = get_current_role()

    data_master.reload_if_changed()
    org_options = data_master.get_opciones_orgs_for_user(get_current_org_access())
    sidebar = build_sidebar(org_options=org_options)

    main_content = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            [
                                dbc.Button(
                                    html.I(className="fas fa-bars", id="sidebar-toggle-icon"),
                                    id="btn-sidebar-toggle",
                                    color="link",
                                    size="sm",
                                    className="text-secondary p-0 me-3 flex-shrink-0",
                                    style={"fontSize": "1.05rem", "lineHeight": "1"},
                                ),
                                html.Div(
                                    [
                                        html.H2(
                                            "Operaciones",
                                            className="fw-bold text-dark mb-0",
                                            style={"fontSize": "1.5rem", "letterSpacing": "-0.3px"},
                                        ),
                                        html.Span(
                                            datetime.today().strftime("%-d de %B · %Y"),
                                            style={
                                                "fontSize": "0.75rem",
                                                "color": "#8492a6",
                                                "fontWeight": "500",
                                                "marginTop": "2px",
                                            },
                                        ),
                                    ],
                                    className="d-flex flex-column justify-content-center",
                                ),
                            ],
                            className="d-flex align-items-center",
                        ),
                        xs=12,
                        md=7,
                        className="mb-4 mb-md-0",
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                dbc.Button(
                                    [html.I(className="fas fa-sync-alt me-2"), "Sincronizar"],
                                    id="btn-sync",
                                    color="primary",
                                    outline=True,
                                    size="sm",
                                    className="fw-bold rounded-3 shadow-sm me-2 d-none",
                                ),
                                (
                                    dbc.Button(
                                        [html.I(className="fas fa-shield-halved me-1"), "Admin"],
                                        id="btn-admin-panel",
                                        color="secondary",
                                        outline=True,
                                        size="sm",
                                        className="fw-bold rounded-3 shadow-sm me-2",
                                    )
                                    if role == "admin"
                                    else html.Span(id="btn-admin-panel")
                                ),
                                (
                                    html.A(
                                        [
                                            html.I(className="fas fa-user-circle me-1"),
                                            session_id,
                                        ],
                                        href="/logout",
                                        className="btn btn-outline-secondary btn-sm fw-bold rounded-3 shadow-sm",
                                    )
                                    if not MODO_DESARROLLO
                                    else html.Span()
                                ),
                            ],
                            className="d-flex align-items-center justify-content-center justify-content-md-end",
                        ),
                        xs=12,
                        md=5,
                        className="text-center text-md-end",
                    ),
                ],
                id="cabecera-app",
                className="mb-4 align-items-center d-print-none",
            ),
            dbc.Card(
                [
                    dbc.CardBody(
                        [
                            dcc.Tabs(
                                id="tabs-panel",
                                value="tab-ejecutivo",
                                className="custom-tabs",
                                children=[
                                    build_tab_pm(),
                                    build_tab_bi(),
                                    build_tab_prediccion_cliente(),
                                    *([] if role != "admin" else [build_tab_ml()]),
                                ],
                            )
                        ]
                    )
                ],
                className="border-0 shadow-sm rounded-4",
            ),
        ]
    )

    return dbc.Container(
        [
            dcc.Store(id="session-id", data=session_id),
            dcc.Store(id="data-version", data=0),
            dcc.Store(id="sync-trigger", data=0),
            dcc.Store(id="sidebar-open", data=True),
            dcc.Interval(id="interval-staleness", interval=5 * 60 * 1000, n_intervals=0),
            dcc.Interval(id="interval-sync-poll", interval=1500, n_intervals=0, disabled=True),
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle(id="modal-bi-title", className="fw-bold text-primary")
                    ),
                    dbc.ModalBody(dcc.Graph(id="modal-bi-graph", style={"height": "75vh"})),
                ],
                id="modal-bi-fullscreen",
                size="xl",
                is_open=False,
                centered=True,
            ),
            dbc.Modal(
                [
                    dbc.ModalBody(
                        html.Div(
                            [
                                html.Div(
                                    [
                                        dbc.Spinner(color="primary", size="sm"),
                                        html.H6(
                                            "Sincronizando datos…",
                                            className="ms-3 mb-0 text-primary fw-bold",
                                        ),
                                    ],
                                    className="d-flex align-items-center mb-3",
                                ),
                                dbc.Progress(
                                    id="sync-progress-bar",
                                    value=0,
                                    max=100,
                                    striped=True,
                                    animated=True,
                                    color="primary",
                                    className="mb-2",
                                    style={"height": "10px", "borderRadius": "5px"},
                                ),
                                html.Div(
                                    id="sync-progress-text", className="text-muted small mb-3"
                                ),
                                dbc.Button(
                                    [html.I(className="fas fa-times me-1"), "Cancelar"],
                                    id="btn-cancel-sync",
                                    color="danger",
                                    outline=True,
                                    size="sm",
                                    className="rounded-3",
                                ),
                            ],
                            className="p-4",
                        ),
                        className="p-0",
                    ),
                ],
                id="modal-sync",
                is_open=False,
                backdrop="static",
                keyboard=False,
                centered=True,
                contentClassName="border-0 rounded-4",
                style={"boxShadow": "0 20px 60px rgba(0,0,0,0.15)"},
            ),
            dbc.Modal(
                [
                    dbc.ModalBody(
                        html.Div(
                            [
                                html.Div(
                                    [
                                        dbc.Spinner(color="primary", size="sm"),
                                        html.H6(
                                            id="modal-ml-label",
                                            children="Entrenando modelo…",
                                            className="ms-3 mb-0 text-primary fw-bold",
                                        ),
                                    ],
                                    className="d-flex align-items-center mb-3",
                                ),
                                html.P(
                                    "El motor XGBoost está procesando el histórico. Esto puede tardar unos segundos.",
                                    className="text-muted small mb-0",
                                ),
                            ],
                            className="p-4",
                        ),
                        className="p-0",
                    ),
                ],
                id="modal-ml-loading",
                is_open=False,
                backdrop="static",
                keyboard=False,
                centered=True,
                contentClassName="border-0 rounded-4",
                style={"boxShadow": "0 20px 60px rgba(0,0,0,0.15)"},
            ),
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle(
                            [
                                html.I(className="fas fa-shield-halved me-2 text-primary"),
                                "Panel de administración",
                            ],
                            className="fw-bold",
                        ),
                        close_button=True,
                    ),
                    dbc.ModalBody(build_admin_content(), className="p-0"),
                ],
                id="modal-admin-panel",
                size="xl",
                is_open=False,
                scrollable=True,
                centered=False,
                contentClassName="border-0 rounded-4",
                style={"boxShadow": "0 20px 60px rgba(0,0,0,0.15)"},
            ),
            dbc.Toast(
                id="toast-notificacion",
                header="Notificación",
                is_open=False,
                dismissable=True,
                icon="info",
                duration=4000,
                style={
                    "position": "fixed",
                    "top": 20,
                    "right": 20,
                    "width": 350,
                    "zIndex": 9999,
                    "fontSize": "15px",
                },
            ),
            build_chat_modal(),
            build_chat_fab(),
            dbc.Row(
                [
                    dbc.Col(sidebar, id="sidebar-col", xs=12, lg=3, xl=2, className="mb-4 mb-lg-0"),
                    dbc.Col(main_content, id="main-col", xs=12, lg=9, xl=10),
                ]
            ),
        ],
        fluid=True,
        style={"padding": "30px", "minHeight": "100vh"},
    )
