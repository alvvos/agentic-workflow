from datetime import date, timedelta

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html, no_update

from src.core.data_master import mapa_tiendas
from src.db.queries import get_df_enriquecido, get_zones_for_loc
from src.services.ml_predictivo import ejecutar_auditoria_predictiva

mapa_zonas_por_loc = {}
mapa_tiendas_ml = {}
mapa_zonas_ml = {}


def _rebuild_ml_maps():
    mapa_zonas_por_loc.clear()
    mapa_tiendas_ml.clear()
    mapa_zonas_ml.clear()
    for loc_uuid, nombre in mapa_tiendas.items():
        zonas = [
            {"label": z["nombre"], "value": z["zona_id"]}
            for z in get_zones_for_loc(loc_uuid)
            if not z["oculta"]
        ]
        mapa_zonas_por_loc[loc_uuid] = zonas
        mapa_tiendas_ml[loc_uuid] = nombre
        for z in get_zones_for_loc(loc_uuid):
            if not z["oculta"]:
                mapa_zonas_ml[z["zona_id"]] = z["nombre"]


try:
    _rebuild_ml_maps()
except Exception:
    pass


def generar_panel_ml():
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H4(
                                [
                                    html.I(className="fas fa-brain me-2 text-primary"),
                                    "Forecasting",
                                    dbc.Badge(
                                        "Beta",
                                        color="warning",
                                        pill=True,
                                        className="ms-2 align-middle small fw-normal",
                                    ),
                                ],
                                className="fw-bold mb-1 text-dark",
                            ),
                            html.P(
                                "Entrena un modelo de forecasting al instante para predecir el flujo futuro de visitantes basado en el histórico sincronizado.",
                                className="text-muted small",
                            ),
                        ],
                        width=12,
                    )
                ],
                className="mb-4",
            ),
            dbc.Card(
                [
                    dbc.CardBody(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            html.Label(
                                                "Zona a predecir:",
                                                className="fw-bold text-secondary small text-uppercase mb-1",
                                            ),
                                            dcc.Dropdown(
                                                id="ml-drop-zone",
                                                clearable=False,
                                                className="shadow-sm",
                                                placeholder="Esperando ubicación global...",
                                            ),
                                        ],
                                        xs=12,
                                        md=4,
                                        className="mb-3 mb-md-0",
                                    ),
                                    dbc.Col(
                                        [
                                            html.Label(
                                                "Fecha de inicio (Simulación):",
                                                className="fw-bold text-secondary small text-uppercase mb-1",
                                            ),
                                            dcc.DatePickerSingle(
                                                id="ml-date-falso",
                                                date=date(2026, 3, 1),
                                                display_format="YYYY-MM-DD",
                                                className="w-100 shadow-sm",
                                            ),
                                        ],
                                        xs=12,
                                        md=4,
                                        className="mb-3 mb-md-0",
                                    ),
                                    dbc.Col(
                                        [
                                            html.Label(
                                                "Horizonte a futuro (Días):",
                                                className="fw-bold text-secondary small text-uppercase mb-1",
                                            ),
                                            dcc.Slider(
                                                id="ml-slider-horiz",
                                                min=1,
                                                max=14,
                                                step=1,
                                                value=7,
                                                marks={i: f"{i}d" for i in [1, 3, 7, 10, 14]},
                                                className="mt-2",
                                            ),
                                        ],
                                        xs=12,
                                        md=4,
                                    ),
                                ],
                                className="align-items-center mb-4",
                            ),
                            dbc.Button(
                                [html.I(className="fas fa-cogs me-2"), "ENTRENAR Y EVALUAR MODELO"],
                                id="ml-btn-run",
                                color="primary",
                                className="w-100 fw-bold rounded-3 shadow-sm mb-2",
                            ),
                            html.Div(
                                id="ml-error-msg",
                                className="text-danger fw-bold mt-2 text-center small",
                            ),
                        ]
                    )
                ],
                className="border-0 shadow-sm rounded-4 bg-light mb-4",
            ),
            dcc.Loading(
                html.Div(
                    [
                        dbc.Row(
                            [
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody(
                                            [
                                                html.H6(
                                                    "Precisión (Accuracy)",
                                                    className="text-muted small text-uppercase fw-bold",
                                                ),
                                                html.H3(
                                                    id="ml-card-acc",
                                                    children="-",
                                                    className="text-success fw-bold mb-0",
                                                ),
                                            ]
                                        ),
                                        className="border-0 shadow-sm rounded-4 text-center",
                                    ),
                                    xs=6,
                                    md=3,
                                    className="mb-3 mb-md-0",
                                ),
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody(
                                            [
                                                html.H6(
                                                    "Error Medio (MAE)",
                                                    className="text-muted small text-uppercase fw-bold",
                                                ),
                                                html.H3(
                                                    id="ml-card-mae",
                                                    children="-",
                                                    className="text-warning fw-bold mb-0",
                                                ),
                                            ]
                                        ),
                                        className="border-0 shadow-sm rounded-4 text-center",
                                    ),
                                    xs=6,
                                    md=3,
                                    className="mb-3 mb-md-0",
                                ),
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody(
                                            [
                                                html.H6(
                                                    "Desviación (WMAPE)",
                                                    className="text-muted small text-uppercase fw-bold",
                                                ),
                                                html.H3(
                                                    id="ml-card-wmape",
                                                    children="-",
                                                    className="text-danger fw-bold mb-0",
                                                ),
                                            ]
                                        ),
                                        className="border-0 shadow-sm rounded-4 text-center",
                                    ),
                                    xs=6,
                                    md=3,
                                    className="mb-3 mb-md-0",
                                ),
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody(
                                            [
                                                html.H6(
                                                    "Iteraciones (Trees)",
                                                    className="text-muted small text-uppercase fw-bold",
                                                ),
                                                html.H3(
                                                    id="ml-card-iter",
                                                    children="-",
                                                    className="text-info fw-bold mb-0",
                                                ),
                                            ]
                                        ),
                                        className="border-0 shadow-sm rounded-4 text-center",
                                    ),
                                    xs=6,
                                    md=3,
                                ),
                            ],
                            className="mb-4",
                        ),
                        dbc.Card(
                            [
                                dbc.CardBody(
                                    [
                                        dcc.Graph(
                                            id="ml-graph-res",
                                            style={"height": "400px"},
                                            config={"displayModeBar": False},
                                        )
                                    ],
                                    className="p-2",
                                )
                            ],
                            className="border-0 shadow-sm rounded-4 bg-white",
                        ),
                    ],
                    style={"minHeight": "120px"},
                ),
                custom_spinner=html.Div(
                    [
                        dbc.Spinner(color="primary", size="lg"),
                        html.H5("Entrenando modelo...", className="ms-3 mb-0 text-primary fw-bold"),
                    ],
                    className="d-flex align-items-center justify-content-center loading-spinner-body",
                    style={"minHeight": "120px"},
                ),
                delay_show=100,
                delay_hide=500,
            ),
            html.Hr(className="text-muted my-5"),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H4(
                                [
                                    html.I(className="fas fa-calendar-day me-2 text-warning"),
                                    "Proyección para Mañana",
                                    dbc.Badge(
                                        "Beta",
                                        color="warning",
                                        pill=True,
                                        className="ms-2 align-middle small fw-normal",
                                    ),
                                ],
                                className="fw-bold mb-1 text-dark",
                            ),
                            html.P(
                                "Entrena el modelo sobre todos los datos históricos disponibles y proyecta las visitas del día siguiente para cada zona.",
                                className="text-muted small",
                            ),
                        ],
                        width=12,
                    )
                ],
                className="mb-4",
            ),
            dbc.Card(
                [
                    dbc.CardBody(
                        [
                            dbc.Button(
                                [
                                    html.I(className="fas fa-magic me-2"),
                                    "CALCULAR PROYECCIÓN DE MAÑANA",
                                ],
                                id="ml-btn-manana",
                                color="warning",
                                className="w-100 fw-bold rounded-3 shadow-sm mb-2",
                            ),
                            html.Div(
                                id="ml-manana-msg",
                                className="text-danger fw-bold mt-2 text-center small",
                            ),
                        ]
                    )
                ],
                className="border-0 shadow-sm rounded-4 bg-light mb-4",
            ),
            dcc.Loading(
                html.Div(id="ml-forecast-manana", style={"minHeight": "60px"}),
                custom_spinner=html.Div(
                    [
                        dbc.Spinner(color="warning", size="lg"),
                        html.H5(
                            "Calculando proyección...",
                            className="ms-3 mb-0 fw-bold",
                            style={"color": "#e67e22"},
                        ),
                    ],
                    className="d-flex align-items-center justify-content-center loading-spinner-body",
                    style={"minHeight": "60px"},
                ),
                delay_show=100,
                delay_hide=500,
            ),
        ],
        className="p-2",
    )


