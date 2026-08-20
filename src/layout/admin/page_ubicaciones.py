import dash_bootstrap_components as dbc
from dash import html


def build_page_ubicaciones():
    zone_editor = html.Div(
        id="admin-zone-editor-panel",
        style={"display": "none"},
        children=dbc.Card(
            [
                dbc.CardHeader(
                    [
                        html.I(className="fas fa-sitemap me-2 text-primary"),
                        html.Span(id="admin-zone-modal-title", className="fw-bold"),
                    ],
                    className="bg-white border-bottom py-2 px-4",
                ),
                dbc.CardBody(
                    html.Div(id="admin-zone-modal-body", style={"minHeight": "120px"}),
                    className="p-0",
                ),
                dbc.CardFooter(
                    dbc.ButtonGroup(
                        [
                            dbc.Button(
                                [html.I(className="fas fa-save me-2"), "Publicar jerarquía"],
                                id="admin-zone-modal-save",
                                color="primary",
                                className="rounded-start-3 fw-bold shadow-sm",
                            ),
                            dbc.Button(
                                [html.I(className="fas fa-times me-2"), "Cerrar"],
                                id="admin-zone-modal-cancel",
                                color="secondary",
                                outline=True,
                                className="rounded-end-3",
                            ),
                        ]
                    ),
                    className="bg-white border-top py-3 px-4",
                ),
            ],
            className="border-0 shadow-sm rounded-4 mx-4 mt-4 overflow-hidden",
        ),
    )

    return html.Div(
        [
            html.Div(
                html.H4(
                    [html.I(className="fas fa-building me-2 text-primary"), "Ubicaciones"],
                    className="mb-0 fw-bold",
                ),
                className="px-4 pt-4 pb-3 border-bottom",
                style={"background": "#fff"},
            ),
            dbc.Alert(
                id="admin-locs-feedback",
                is_open=False,
                dismissable=True,
                className="mx-4 mt-4 rounded-3 border-0 shadow-sm",
            ),
            zone_editor,
            html.Div(
                id="admin-locs-container",
                className="px-4 pt-4 pb-5",
                style={"minHeight": "200px"},
            ),
        ],
        className="flex-grow-1",
        style={"background": "#f7f7f5", "minHeight": "calc(100vh - 57px)"},
    )
