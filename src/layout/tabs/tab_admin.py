import dash_bootstrap_components as dbc
from dash import dcc, html


def build_admin_content():
    return html.Div(
        [
            html.Br(),
            dcc.Store(id="admin-crud-signal", data=0),
            dcc.Store(id="admin-pending-delete", data=None),
            dcc.Store(id="admin-zone-edit-loc", data=None),
            dcc.Store(id="admin-access-modal-user", data=None),
            # Modal gestión de acceso por organización
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle(
                            [
                                html.I(className="fas fa-key me-2"),
                                html.Span(id="admin-access-modal-title"),
                            ],
                            className="fw-bold text-primary",
                        ),
                        close_button=True,
                    ),
                    dbc.ModalBody(
                        html.Div(
                            [
                                html.P(
                                    id="admin-access-modal-info",
                                    className="text-muted small mb-3",
                                ),
                                dbc.Checklist(
                                    id="admin-access-checklist",
                                    options=[],
                                    value=[],
                                    input_class_name="me-2",
                                ),
                            ],
                            className="px-1",
                        )
                    ),
                    dbc.ModalFooter(
                        [
                            dbc.Button(
                                [html.I(className="fas fa-times me-2"), "Cancelar"],
                                id="admin-access-modal-cancel",
                                color="secondary",
                                outline=True,
                                className="rounded-3 me-2",
                            ),
                            dbc.Button(
                                [html.I(className="fas fa-save me-2"), "Guardar acceso"],
                                id="admin-access-modal-save",
                                color="primary",
                                className="rounded-3 fw-bold shadow-sm",
                            ),
                        ]
                    ),
                ],
                id="admin-access-modal",
                is_open=False,
                size="lg",
                centered=True,
                contentClassName="border-0 rounded-4 shadow",
            ),
            # Modal edición jerarquía de zonas
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle(
                            [
                                html.I(className="fas fa-sitemap me-2"),
                                html.Span(id="admin-zone-modal-title"),
                            ],
                            className="fw-bold text-primary",
                        ),
                        close_button=True,
                    ),
                    dbc.ModalBody(
                        html.Div(id="admin-zone-modal-body", style={"minHeight": "120px"}),
                    ),
                    dbc.ModalFooter(
                        [
                            dbc.Button(
                                [html.I(className="fas fa-times me-2"), "Cancelar"],
                                id="admin-zone-modal-cancel",
                                color="secondary",
                                outline=True,
                                className="rounded-3 me-2",
                            ),
                            dbc.Button(
                                [html.I(className="fas fa-save me-2"), "Publicar jerarquía"],
                                id="admin-zone-modal-save",
                                color="primary",
                                className="rounded-3 fw-bold shadow-sm",
                            ),
                        ]
                    ),
                ],
                id="admin-zone-modal",
                is_open=False,
                size="lg",
                centered=True,
                contentClassName="border-0 rounded-4 shadow",
            ),
            # Modal de confirmación unificado (usuarios / ubicaciones / orgs)
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle(
                            [
                                html.I(className="fas fa-exclamation-triangle me-2"),
                                "Confirmar eliminación",
                            ],
                            className="text-danger fw-bold",
                        ),
                    ),
                    dbc.ModalBody(html.Div(id="admin-delete-modal-body")),
                    dbc.ModalFooter(
                        [
                            dbc.Button(
                                [html.I(className="fas fa-times me-2"), "Cancelar"],
                                id="admin-cancel-delete-btn",
                                color="secondary",
                                outline=True,
                                className="rounded-3 me-2",
                            ),
                            dbc.Button(
                                [html.I(className="fas fa-trash-alt me-2"), "Eliminar"],
                                id="admin-confirm-delete-btn",
                                color="danger",
                                className="rounded-3 fw-bold",
                            ),
                        ]
                    ),
                ],
                id="admin-delete-modal",
                is_open=False,
                centered=True,
                contentClassName="border-0 rounded-4 shadow",
            ),
            dbc.Tabs(
                id="admin-sub-tabs",
                active_tab="admin-tab-users",
                children=[
                    # ── Pestaña POIs ─────────────────────────────────────────────────
                    dbc.Tab(
                        label="POIs",
                        tab_id="admin-tab-pois",
                        tab_style={"fontWeight": "600"},
                        children=[
                            html.Br(),
                            dbc.Alert(
                                id="admin-pois-feedback",
                                is_open=False,
                                dismissable=True,
                                duration=5000,
                                className="mb-3 rounded-3 border-0 shadow-sm",
                            ),
                            # Modal añadir / editar POI
                            dbc.Modal(
                                [
                                    dbc.ModalHeader(
                                        dbc.ModalTitle(
                                            [
                                                html.I(className="fas fa-map-pin me-2"),
                                                html.Span(
                                                    id="admin-poi-modal-title",
                                                    children="Añadir POI",
                                                ),
                                            ],
                                            className="fw-bold text-primary",
                                        ),
                                        close_button=True,
                                    ),
                                    dbc.ModalBody(
                                        [
                                            dcc.Store(id="admin-poi-edit-id", data=None),
                                            dbc.Row(
                                                [
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                "Nombre",
                                                                className="fw-bold small text-muted mb-1",
                                                            ),
                                                            dbc.Input(
                                                                id="admin-poi-nombre",
                                                                placeholder="Gran Vía · L1/L5",
                                                                className="rounded-3",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=8,
                                                    ),
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                "Categoría",
                                                                className="fw-bold small text-muted mb-1",
                                                            ),
                                                            dbc.Select(
                                                                id="admin-poi-categoria",
                                                                className="rounded-3",
                                                                options=[
                                                                    {
                                                                        "label": "Metro / Transporte",
                                                                        "value": "metro",
                                                                    },
                                                                    {
                                                                        "label": "Polo turístico",
                                                                        "value": "tourist_poi",
                                                                    },
                                                                    {
                                                                        "label": "Sala de eventos",
                                                                        "value": "event_venue",
                                                                    },
                                                                    {
                                                                        "label": "Competidor",
                                                                        "value": "competitor",
                                                                    },
                                                                    {
                                                                        "label": "Otro",
                                                                        "value": "otro",
                                                                    },
                                                                ],
                                                                value="metro",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=4,
                                                    ),
                                                ],
                                                className="g-3 mb-3",
                                            ),
                                            dbc.Row(
                                                [
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                "Latitud",
                                                                className="fw-bold small text-muted mb-1",
                                                            ),
                                                            dbc.Input(
                                                                id="admin-poi-lat",
                                                                placeholder="40.4193",
                                                                type="number",
                                                                step="0.0001",
                                                                className="rounded-3",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=4,
                                                    ),
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                "Longitud",
                                                                className="fw-bold small text-muted mb-1",
                                                            ),
                                                            dbc.Input(
                                                                id="admin-poi-lon",
                                                                placeholder="-3.7014",
                                                                type="number",
                                                                step="0.0001",
                                                                className="rounded-3",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=4,
                                                    ),
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                "Relevancia (0-1)",
                                                                className="fw-bold small text-muted mb-1",
                                                            ),
                                                            dbc.Input(
                                                                id="admin-poi-valor",
                                                                placeholder="0.8",
                                                                type="number",
                                                                min=0,
                                                                max=1,
                                                                step=0.05,
                                                                className="rounded-3",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=4,
                                                    ),
                                                ],
                                                className="g-3 mb-3",
                                            ),
                                            dbc.Row(
                                                [
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                "Descripción / detalle",
                                                                className="fw-bold small text-muted mb-1",
                                                            ),
                                                            dbc.Input(
                                                                id="admin-poi-detalle",
                                                                placeholder="~32 000 validaciones/día · 3 min a pie",
                                                                className="rounded-3",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=8,
                                                    ),
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                "Radio influencia (m)",
                                                                className="fw-bold small text-muted mb-1",
                                                            ),
                                                            dbc.Input(
                                                                id="admin-poi-radio",
                                                                placeholder="400",
                                                                type="number",
                                                                min=0,
                                                                step=50,
                                                                className="rounded-3",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=4,
                                                    ),
                                                ],
                                                className="g-3",
                                            ),
                                        ]
                                    ),
                                    dbc.ModalFooter(
                                        [
                                            dbc.Button(
                                                [html.I(className="fas fa-times me-2"), "Cancelar"],
                                                id="admin-poi-modal-cancel",
                                                color="secondary",
                                                outline=True,
                                                className="rounded-3 me-2",
                                            ),
                                            dbc.Button(
                                                [
                                                    html.I(className="fas fa-save me-2"),
                                                    "Guardar POI",
                                                ],
                                                id="admin-poi-modal-save",
                                                color="primary",
                                                className="rounded-3 fw-bold shadow-sm",
                                            ),
                                        ]
                                    ),
                                ],
                                id="admin-poi-modal",
                                is_open=False,
                                size="lg",
                                centered=True,
                                contentClassName="border-0 rounded-4 shadow",
                            ),
                            # Selector de ubicación + botones de acción
                            dbc.Card(
                                [
                                    dbc.CardBody(
                                        [
                                            dbc.Row(
                                                [
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                "Ubicación",
                                                                className="fw-bold small text-muted mb-1",
                                                            ),
                                                            dbc.Select(
                                                                id="admin-pois-loc-select",
                                                                placeholder="Selecciona una ubicación…",
                                                                className="rounded-3",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=6,
                                                    ),
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                " ",
                                                                className="fw-bold small text-muted mb-1 d-block",
                                                            ),
                                                            dbc.ButtonGroup(
                                                                [
                                                                    dbc.Button(
                                                                        [
                                                                            html.I(
                                                                                className="fas fa-plus me-2"
                                                                            ),
                                                                            "Añadir POI",
                                                                        ],
                                                                        id="admin-poi-add-btn",
                                                                        color="primary",
                                                                        outline=True,
                                                                        className="rounded-start-3 fw-bold",
                                                                    ),
                                                                    dbc.Button(
                                                                        [
                                                                            html.I(
                                                                                className="fas fa-satellite me-2"
                                                                            ),
                                                                            "Esri Places",
                                                                        ],
                                                                        id="admin-pois-sync-btn",
                                                                        color="success",
                                                                        outline=True,
                                                                        className="fw-bold",
                                                                    ),
                                                                    dbc.Button(
                                                                        [
                                                                            html.I(
                                                                                className="fab fa-google me-2"
                                                                            ),
                                                                            "Google Places",
                                                                        ],
                                                                        id="admin-pois-google-sync-btn",
                                                                        color="info",
                                                                        outline=True,
                                                                        className="rounded-end-3 fw-bold",
                                                                    ),
                                                                ],
                                                                className="w-100",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=6,
                                                        className="d-flex flex-column justify-content-end",
                                                    ),
                                                ],
                                                className="g-3",
                                            ),
                                        ],
                                        className="p-3",
                                    ),
                                ],
                                className="border-0 shadow-sm rounded-4 mb-3",
                            ),
                            # Tabla de POIs
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        [
                                            html.I(className="fas fa-map-pin me-2 text-primary"),
                                            html.Span(
                                                "Puntos de interés",
                                                className="fw-bold small text-uppercase text-muted",
                                            ),
                                        ],
                                        className="bg-white border-bottom py-2 px-4",
                                    ),
                                    dbc.CardBody(
                                        html.Div(
                                            id="admin-pois-table", style={"minHeight": "120px"}
                                        ),
                                        className="p-0",
                                    ),
                                ],
                                className="border-0 shadow-sm rounded-4 overflow-hidden",
                            ),
                        ],
                    ),
                    # ── Pestaña Usuarios ─────────────────────────────────────────────
                    dbc.Tab(
                        label="Usuarios",
                        tab_id="admin-tab-users",
                        tab_style={"fontWeight": "600"},
                        children=[
                            html.Br(),
                            # Feedback
                            dbc.Alert(
                                id="admin-users-feedback",
                                is_open=False,
                                dismissable=True,
                                className="mb-4 rounded-3 border-0 shadow-sm",
                            ),
                            # Tabla de usuarios
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        [
                                            html.I(className="fas fa-users me-2 text-primary"),
                                            html.Span(
                                                "Gestión de usuarios",
                                                className="fw-bold small text-uppercase text-muted",
                                            ),
                                        ],
                                        className="bg-white border-bottom py-2 px-4",
                                    ),
                                    dbc.CardBody(
                                        html.Div(
                                            id="admin-users-table-container",
                                            style={"minHeight": "120px"},
                                        ),
                                        className="p-0",
                                    ),
                                ],
                                className="border-0 shadow-sm rounded-4 mb-4 overflow-hidden",
                            ),
                            # Formulario añadir usuario
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        [
                                            html.I(className="fas fa-user-plus me-2 text-primary"),
                                            html.Span(
                                                "Añadir usuario",
                                                className="fw-bold small text-uppercase text-muted",
                                            ),
                                        ],
                                        className="bg-white border-bottom py-2 px-4",
                                    ),
                                    dbc.CardBody(
                                        [
                                            dbc.Row(
                                                [
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                "Usuario",
                                                                className="fw-bold small text-muted mb-1",
                                                            ),
                                                            dbc.Input(
                                                                id="admin-new-username",
                                                                placeholder="nombre de usuario",
                                                                type="text",
                                                                className="rounded-3",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=4,
                                                    ),
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                "Contraseña",
                                                                className="fw-bold small text-muted mb-1",
                                                            ),
                                                            dbc.Input(
                                                                id="admin-new-password",
                                                                placeholder="contraseña",
                                                                type="password",
                                                                className="rounded-3",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=4,
                                                    ),
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                "Rol",
                                                                className="fw-bold small text-muted mb-1",
                                                            ),
                                                            dbc.Select(
                                                                id="admin-new-role",
                                                                options=[
                                                                    {
                                                                        "label": "Usuario",
                                                                        "value": "user",
                                                                    },
                                                                    {
                                                                        "label": "Administrador",
                                                                        "value": "admin",
                                                                    },
                                                                ],
                                                                value="user",
                                                                className="rounded-3",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=2,
                                                    ),
                                                    dbc.Col(
                                                        [
                                                            dbc.Label(
                                                                " ",
                                                                className="fw-bold small text-muted mb-1 d-block",
                                                            ),
                                                            dbc.Button(
                                                                [
                                                                    html.I(
                                                                        className="fas fa-plus me-2"
                                                                    ),
                                                                    "Añadir",
                                                                ],
                                                                id="admin-add-user-btn",
                                                                color="primary",
                                                                className="rounded-3 w-100 fw-bold shadow-sm",
                                                            ),
                                                        ],
                                                        xs=12,
                                                        md=2,
                                                    ),
                                                ],
                                                className="g-3",
                                            ),
                                        ],
                                        className="p-4",
                                    ),
                                ],
                                className="border-0 shadow-sm rounded-4 overflow-hidden",
                            ),
                        ],
                    ),
                    # ── Pestaña Árbol de ubicaciones ─────────────────────────────────
                    dbc.Tab(
                        label="Árbol de ubicaciones",
                        tab_id="admin-tab-locs",
                        tab_style={"fontWeight": "600"},
                        children=[
                            html.Br(),
                            dbc.Alert(
                                id="admin-locs-feedback",
                                is_open=False,
                                dismissable=True,
                                className="mb-4 rounded-3 border-0 shadow-sm",
                            ),
                            html.Div(id="admin-locs-container", style={"minHeight": "200px"}),
                        ],
                    ),
                ],
                className="mb-3",
            ),
        ],
        style={"overflowY": "auto"},
    )


def build_tab_admin():
    return dcc.Tab(
        label="Admin",
        value="tab-admin",
        className="fw-bold",
        children=[build_admin_content()],
    )
