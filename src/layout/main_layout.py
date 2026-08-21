from datetime import datetime

import dash_bootstrap_components as dbc
import flask
from dash import dcc, html

from src.chatbot.chat_panel import build_chat_fab, build_chat_modal
from src.core import data_master
from src.core.auth import get_current_org_access, get_current_role
from src.core.config import MODO_DESARROLLO
from src.layout.admin.admin_shell import build_admin_shell
from src.layout.sidebar import build_sidebar
from src.layout.tabs.tab_bi import build_tab_bi
from src.layout.tabs.tab_informes import build_tab_informes
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
                                            className="mb-0",
                                            style={
                                                "fontSize": "1.45rem",
                                                "fontWeight": "700",
                                                "letterSpacing": "-0.5px",
                                                "color": "#0f0f0f",
                                                "lineHeight": "1.1",
                                            },
                                        ),
                                        html.Span(
                                            datetime.today().strftime("%-d de %B · %Y"),
                                            style={
                                                "fontSize": "0.7rem",
                                                "color": "#b0b0aa",
                                                "fontWeight": "400",
                                                "marginTop": "3px",
                                                "letterSpacing": "0.02em",
                                            },
                                        ),
                                    ],
                                    className="d-flex flex-column justify-content-center",
                                ),
                                html.Div(
                                    html.Img(
                                        id="org-logo-img",
                                        src="",
                                        style={
                                            "maxHeight": "36px",
                                            "maxWidth": "140px",
                                            "objectFit": "contain",
                                        },
                                    ),
                                    id="org-logo-wrapper",
                                    className="ms-3 flex-shrink-0",
                                    style={"display": "none"},
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
                                    "Sincronizar",
                                    id="btn-sync",
                                    color="primary",
                                    outline=True,
                                    size="sm",
                                    className="fw-bold rounded-3 shadow-sm me-2 d-none",
                                ),
                                (
                                    html.A(
                                        html.I(className="fas fa-shield-halved"),
                                        id="btn-admin-panel",
                                        href="/admin/usuarios",
                                        className="header-icon-btn me-1",
                                        title="Panel de administración",
                                    )
                                    if role == "admin"
                                    else html.Span(id="btn-admin-panel")
                                ),
                                (
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.Span(
                                                        (
                                                            session_id[0].upper()
                                                            if session_id
                                                            else "?"
                                                        ),
                                                        style={
                                                            "fontSize": "0.68rem",
                                                            "fontWeight": "700",
                                                            "color": "#4f46e5",
                                                            "lineHeight": "1",
                                                        },
                                                    )
                                                ],
                                                style={
                                                    "width": "28px",
                                                    "height": "28px",
                                                    "borderRadius": "50%",
                                                    "background": "#e0e7ff",
                                                    "display": "flex",
                                                    "alignItems": "center",
                                                    "justifyContent": "center",
                                                    "flexShrink": "0",
                                                },
                                            ),
                                            html.Span(
                                                session_id,
                                                className="small mx-2",
                                                style={"fontWeight": "500", "color": "#374151"},
                                            ),
                                            html.Span(
                                                style={
                                                    "width": "1px",
                                                    "height": "16px",
                                                    "background": "#e5e7eb",
                                                    "marginRight": "10px",
                                                }
                                            ),
                                            html.A(
                                                html.I(className="fas fa-right-from-bracket"),
                                                href="/logout",
                                                className="header-icon-btn",
                                                title="Cerrar sesión",
                                            ),
                                        ],
                                        className="d-flex align-items-center header-user-chip",
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
                                    build_tab_prediccion_cliente(role=role),
                                    *([build_tab_informes()] if role == "admin" else []),
                                ],
                            )
                        ]
                    )
                ],
                className="border-0 rounded-4",
                style={
                    "background": "#ffffff",
                    "boxShadow": "0 1px 4px rgba(0,0,0,.05), 0 4px 20px rgba(0,0,0,.04)",
                },
            ),
        ]
    )

    return dbc.Container(
        id="main-container",
        children=[
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="session-id", data=session_id),
            dcc.Store(id="data-version", data=0),
            dcc.Store(id="sync-trigger", data=0),
            dcc.Store(id="sync-phase", data="configure"),
            dcc.Store(id="sidebar-open", data=True),
            dcc.Store(id="loc-loaded", data=None),
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
                    dbc.ModalHeader(
                        dbc.ModalTitle(
                            [
                                html.I(className="fas fa-rotate me-2 text-primary"),
                                "Sincronizar datos",
                            ],
                            className="fw-bold",
                        ),
                        close_button=True,
                    ),
                    dbc.ModalBody(
                        html.Div(
                            [
                                # ── Fase 1: Configuración ────────────────────────
                                html.Div(
                                    id="sync-configure-phase",
                                    children=[
                                        html.P(
                                            "Descargará datos desde la última fecha registrada para la ubicación seleccionada.",
                                            className="text-muted small mb-3",
                                        ),
                                        dbc.Switch(
                                            id="sync-use-rango",
                                            label="Restaurar rango específico",
                                            value=False,
                                            className="mb-2",
                                        ),
                                        dbc.Collapse(
                                            id="sync-rango-collapse",
                                            is_open=False,
                                            children=[
                                                dbc.Alert(
                                                    [
                                                        html.I(className="fas fa-info-circle me-2"),
                                                        "Los datos existentes en el rango serán sobreescritos con los valores actuales de la API.",
                                                    ],
                                                    color="info",
                                                    className="rounded-3 border-0 py-2 small mb-3",
                                                ),
                                                dbc.Row(
                                                    [
                                                        dbc.Col(
                                                            [
                                                                html.Label(
                                                                    "Desde",
                                                                    className="form-label fw-bold small text-muted",
                                                                ),
                                                                dcc.DatePickerSingle(
                                                                    id="sync-input-desde",
                                                                    display_format="DD MMM YYYY",
                                                                    placeholder="Fecha inicio",
                                                                    first_day_of_week=1,
                                                                    style={"width": "100%"},
                                                                ),
                                                            ],
                                                            width=6,
                                                        ),
                                                        dbc.Col(
                                                            [
                                                                html.Label(
                                                                    "Hasta",
                                                                    className="form-label fw-bold small text-muted",
                                                                ),
                                                                dcc.DatePickerSingle(
                                                                    id="sync-input-hasta",
                                                                    display_format="DD MMM YYYY",
                                                                    placeholder="Fecha fin",
                                                                    first_day_of_week=1,
                                                                    style={"width": "100%"},
                                                                ),
                                                            ],
                                                            width=6,
                                                        ),
                                                    ],
                                                    className="g-2 mb-3",
                                                ),
                                            ],
                                        ),
                                        dbc.Button(
                                            [
                                                html.I(className="fas fa-play me-2"),
                                                "Iniciar sincronización",
                                            ],
                                            id="btn-iniciar-sync",
                                            color="primary",
                                            className="w-100 rounded-3 fw-bold mt-2",
                                        ),
                                    ],
                                ),
                                # ── Fase 2: Progreso ─────────────────────────────
                                html.Div(
                                    id="sync-progress-phase",
                                    style={"display": "none"},
                                    children=[
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
                                            id="sync-progress-text",
                                            className="text-muted small mb-3",
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
            html.Div(
                id="dashboard-container",
                children=dbc.Row(
                    [
                        dbc.Col(
                            sidebar, id="sidebar-col", xs=12, lg=3, xl=2, className="mb-4 mb-lg-0"
                        ),
                        dbc.Col(main_content, id="main-col", xs=12, lg=9, xl=10),
                    ]
                ),
            ),
            build_admin_shell(),
        ],
        fluid=True,
        style={
            "padding": "28px 32px",
            "minHeight": "100vh",
            "background": "#f7f7f5",
        },
    )
