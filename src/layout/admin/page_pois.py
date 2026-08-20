import dash_bootstrap_components as dbc
from dash import html


def build_page_pois():
    poi_form = html.Div(
        id="admin-poi-form-panel",
        style={"display": "none"},
        children=dbc.Card(
            [
                dbc.CardHeader(
                    [
                        html.I(className="fas fa-map-pin me-2 text-primary"),
                        html.Span(
                            id="admin-poi-modal-title",
                            children="Añadir POI",
                            className="fw-bold",
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
                                                {"label": "Competidor", "value": "competitor"},
                                                {"label": "Otro", "value": "otro"},
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
                    ],
                    className="p-4",
                ),
                dbc.CardFooter(
                    dbc.ButtonGroup(
                        [
                            dbc.Button(
                                [html.I(className="fas fa-save me-2"), "Guardar POI"],
                                id="admin-poi-modal-save",
                                color="primary",
                                className="rounded-start-3 fw-bold shadow-sm",
                            ),
                            dbc.Button(
                                [html.I(className="fas fa-times me-2"), "Cancelar"],
                                id="admin-poi-modal-cancel",
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
                    [html.I(className="fas fa-map-pin me-2 text-primary"), "POIs"],
                    className="mb-0 fw-bold",
                ),
                className="px-4 pt-4 pb-3 border-bottom",
                style={"background": "#fff"},
            ),
            dbc.Alert(
                id="admin-pois-feedback",
                is_open=False,
                dismissable=True,
                duration=5000,
                className="mx-4 mt-4 mb-0 rounded-3 border-0 shadow-sm",
            ),
            dbc.Card(
                dbc.CardBody(
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
                                                    html.I(className="fas fa-plus me-2"),
                                                    "Añadir POI",
                                                ],
                                                id="admin-poi-add-btn",
                                                color="primary",
                                                outline=True,
                                                className="rounded-start-3 fw-bold",
                                            ),
                                            dbc.Button(
                                                [
                                                    html.I(className="fas fa-satellite me-2"),
                                                    "Esri Places",
                                                ],
                                                id="admin-pois-sync-btn",
                                                color="success",
                                                outline=True,
                                                className="fw-bold",
                                            ),
                                            dbc.Button(
                                                [
                                                    html.I(className="fab fa-google me-2"),
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
                    className="p-3",
                ),
                className="border-0 shadow-sm rounded-4 mx-4 mt-4",
            ),
            poi_form,
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
                        html.Div(id="admin-pois-table", style={"minHeight": "120px"}),
                        className="p-0",
                    ),
                ],
                className="border-0 shadow-sm rounded-4 mx-4 mt-4 mb-5 overflow-hidden",
            ),
        ],
        className="flex-grow-1",
        style={"background": "#f7f7f5", "minHeight": "calc(100vh - 57px)"},
    )
