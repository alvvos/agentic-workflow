import pandas as pd
from datetime import datetime, timedelta
import dash
from dash import Output, Input, State, html, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from src.core.config import app
from src.core import data_master
from src.core.data_master import mapa_tiendas, mapa_zonas
from src.reporting.health_check import generar_panel_pm
from src.data_processing.data_radar import generar_tabla_auditoria
from src.models.anomalys import generar_panel_bi_completo
from src.db.queries import get_df_visitas


@app.callback(
    [Output("bi-dynamic-content", "children"), Output("bi-status-visor", "children"),
     Output("audit-results", "children"), Output("panel-ejecutivo-content", "children")],
    [Input("drop-locs", "value"), Input("tipo-fecha", "value"), Input("date-rango", "start_date"),
     Input("date-rango", "end_date"), Input("date-dia", "date"), Input("zonas-activas-combined", "data"),
     Input("bi-comparativa", "value"),
     Input("pm-ventana", "value"), Input("data-version", "data")],
    [State("session-id", "data")], prevent_initial_call=False
)
def master_reactive_analytics(locs, t_f, sd, ed, dia, zones_bi, comp, pm_ventana, _data_v, s_id):
    if not locs:
        return html.Div(), "Esperando selección de ubicación...", html.Div(), html.Div()

    df = get_df_visitas(locs)
    if df.empty:
        return html.Div(), "Sin datos. Sincroniza para descargar.", html.Div(), html.Div()

    df['Ubicación'] = df['location_id'].map(mapa_tiendas).fillna('Desconocida')
    df['Zona'] = df['zone_uuid'].map(mapa_zonas).fillna('SinNombre') if 'zone_uuid' in df.columns else 'SinNombre'

    informe_ejecutivo = generar_panel_pm(df, locs, [], ventana=pm_ventana or "semana")

    hoy = datetime.today().date()
    start = end = pd.to_datetime(hoy - timedelta(days=1))
    if t_f == "7d_rel":
        start, end = pd.to_datetime(hoy - timedelta(days=7)), pd.to_datetime(hoy - timedelta(days=1))
    elif t_f == "28d_rel":
        start, end = pd.to_datetime(hoy - timedelta(days=28)), pd.to_datetime(hoy - timedelta(days=1))
    elif t_f == "dia" and dia:
        start = end = pd.to_datetime(dia)
    elif t_f == "rango" and sd and ed:
        start, end = pd.to_datetime(sd), pd.to_datetime(ed)

    df_actual = df[(df['fecha'] >= start) & (df['fecha'] <= end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))].copy()
    if zones_bi:
        df_actual = df_actual[df_actual['Zona'].isin(zones_bi)]

    df_hist = pd.DataFrame()
    if comp != 'none':
        off = {'wow': 7, 'mom': 28, 'yoy': 365}[comp]
        s_h, e_h = start - pd.Timedelta(days=off), end - pd.Timedelta(days=off)
        df_hist = df[(df['fecha'] >= s_h) & (df['fecha'] <= e_h + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))].copy()
        if zones_bi:
            df_hist = df_hist[df_hist['Zona'].isin(zones_bi)]

    df_bi = df_actual.copy()
    df_bi_hist = df_hist.copy()
    if 'dwell_time' in df_bi.columns:
        df_bi['dwell_time'] /= 60.0
    if not df_bi_hist.empty and 'dwell_time' in df_bi_hist.columns:
        df_bi_hist['dwell_time'] /= 60.0

    comparativa_txt = {'wow': 'vs. Semana Anterior', 'mom': 'vs. Mes Anterior', 'yoy': 'vs. Año Anterior', 'none': ''}[comp]
    visor_children = [
        html.Span([html.I(className="fas fa-calendar-day me-2"), f"{start.strftime('%d %b')} - {end.strftime('%d %b')}"], className="badge bg-white text-primary me-2 shadow-sm fs-6"),
        html.Span([html.I(className="fas fa-layer-group me-2"), f"{len(zones_bi) if zones_bi else 'Todas las'} Zonas"], className="badge bg-white text-secondary me-2 shadow-sm fs-6"),
    ]
    if comparativa_txt:
        visor_children.append(html.Span(comparativa_txt, className="badge bg-primary text-white shadow-sm fs-6"))
    visor = html.Div(visor_children)

    child_zone_names: set = set()
    for l in (locs or []):
        for children in data_master.mapa_hijos_por_zona.get(l, {}).values():
            child_zone_names.update(z['label'] for z in children)
    bi_content = generar_panel_bi_completo(df_bi, df_bi_hist, comp, child_zones=child_zone_names)
    audit_content = generar_tabla_auditoria(df_actual) if not df_actual.empty else dbc.Alert("No hay datos para el radar en estas fechas.", color="info", className="rounded-4")

    return bi_content, visor, audit_content, informe_ejecutivo


@app.callback(
    Output("modal-bi-fullscreen", "is_open"), Output("modal-bi-graph", "figure"), Output("modal-bi-title", "children"),
    Input({"type": "btn-expand", "index": dash.ALL}, "n_clicks"), State({"type": "bi-graph", "index": dash.ALL}, "figure"),
    State({"type": "bi-graph", "index": dash.ALL}, "id"), prevent_initial_call=True
)
def expandir_grafico(n_clicks_list, figures, ids):
    if not ctx.triggered:
        return dash.no_update
    trigger_val = ctx.triggered[0]['value']
    if not trigger_val:
        return dash.no_update
    trigger_id = ctx.triggered_id
    if not trigger_id:
        return dash.no_update
    index_buscado = trigger_id['index']
    for fig, item_id in zip(figures, ids):
        if item_id['index'] == index_buscado:
            titulo = fig['layout']['title']['text'] if 'title' in fig['layout'] else "Análisis en detalle"
            fig_copy = go.Figure(fig)
            fig_copy.update_layout(height=None, margin=dict(t=50, b=80, l=40, r=20))
            return True, fig_copy, titulo
    return dash.no_update
