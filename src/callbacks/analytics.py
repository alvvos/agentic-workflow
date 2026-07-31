from datetime import datetime, timedelta

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, ctx, html

from src.core import data_master
from src.core.config import app
from src.core.data_master import mapa_tiendas, mapa_zonas
from src.core.org_branding import get_branding_from_locs
from src.data_processing.data_radar import generar_tabla_auditoria
from src.db.queries import get_df_visitas
from src.models.anomalys import generar_panel_bi_completo
from src.reporting.health_check import generar_panel_pm


@app.callback(
    [
        Output("bi-dynamic-content", "children"),
        Output("bi-status-visor", "children"),
        Output("audit-results", "children"),
        Output("panel-ejecutivo-content", "children"),
    ],
    [Input("loc-loaded", "data")],
    [
        State("tipo-fecha", "value"),
        State("date-rango", "start_date"),
        State("date-rango", "end_date"),
        State("date-dia", "date"),
        State("zonas-activas-combined", "data"),
        State("bi-comparativa", "value"),
        State("pm-ventana", "value"),
        State("data-version", "data"),
        State("session-id", "data"),
    ],
    prevent_initial_call=True,
)
def master_reactive_analytics(locs, t_f, sd, ed, dia, zones_bi, comp, pm_ventana, _data_v, s_id):
    if not locs:
        return html.Div(), "Esperando selección de ubicación...", html.Div(), html.Div()
    if isinstance(locs, str):
        locs = [locs]

    df = get_df_visitas(locs)
    if df.empty:
        return html.Div(), "Sin datos. Sincroniza para descargar.", html.Div(), html.Div()

    df["Ubicación"] = df["location_id"].map(mapa_tiendas).fillna("Desconocida")
    df["Zona"] = (
        df["zona_id"].map(mapa_zonas).fillna("SinNombre")
        if "zona_id" in df.columns
        else "SinNombre"
    )

    informe_ejecutivo = generar_panel_pm(df, locs, [], ventana=pm_ventana or "semana")

    hoy = datetime.today().date()
    start = end = pd.to_datetime(hoy - timedelta(days=1))
    if t_f == "7d_rel":
        start, end = pd.to_datetime(hoy - timedelta(days=7)), pd.to_datetime(
            hoy - timedelta(days=1)
        )
    elif t_f == "28d_rel":
        start, end = pd.to_datetime(hoy - timedelta(days=28)), pd.to_datetime(
            hoy - timedelta(days=1)
        )
    elif t_f == "dia" and dia:
        start = end = pd.to_datetime(dia)
    elif t_f == "rango" and sd and ed:
        start, end = pd.to_datetime(sd), pd.to_datetime(ed)

    df_actual = df[
        (df["fecha"] >= start)
        & (df["fecha"] <= end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
    ].copy()
    if zones_bi:
        df_actual = df_actual[df_actual["Zona"].isin(zones_bi)]

    df_hist = pd.DataFrame()
    if comp != "none":
        off = {"wow": 7, "mom": 28, "yoy": 365}[comp]
        s_h, e_h = start - pd.Timedelta(days=off), end - pd.Timedelta(days=off)
        df_hist = df[
            (df["fecha"] >= s_h)
            & (df["fecha"] <= e_h + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
        ].copy()
        if zones_bi:
            df_hist = df_hist[df_hist["Zona"].isin(zones_bi)]

    df_bi = df_actual.copy()
    df_bi_hist = df_hist.copy()
    if "dwell_time" in df_bi.columns:
        df_bi["dwell_time"] /= 60.0
    if not df_bi_hist.empty and "dwell_time" in df_bi_hist.columns:
        df_bi_hist["dwell_time"] /= 60.0

    _comp_lbl = {
        "wow": "vs. 7 días anteriores",
        "mom": "vs. 28 días anteriores",
        "yoy": "vs. año anterior",
        "none": "",
    }[comp]
    _primary = get_branding_from_locs(locs).primary

    def _darken(h, f=0.75):
        c = h.lstrip("#")
        return f"#{int(int(c[0:2], 16) * f):02x}{int(int(c[2:4], 16) * f):02x}{int(int(c[4:6], 16) * f):02x}"

    _loc_nombre = (
        mapa_tiendas.get(locs[0], locs[0]) if len(locs) == 1 else f"{len(locs)} ubicaciones"
    )
    _date_lbl = f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"
    _zones_lbl = (
        f"{len(zones_bi)} zona{'s' if len(zones_bi) != 1 else ''}"
        if zones_bi
        else "Todas las zonas"
    )
    _meta_parts = [_zones_lbl] + ([_comp_lbl] if _comp_lbl else [])

    visor = dbc.Card(
        dbc.CardBody(
            html.Div(
                [
                    html.P(
                        "ANALÍTICA",
                        className="mb-1 text-uppercase fw-bold",
                        style={
                            "fontSize": "0.6rem",
                            "letterSpacing": "1.5px",
                            "color": "rgba(255,255,255,0.72)",
                        },
                    ),
                    html.H4(
                        _loc_nombre,
                        className="fw-bold mb-1",
                        style={"color": "white", "fontSize": "1.35rem"},
                    ),
                    html.P(
                        _date_lbl,
                        className="mb-0",
                        style={
                            "fontSize": "0.82rem",
                            "color": "rgba(255,255,255,0.85)",
                            "fontWeight": "500",
                        },
                    ),
                    html.P(
                        " · ".join(_meta_parts),
                        className="mb-0 mt-1",
                        style={"fontSize": "0.75rem", "color": "rgba(255,255,255,0.65)"},
                    ),
                ],
                style={"marginTop": "auto"},
            ),
            style={
                "display": "flex",
                "flexDirection": "column",
                "padding": "20px 24px",
                "minHeight": "130px",
            },
        ),
        className="border-0 rounded-4 mb-4 shadow",
        style={"background": f"linear-gradient(135deg, {_primary} 0%, {_darken(_primary)} 100%)"},
    )

    child_zone_names: set = set()
    funnel_step_map: dict[str, int] = {}
    for loc in locs or []:
        for children in data_master.mapa_hijos_por_zona.get(loc, {}).values():
            child_zone_names.update(z["label"] for z in children)
        for z in data_master.mapa_zonas_por_loc.get(loc, []):
            if z.get("funnel_step") is not None:
                funnel_step_map[z["value"]] = z["funnel_step"]
    bi_content = generar_panel_bi_completo(
        df_bi, df_bi_hist, comp, child_zones=child_zone_names, funnel_step_map=funnel_step_map
    )
    audit_content = (
        generar_tabla_auditoria(df_actual)
        if not df_actual.empty
        else dbc.Alert(
            "No hay datos para el radar en estas fechas.", color="info", className="rounded-4"
        )
    )

    return bi_content, visor, audit_content, informe_ejecutivo


@app.callback(
    Output("modal-bi-fullscreen", "is_open"),
    Output("modal-bi-graph", "figure"),
    Output("modal-bi-title", "children"),
    Input({"type": "btn-expand", "index": dash.ALL}, "n_clicks"),
    State({"type": "bi-graph", "index": dash.ALL}, "figure"),
    State({"type": "bi-graph", "index": dash.ALL}, "id"),
    prevent_initial_call=True,
)
def expandir_grafico(n_clicks_list, figures, ids):
    if not ctx.triggered:
        return dash.no_update
    trigger_val = ctx.triggered[0]["value"]
    if not trigger_val:
        return dash.no_update
    trigger_id = ctx.triggered_id
    if not trigger_id:
        return dash.no_update
    index_buscado = trigger_id["index"]
    for fig, item_id in zip(figures, ids):
        if item_id["index"] == index_buscado:
            titulo = (
                fig["layout"]["title"]["text"]
                if "title" in fig["layout"]
                else "Análisis en detalle"
            )
            fig_copy = go.Figure(fig)
            fig_copy.update_layout(height=None, margin=dict(t=50, b=80, l=40, r=20))
            return True, fig_copy, titulo
    return dash.no_update
