"""
Tab Informes — solo visible para rol admin.

Panel de generación de informes PDF por período y ubicación,
con configuración de envío automático por email.
"""

from datetime import date, timedelta

import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc, html, no_update

from src.core.config import app

_C_ACCENT = "#495057"
_C_DARK = "#2c3e50"
_C_MUTED = "#8492a6"
_C_BORDER = "#edf0f5"

_LABEL_STYLE = {
    "fontSize": "0.68rem",
    "fontWeight": "700",
    "letterSpacing": "0.6px",
    "color": _C_MUTED,
    "textTransform": "uppercase",
    "marginBottom": "6px",
}

_SECTION_HEADER_BAR = {
    "width": "3px",
    "height": "16px",
    "backgroundColor": _C_ACCENT,
    "borderRadius": "2px",
    "flexShrink": 0,
}

_SECTION_HEADER_TEXT = {
    "fontSize": "0.78rem",
    "fontWeight": "700",
    "letterSpacing": "0.8px",
    "textTransform": "uppercase",
    "color": _C_DARK,
}


def _section_label(text: str):
    return html.Div(text, style=_LABEL_STYLE)


def _section_header(text: str):
    return html.Div(
        [
            html.Div(style=_SECTION_HEADER_BAR),
            html.Span(text, style=_SECTION_HEADER_TEXT),
        ],
        className="d-flex align-items-center gap-2 mb-4",
    )


def build_tab_informes():
    hoy = date.today()
    semana_ini = hoy - timedelta(days=hoy.weekday() + 7)
    semana_fin = semana_ini + timedelta(days=6)

    content = html.Div(
        [
            # ── Cabecera ───────────────────────────────────────────────────────
            dbc.Row(
                dbc.Col(
                    [
                        html.H4("Informes", className="fw-bold mb-1 text-dark"),
                        html.P(
                            "Genera informes PDF por período a partir de la ubicación cargada.",
                            className="text-muted small mb-0",
                        ),
                    ]
                ),
                className="mb-4",
            ),
            # ── Formulario de generación ───────────────────────────────────────
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    _section_header("Configuración del informe"),
                                    _section_label("Tipo de período"),
                                    dbc.RadioItems(
                                        id="inf-tipo-periodo",
                                        options=[
                                            {"label": "Última semana completa", "value": "semana"},
                                            {"label": "Último mes completo", "value": "mes"},
                                            {"label": "Rango personalizado", "value": "rango"},
                                        ],
                                        value="semana",
                                        className="mb-3",
                                        style={"fontSize": "0.87rem"},
                                    ),
                                    html.Div(
                                        id="inf-rango-wrapper",
                                        style={"display": "none"},
                                        children=[
                                            _section_label("Rango"),
                                            dcc.DatePickerRange(
                                                id="inf-date-rango",
                                                start_date=semana_ini,
                                                end_date=semana_fin,
                                                max_date_allowed=hoy,
                                                initial_visible_month=semana_fin,
                                                display_format="YYYY-MM-DD",
                                                className="w-100 mb-3",
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        style={
                                            "borderTop": f"1px solid {_C_BORDER}",
                                            "margin": "16px 0 14px",
                                        }
                                    ),
                                    dbc.Button(
                                        [
                                            html.I(className="fas fa-file-pdf me-2"),
                                            "Generar informe PDF",
                                        ],
                                        id="inf-btn-generar",
                                        color="dark",
                                        outline=True,
                                        size="sm",
                                        className="w-100 fw-bold rounded-3",
                                    ),
                                    dcc.Download(id="inf-download-pdf"),
                                    html.Div(id="inf-status", className="mt-3"),
                                ],
                                style={"padding": "20px 18px"},
                            ),
                            className="border-0 shadow-sm rounded-4",
                        ),
                        xs=12,
                        lg=4,
                        xl=3,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    _section_header("Contenido del informe"),
                                    html.Div(
                                        id="inf-preview-content",
                                        children=_preview_placeholder(),
                                    ),
                                ],
                                style={"padding": "20px 18px"},
                            ),
                            className="border-0 shadow-sm rounded-4",
                            style={"minHeight": "340px"},
                        ),
                        xs=12,
                        lg=8,
                        xl=9,
                    ),
                ],
                className="g-3",
            ),
            # ── Envío automático ───────────────────────────────────────────────
            dbc.Row(
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                _section_header("Envío automático por email"),
                                # Estado actual (se rellena con callback)
                                html.Div(id="inf-schedule-status", className="mb-3"),
                                dbc.Row(
                                    [
                                        # Frecuencia
                                        dbc.Col(
                                            [
                                                _section_label("Frecuencia"),
                                                dbc.RadioItems(
                                                    id="inf-sched-tipo",
                                                    options=[
                                                        {
                                                            "label": "Semanal — cada lunes 08:00",
                                                            "value": "semanal",
                                                        },
                                                        {
                                                            "label": "Mensual — día 1 de cada mes",
                                                            "value": "mensual",
                                                        },
                                                        {
                                                            "label": "Fecha concreta",
                                                            "value": "fecha",
                                                        },
                                                    ],
                                                    value="semanal",
                                                    style={"fontSize": "0.87rem"},
                                                ),
                                                html.Div(
                                                    id="inf-sched-fecha-wrapper",
                                                    style={"display": "none"},
                                                    children=[
                                                        dcc.DatePickerSingle(
                                                            id="inf-sched-fecha",
                                                            min_date_allowed=date.today().isoformat(),
                                                            display_format="DD/MM/YYYY",
                                                            className="mt-2",
                                                        )
                                                    ],
                                                ),
                                            ],
                                            md=5,
                                        ),
                                        # Destinatarios
                                        dbc.Col(
                                            [
                                                _section_label(
                                                    "Destinatarios (separados por coma)"
                                                ),
                                                dbc.Input(
                                                    id="inf-sched-emails",
                                                    placeholder="email1@empresa.com, email2@empresa.com",
                                                    type="text",
                                                    size="sm",
                                                    className="mb-3",
                                                    style={"fontSize": "0.87rem"},
                                                ),
                                                dbc.Row(
                                                    [
                                                        dbc.Col(
                                                            dbc.Button(
                                                                [
                                                                    html.I(
                                                                        className="fas fa-clock me-2"
                                                                    ),
                                                                    "Guardar programación",
                                                                ],
                                                                id="inf-sched-btn-guardar",
                                                                color="dark",
                                                                outline=True,
                                                                size="sm",
                                                                className="w-100 fw-bold rounded-3",
                                                            ),
                                                            xs=8,
                                                        ),
                                                        dbc.Col(
                                                            dbc.Button(
                                                                html.I(className="fas fa-trash"),
                                                                id="inf-sched-btn-eliminar",
                                                                color="danger",
                                                                outline=True,
                                                                size="sm",
                                                                className="w-100 rounded-3",
                                                                title="Eliminar programación",
                                                            ),
                                                            xs=4,
                                                        ),
                                                    ],
                                                    className="g-2",
                                                ),
                                            ],
                                            md=7,
                                        ),
                                    ],
                                    className="g-3",
                                ),
                                html.Div(id="inf-sched-status", className="mt-3"),
                            ],
                            style={"padding": "20px 18px"},
                        ),
                        className="border-0 shadow-sm rounded-4",
                    )
                ),
                className="mt-3",
            ),
        ],
        className="p-3",
    )

    return dcc.Tab(
        label="Informes",
        value="tab-informes",
        className="fw-bold",
        children=[content],
    )


