from dash import html, dcc
import dash_bootstrap_components as dbc


def build_tab_admin():
    return dcc.Tab(label='Admin', value='tab-admin', className="fw-bold", children=[
        html.Br(),

        dcc.Store(id='admin-crud-signal', data=0),
        dcc.Store(id='admin-pending-delete', data=None),
        dcc.Store(id='admin-zone-edit-loc', data=None),

        # Modal edición jerarquía de zonas
        dbc.Modal([
            dbc.ModalHeader(
                dbc.ModalTitle([
                    html.I(className="fas fa-sitemap me-2"),
                    html.Span(id="admin-zone-modal-title"),
                ], className="fw-bold text-primary"),
                close_button=True,
            ),
            dbc.ModalBody(
                html.Div(id="admin-zone-modal-body", style={"minHeight": "120px"}),
            ),
            dbc.ModalFooter([
                dbc.Button(
                    [html.I(className="fas fa-times me-2"), "Cancelar"],
                    id="admin-zone-modal-cancel", color="secondary",
                    outline=True, className="rounded-3 me-2",
                ),
                dbc.Button(
                    [html.I(className="fas fa-save me-2"), "Publicar jerarquía"],
                    id="admin-zone-modal-save", color="primary",
                    className="rounded-3 fw-bold shadow-sm",
                ),
            ]),
        ], id="admin-zone-modal", is_open=False, size="lg", centered=True,
           contentClassName="border-0 rounded-4 shadow"),

        # Modal de confirmación unificado (usuarios / ubicaciones / orgs)
        dbc.Modal([
            dbc.ModalHeader(
                dbc.ModalTitle([
                    html.I(className="fas fa-exclamation-triangle me-2"),
                    "Confirmar eliminación",
                ], className="text-danger fw-bold"),
            ),
            dbc.ModalBody(html.Div(id='admin-delete-modal-body')),
            dbc.ModalFooter([
                dbc.Button(
                    [html.I(className="fas fa-times me-2"), "Cancelar"],
                    id='admin-cancel-delete-btn', color="secondary",
                    outline=True, className="rounded-3 me-2",
                ),
                dbc.Button(
                    [html.I(className="fas fa-trash-alt me-2"), "Eliminar"],
                    id='admin-confirm-delete-btn', color="danger",
                    className="rounded-3 fw-bold",
                ),
            ]),
        ], id='admin-delete-modal', is_open=False, centered=True,
           contentClassName="border-0 rounded-4 shadow"),

        dbc.Tabs(id='admin-sub-tabs', active_tab='admin-tab-users', children=[

            # ── Pestaña Usuarios ─────────────────────────────────────────────
            dbc.Tab(label='Usuarios', tab_id='admin-tab-users',
                    tab_style={"fontWeight": "600"}, children=[
                html.Br(),

                # Feedback
                dbc.Alert(id='admin-users-feedback', is_open=False, dismissable=True,
                          className="mb-4 rounded-3 border-0 shadow-sm"),

                # Tabla de usuarios
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="fas fa-users me-2 text-primary"),
                        html.Span("Gestión de usuarios", className="fw-bold small text-uppercase text-muted"),
                    ], className="bg-white border-bottom py-2 px-4"),
                    dbc.CardBody(
                        html.Div(id='admin-users-table-container', style={"minHeight": "120px"}),
                        className="p-0",
                    ),
                ], className="border-0 shadow-sm rounded-4 mb-4 overflow-hidden"),

                # Formulario añadir usuario
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="fas fa-user-plus me-2 text-primary"),
                        html.Span("Añadir usuario", className="fw-bold small text-uppercase text-muted"),
                    ], className="bg-white border-bottom py-2 px-4"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Usuario", className="fw-bold small text-muted mb-1"),
                                dbc.Input(
                                    id='admin-new-username',
                                    placeholder="nombre de usuario",
                                    type="text",
                                    className="rounded-3",
                                ),
                            ], xs=12, md=4),
                            dbc.Col([
                                dbc.Label("Contraseña", className="fw-bold small text-muted mb-1"),
                                dbc.Input(
                                    id='admin-new-password',
                                    placeholder="contraseña",
                                    type="password",
                                    className="rounded-3",
                                ),
                            ], xs=12, md=4),
                            dbc.Col([
                                dbc.Label("Rol", className="fw-bold small text-muted mb-1"),
                                dbc.Select(
                                    id='admin-new-role',
                                    options=[
                                        {"label": "Usuario", "value": "user"},
                                        {"label": "Administrador", "value": "admin"},
                                    ],
                                    value="user",
                                    className="rounded-3",
                                ),
                            ], xs=12, md=2),
                            dbc.Col([
                                dbc.Label(" ", className="fw-bold small text-muted mb-1 d-block"),
                                dbc.Button(
                                    [html.I(className="fas fa-plus me-2"), "Añadir"],
                                    id='admin-add-user-btn', color="primary",
                                    className="rounded-3 w-100 fw-bold shadow-sm",
                                ),
                            ], xs=12, md=2),
                        ], className="g-3"),
                    ], className="p-4"),
                ], className="border-0 shadow-sm rounded-4 overflow-hidden"),
            ]),

            # ── Pestaña Árbol de ubicaciones ─────────────────────────────────
            dbc.Tab(label='Árbol de ubicaciones', tab_id='admin-tab-locs',
                    tab_style={"fontWeight": "600"}, children=[
                html.Br(),

                dbc.Alert(id='admin-locs-feedback', is_open=False, dismissable=True,
                          className="mb-4 rounded-3 border-0 shadow-sm"),

                html.Div(id='admin-locs-container', style={"minHeight": "200px"}),
            ]),

        ], className="mb-3"),
    ])