@callback(
    [Output("ml-drop-zone", "options"), Output("ml-drop-zone", "value")],
    [Input("drop-locs", "value")],
)
def filtrar_zonas_desde_global(locs):
    if not locs:
        return [], None
    zonas_combinadas = []
    for loc in locs:
        zonas_combinadas.extend(mapa_zonas_por_loc.get(loc, []))
    return zonas_combinadas, zonas_combinadas[0]["value"] if zonas_combinadas else None


@callback(
    [
        Output("ml-card-acc", "children"),
        Output("ml-card-mae", "children"),
        Output("ml-card-wmape", "children"),
        Output("ml-card-iter", "children"),
        Output("ml-graph-res", "figure"),
        Output("ml-error-msg", "children"),
    ],
    [Input("ml-btn-run", "n_clicks")],
    [
        State("drop-locs", "value"),
        State("ml-drop-zone", "value"),
        State("ml-date-falso", "date"),
        State("ml-slider-horiz", "value"),
        State("session-id", "data"),
    ],
    prevent_initial_call=True,
    running=[
        (Output("modal-ml-loading", "is_open"), True, False),
        (Output("modal-ml-label", "children"), "Entrenando modelo…", "Entrenando modelo…"),
        (Output("ml-btn-run", "disabled"), True, False),
    ],
)
def ejecutar_auditoria(n, locs, zone, fecha, horiz, session_id):
    if n is None:
        return (
            no_update,
            no_update,
            no_update,
            no_update,
            go.Figure().update_layout(template="plotly_white"),
            "",
        )
    if not locs or not zone:
        return (
            "-",
            "-",
            "-",
            "-",
            go.Figure(),
            "Aviso: Selecciona una ubicación en el filtro global (izquierda) y una zona.",
        )
    if not session_id:
        return (
            "-",
            "-",
            "-",
            "-",
            go.Figure(),
            "Error de sesión: No se puede identificar el usuario.",
        )

    loc_principal = locs[0]

    try:
        # Prefer DuckDB; fall back to session CSV
        df_e = get_df_enriquecido(loc_principal, session_id=session_id)
        if df_e.empty:
            return (
                "-",
                "-",
                "-",
                "-",
                go.Figure(),
                "Error: Sincroniza los datos desde el panel principal antes de usar el Motor Predictivo.",
            )
        res = ejecutar_auditoria_predictiva(df_e, loc_principal, zone, fecha, horiz)

        if "error" in res:
            return "-", "-", "-", "-", go.Figure(), f"Error en el motor ML: {res['error']}"

        g = res["grafica"]
        fechas = g["fechas"]

        fig = go.Figure()

        # Banda conforme al 90 % (se añade primero para que quede detrás)
        if g.get("lower") is not None and g.get("upper") is not None:
            fig.add_trace(
                go.Scatter(
                    x=fechas + fechas[::-1],
                    y=g["upper"] + g["lower"][::-1],
                    fill="toself",
                    fillcolor="rgba(39,174,96,0.10)",
                    line=dict(color="rgba(0,0,0,0)"),
                    hoverinfo="skip",
                    showlegend=True,
                    name="Intervalo 90 %",
                )
            )

        fig.add_trace(
            go.Scatter(
                x=fechas,
                y=g["reales"],
                name="Datos Reales",
                mode="lines+markers",
                line=dict(color="#bdc3c7", width=2),
                marker=dict(size=6, color="#7f8c8d"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=fechas,
                y=g["predichos"],
                name="Predicción del Algoritmo",
                mode="lines+markers",
                line=dict(color="#27ae60", width=3, dash="dot", shape="spline"),
                marker=dict(size=8, symbol="diamond", color="#2ecc71"),
            )
        )

        fig.update_layout(
            title=dict(
                text="Proyección Predictiva vs Datos Reales",
                font=dict(size=16, color="#2c3e50", family="Arial, sans-serif"),
            ),
            template="plotly_white",
            margin=dict(l=40, r=20, t=50, b=40),
            legend=dict(orientation="h", y=1.1, x=0.5, xanchor="center"),
            hovermode="x unified",
            plot_bgcolor="white",
        )
        fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
        fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0", rangemode="tozero")

        m = res["metricas"]

        acc = f"{m['accuracy']}%" if m["accuracy"] != "N/A" else "N/A"
        mae = f"{int(m['mae'])} vis." if m["mae"] != "N/A" else "N/A"
        wmape = f"{m['wmape_pct']}%" if m["wmape_pct"] != "N/A" else "N/A"

        return acc, mae, wmape, str(m["arboles_optimos"]), fig, ""

    except Exception as e:
        return "-", "-", "-", "-", go.Figure(), f"Error crítico durante el entrenamiento: {str(e)}"


@callback(
    [Output("ml-forecast-manana", "children"), Output("ml-manana-msg", "children")],
    [Input("ml-btn-manana", "n_clicks")],
    [State("drop-locs", "value"), State("session-id", "data")],
    prevent_initial_call=True,
    running=[
        (Output("modal-ml-loading", "is_open"), True, False),
        (
            Output("modal-ml-label", "children"),
            "Calculando proyección de mañana…",
            "Calculando proyección de mañana…",
        ),
        (Output("ml-btn-manana", "disabled"), True, False),
    ],
)
def ejecutar_forecast_manana(n, locs, session_id):
    if n is None:
        return no_update, ""
    if not locs:
        return no_update, "Selecciona una ubicación en el filtro global antes de calcular."
    if not session_id:
        return no_update, "Error de sesión."

    try:
        zona_cards = []
        ultima_fecha_global = None
        for loc_uuid in locs or []:
            df_e = get_df_enriquecido(loc_uuid, session_id=session_id)
            if df_e.empty:
                continue
            max_fecha = pd.to_datetime(df_e["fecha"]).max()
            if ultima_fecha_global is None or max_fecha > ultima_fecha_global:
                ultima_fecha_global = max_fecha
            falso_hoy = (max_fecha + timedelta(days=1)).strftime("%Y-%m-%d")
            loc_nombre = mapa_tiendas_ml.get(loc_uuid, loc_uuid)
            for zona_info in mapa_zonas_por_loc.get(loc_uuid, []):
                zone_uuid = zona_info["value"]
                zona_nombre = mapa_zonas_ml.get(zone_uuid, zona_info["label"])
                res = ejecutar_auditoria_predictiva(
                    df_e, loc_uuid, zone_uuid, falso_hoy, horizonte_dias=1
                )
                if res.get("status") != "success":
                    continue
                pred = int(res["grafica"]["predichos"][0])
                zona_cards.append(
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Small(loc_nombre, className="text-muted d-block mb-1"),
                                    html.H6(
                                        zona_nombre, className="fw-bold small text-uppercase mb-1"
                                    ),
                                    html.H3(f"{pred:,}", className="fw-bold text-dark mb-0"),
                                    html.Small("visitas proyectadas", className="text-muted"),
                                ]
                            ),
                            className="border-0 shadow-sm rounded-4 text-center h-100",
                        ),
                        xs=6,
                        md=3,
                        className="mb-3",
                    )
                )

        if not zona_cards:
            return no_update, "No se pudieron generar proyecciones para las zonas seleccionadas."

        manana_dt = ultima_fecha_global + timedelta(days=1)
        dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        dia_txt = dias_es[manana_dt.dayofweek]

        return (
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className="fas fa-calendar-day me-2 text-warning"),
                            html.Span(
                                f"Proyección para el {manana_dt.strftime('%d/%m/%Y')} ({dia_txt})",
                                className="fw-bold text-dark",
                            ),
                            html.Small(
                                f" — día siguiente al último dato disponible ({ultima_fecha_global.strftime('%d/%m/%Y')})",
                                className="text-muted ms-2",
                            ),
                        ],
                        className="mb-3 fs-6",
                    ),
                    dbc.Row(zona_cards),
                ]
            ),
            "",
        )

    except Exception as e:
        return no_update, f"Error durante la proyección: {str(e)}"