def _preview_placeholder():
    return html.Div(
        [
            html.I(
                className="fas fa-file-lines",
                style={"fontSize": "2.2rem", "color": "#ced4da"},
            ),
            html.P(
                "Selecciona un período y pulsa «Generar informe PDF».",
                className="text-muted mt-3 mb-1",
                style={"fontSize": "0.87rem"},
            ),
            html.P(
                "Resumen ejecutivo · tráfico diario · distribución semanal · "
                "análisis por zonas · insights clave.",
                className="text-muted",
                style={"fontSize": "0.78rem", "maxWidth": "360px", "margin": "0 auto"},
            ),
        ],
        className="d-flex flex-column align-items-center justify-content-center text-center",
        style={"minHeight": "260px"},
    )


def _preview_summary(period_label: str, loc_nombre: str, n_zonas: int) -> html.Div:
    sections = [
        ("fas fa-chart-line", "Resumen ejecutivo", "4 KPIs con variación vs. período anterior"),
        ("fas fa-calendar-days", "Tráfico diario", "Gráfico de líneas por zona"),
        ("fas fa-chart-bar", "Distribución semanal", "Media de visitas por día de semana"),
        (
            "fas fa-layer-group",
            "Análisis por zona",
            f"{n_zonas} zona{'s' if n_zonas != 1 else ''} incluidas",
        ),
        ("fas fa-lightbulb", "Insights clave", "Análisis automático del período"),
    ]
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        loc_nombre, className="fw-bold text-dark", style={"fontSize": "0.9rem"}
                    ),
                    html.Br(),
                    html.Span(period_label, className="text-muted", style={"fontSize": "0.8rem"}),
                ],
                className="mb-3 p-3 rounded-3",
                style={"background": "#f8f9fa", "borderLeft": f"3px solid {_C_ACCENT}"},
            ),
            *[
                html.Div(
                    [
                        html.I(
                            className=f"{icon} me-2",
                            style={"color": _C_ACCENT, "width": "14px"},
                        ),
                        html.Div(
                            [
                                html.Span(
                                    title, className="fw-bold", style={"fontSize": "0.83rem"}
                                ),
                                html.Span(
                                    f" — {desc}",
                                    className="text-muted",
                                    style={"fontSize": "0.78rem"},
                                ),
                            ]
                        ),
                    ],
                    className="d-flex align-items-start mb-2",
                )
                for icon, title, desc in sections
            ],
        ]
    )


