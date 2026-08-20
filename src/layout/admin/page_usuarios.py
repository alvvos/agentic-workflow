import dash_bootstrap_components as dbc
from dash import html


def build_page_usuarios():
    delete_confirm = html.Div(
        id="admin-delete-confirm-area",
        style={"display": "none"},
        children=dbc.Card(
            [
                dbc.CardBody(
                    [
                        html.Div(id="admin-delete-modal-body", className="mb-3 fw-semibold"),
                        dbc.ButtonGroup(
                            [
                                dbc.Button(
                                    [html.I(className="fas fa-trash-alt me-2"), "Confirmar"],
                                    id="admin-confirm-delete-btn",
                                    color="danger",
                                    className="rounded-start-3 fw-bold",
                                ),
                                dbc.Button(
                                    [html.I(className="fas fa-times me-2"), "Cancelar"],
                                    id="admin-cancel-delete-btn",
                                    color="secondary",
                                    outline=True,
                                    className="rounded-end-3",
                                ),
                            ]
                        ),
                    ],
                    className="p-4",
                ),
            ],
            className="border border-danger border-opacity-25 shadow-sm rounded-4 mx-4 mt-4 overflow-hidden",
            style={"background": "#fff8f8"},
        ),
    )

    access_panel = html.Div(
        id="admin-access-panel",
        style={"display": "none"},
        children=dbc.Card(
            [
                dbc.CardHeader(
                    [
                        html.I(className="fas fa-key me-2 text-info"),
                        html.Span(id="admin-access-modal-title", className="fw-bold"),
                    ],
                    className="bg-white border-bottom py-2 px-4",
                ),
                dbc.CardBody(
                    [
                        html.P(id="admin-access-modal-info", className="text-muted small mb-3"),
                        dbc.Checklist(
                            id="admin-access-checklist",
                            options=[],
                            value=[],
                            input_class_name="me-2",
                        ),
                        dbc.ButtonGroup(
                            [
                                dbc.Button(
                                    [html.I(className="fas fa-save me-2"), "Guardar acceso"],
                                    id="admin-access-modal-save",
                                    color="primary",
                                    className="rounded-start-3 fw-bold shadow-sm",
                                ),
                                dbc.Button(
                                    [html.I(className="fas fa-times me-2"), "Cancelar"],
                                    id="admin-access-modal-cancel",
                                    color="secondary",
                                    outline=True,
                                    className="rounded-end-3",
                                ),
                            ],
                            className="mt-3",
                        ),
                    ],
                    className="p-4",
                ),
            ],
            className="border-0 shadow-sm rounded-4 mx-4 mt-4 overflow-hidden",
        ),
    )

    add_user_form = dbc.Card(
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
                                    dbc.Label("Rol", className="fw-bold small text-muted mb-1"),
                                    dbc.Select(
                                        id="admin-new-role",
                                        options=[
                                            {"label": "Usuario", "value": "user"},
                                            {"label": "Administrador", "value": "admin"},
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
                                        [html.I(className="fas fa-plus me-2"), "Añadir"],
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
        className="border-0 shadow-sm rounded-4 mx-4 overflow-hidden",
    )

    return html.Div(
        [
            html.Div(
                html.H4(
                    [html.I(className="fas fa-users me-2 text-primary"), "Usuarios"],
                    className="mb-0 fw-bold",
                ),
                className="px-4 pt-4 pb-3 border-bottom",
                style={"background": "#fff"},
            ),
            dbc.Alert(
                id="admin-users-feedback",
                is_open=False,
                dismissable=True,
                className="mx-4 mt-4 rounded-3 border-0 shadow-sm",
            ),
            delete_confirm,
            access_panel,
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
                className="border-0 shadow-sm rounded-4 mx-4 mt-4 mb-4 overflow-hidden",
            ),
            add_user_form,
        ],
        className="flex-grow-1 pb-5",
        style={"background": "#f7f7f5", "minHeight": "calc(100vh - 57px)"},
    )