def _schedule_status_badge(sched: dict | None) -> html.Div:
    if not sched:
        return html.Div(
            [
                html.I(className="fas fa-circle-xmark me-2 text-secondary"),
                html.Span("Sin programación activa", className="text-muted small"),
            ],
            className="d-flex align-items-center",
        )
    tipo_label = {
        "semanal": "Semanal · lunes 08:00",
        "mensual": "Mensual · día 1",
        "fecha": f"Fecha: {sched.get('fecha_concreta', '')}",
    }
    emails_str = ", ".join(sched.get("emails") or [])
    ultima = sched.get("ultima_ejecucion")
    ultima_txt = f" · último envío {ultima[:10]}" if ultima else ""
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="fas fa-circle-check me-2", style={"color": "#198754"}),
                    html.Span(
                        f"Activo — {tipo_label.get(sched['tipo_periodo'], sched['tipo_periodo'])}{ultima_txt}",
                        className="fw-bold small text-dark",
                    ),
                ],
                className="d-flex align-items-center mb-1",
            ),
            html.Div(
                [
                    html.I(className="fas fa-envelope me-2 text-muted"),
                    html.Span(emails_str, className="text-muted small"),
                ],
                className="d-flex align-items-center",
            ),
        ],
        className="p-2 rounded-3",
        style={"background": "#f0faf4", "borderLeft": "3px solid #198754"},
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────


@app.callback(
    Output("inf-rango-wrapper", "style"),
    Input("inf-tipo-periodo", "value"),
)
def toggle_rango(tipo):
    return {"display": "block"} if tipo == "rango" else {"display": "none"}


@app.callback(
    Output("inf-sched-fecha-wrapper", "style"),
    Input("inf-sched-tipo", "value"),
)
def toggle_sched_fecha(tipo):
    return {"display": "block"} if tipo == "fecha" else {"display": "none"}


@app.callback(
    Output("inf-schedule-status", "children"),
    Output("inf-sched-tipo", "value"),
    Output("inf-sched-emails", "value"),
    Output("inf-sched-fecha", "date"),
    Input("loc-loaded", "data"),
)
def load_schedule(locs):
    if not locs:
        return _schedule_status_badge(None), "semanal", "", None
    loc_uuid = locs[0] if isinstance(locs, list) else locs
    try:
        from src.db.queries import get_report_schedule

        sched = get_report_schedule(loc_uuid)
    except Exception:
        sched = None
    if not sched:
        return _schedule_status_badge(None), "semanal", "", None
    emails_str = ", ".join(sched.get("emails") or [])
    return (
        _schedule_status_badge(sched),
        sched["tipo_periodo"],
        emails_str,
        sched.get("fecha_concreta"),
    )


@app.callback(
    Output("inf-schedule-status", "children", allow_duplicate=True),
    Output("inf-sched-status", "children"),
    Input("inf-sched-btn-guardar", "n_clicks"),
    State("inf-sched-tipo", "value"),
    State("inf-sched-emails", "value"),
    State("inf-sched-fecha", "date"),
    State("loc-loaded", "data"),
    prevent_initial_call=True,
)
def guardar_schedule(n_clicks, tipo, emails_raw, fecha_concreta, locs):
    if not locs:
        return no_update, dbc.Alert(
            "Primero carga una ubicación.", color="warning", className="small py-2 rounded-3"
        )
    loc_uuid = locs[0] if isinstance(locs, list) else locs
    emails = [e.strip() for e in (emails_raw or "").split(",") if e.strip()]
    if not emails:
        return no_update, dbc.Alert(
            "Introduce al menos un email.", color="warning", className="small py-2 rounded-3"
        )
    if tipo == "fecha" and not fecha_concreta:
        return no_update, dbc.Alert(
            "Selecciona la fecha de envío.", color="warning", className="small py-2 rounded-3"
        )
    try:
        from src.db.queries import get_report_schedule, upsert_report_schedule

        upsert_report_schedule(loc_uuid, tipo, emails, fecha_concreta if tipo == "fecha" else None)
        sched = get_report_schedule(loc_uuid)
        return _schedule_status_badge(sched), dbc.Alert(
            [html.I(className="fas fa-circle-check me-2 text-success"), "Programación guardada."],
            color="light",
            className="small py-2 rounded-3",
            style={"borderLeft": "3px solid #198754"},
        )
    except Exception as exc:
        return no_update, dbc.Alert(
            f"Error: {exc}", color="danger", className="small py-2 rounded-3"
        )


@app.callback(
    Output("inf-schedule-status", "children", allow_duplicate=True),
    Output("inf-sched-status", "children", allow_duplicate=True),
    Input("inf-sched-btn-eliminar", "n_clicks"),
    State("loc-loaded", "data"),
    prevent_initial_call=True,
)
def eliminar_schedule(n_clicks, locs):
    if not locs:
        return no_update, no_update
    loc_uuid = locs[0] if isinstance(locs, list) else locs
    try:
        from src.db.queries import delete_report_schedule

        delete_report_schedule(loc_uuid)
        return _schedule_status_badge(None), dbc.Alert(
            [html.I(className="fas fa-trash me-2"), "Programación eliminada."],
            color="light",
            className="small py-2 rounded-3",
        )
    except Exception as exc:
        return no_update, dbc.Alert(
            f"Error: {exc}", color="danger", className="small py-2 rounded-3"
        )


@app.callback(
    Output("inf-download-pdf", "data"),
    Output("inf-status", "children"),
    Output("inf-preview-content", "children"),
    Input("inf-btn-generar", "n_clicks"),
    State("inf-tipo-periodo", "value"),
    State("inf-date-rango", "start_date"),
    State("inf-date-rango", "end_date"),
    State("loc-loaded", "data"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def generar_informe(n_clicks, tipo_periodo, rango_start, rango_end, locs, session_id):
    if not locs:
        return (
            no_update,
            dbc.Alert(
                "Primero carga una ubicación desde el panel lateral.",
                color="warning",
                className="small py-2 rounded-3",
            ),
            no_update,
        )

    loc_uuid = locs[0] if isinstance(locs, list) else locs

    hoy = date.today()
    if tipo_periodo == "semana":
        lunes_pasado = hoy - timedelta(days=hoy.weekday() + 7)
        date_from = lunes_pasado.isoformat()
        date_to = (lunes_pasado + timedelta(days=6)).isoformat()
    elif tipo_periodo == "mes":
        primer_dia_mes_act = hoy.replace(day=1)
        ultimo_mes_fin = primer_dia_mes_act - timedelta(days=1)
        date_from = ultimo_mes_fin.replace(day=1).isoformat()
        date_to = ultimo_mes_fin.isoformat()
    else:
        date_from = rango_start or (hoy - timedelta(days=7)).isoformat()
        date_to = min(rango_end or hoy.isoformat(), hoy.isoformat())

    from src.core.data_master import mapa_tiendas
    from src.db.queries import get_zones_for_loc
    from src.reporting.pdf_generator import _period_label

    loc_nombre = mapa_tiendas.get(loc_uuid, loc_uuid)
    n_zonas = len([z for z in get_zones_for_loc(loc_uuid) if not z.get("oculta")])
    period_lbl, *_ = _period_label(date_from, date_to, tipo_periodo)
    preview = _preview_summary(period_lbl, loc_nombre, n_zonas)

    try:
        from src.reporting.pdf_generator import generar_pdf_informe

        pdf_bytes = generar_pdf_informe(
            loc_uuid=loc_uuid,
            period=tipo_periodo,
            date_from=date_from,
            date_to=date_to,
            session_id=session_id or "",
        )

        import base64

        filename = f"informe_{loc_nombre.lower().replace(' ', '_')}_{date_from}_{date_to}.pdf"
        b64 = base64.b64encode(pdf_bytes).decode()
        download = dict(base64=True, content=b64, filename=filename, type="application/pdf")

        status_ok = dbc.Alert(
            [
                html.I(className="fas fa-circle-check me-2 text-success"),
                f"Listo: {filename}",
            ],
            color="light",
            className="small py-2 rounded-3",
            style={"borderLeft": "3px solid #198754"},
        )
        return download, status_ok, preview

    except Exception as exc:
        status_err = dbc.Alert(
            [html.I(className="fas fa-triangle-exclamation me-2"), f"Error al generar: {exc}"],
            color="danger",
            className="small py-2 rounded-3",
        )
        return no_update, status_err, preview
