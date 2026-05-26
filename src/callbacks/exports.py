import os
import io
import pandas as pd
from datetime import datetime, timedelta
import dash
from dash import Output, Input, State, dcc
import plotly.graph_objects as go
import flask

from src.core.config import app
from src.core.data_master import mapa_tiendas, mapa_zonas, mapa_orgs
from src.core.config import dias_semana_es, orden_dias
from src.core.utils import filtrar_dataframe_fechas
from src.reporting.generador_html import generar_reporte_html


@app.callback(
    Output("download-html-report", "data"), Output("error-msg-html", "children"),
    Input("btn-generar-html", "n_clicks"), State("drop-locs", "value"), State("tipo-fecha", "value"),
    State("date-rango", "start_date"), State("date-rango", "end_date"), State("date-dia", "date"),
    State("session-id", "data"), State("drop-org", "value"), prevent_initial_call=True
)
def generar_html(n_clicks, locs, tipo_fecha, start_rango, end_rango, dia_unico, session_id, org_uuid):
    archivo_usuario = os.path.join('src', 'data', f'dataset_{session_id}.csv')
    if not os.path.exists(archivo_usuario):
        return dash.no_update, "Sincroniza los datos primero."

    df_completo = pd.read_csv(archivo_usuario)
    if locs:
        df_completo = df_completo[df_completo['location_id'].isin(locs)]
    df_completo['Ubicación'] = df_completo['location_id'].map(mapa_tiendas).fillna('Desconocida')
    df_completo['Zona'] = df_completo['zone_uuid'].map(mapa_zonas).fillna('SinNombre') if 'zone_uuid' in df_completo.columns else 'SinNombre'
    df_completo['fecha'] = pd.to_datetime(df_completo['fecha'])

    res = filtrar_dataframe_fechas(df_completo, tipo_fecha, start_rango, end_rango, dia_unico)
    if res[0] is None:
        return dash.no_update, res[1]
    df_filt, start, end = res

    df_filt = df_filt[~df_filt['Zona'].str.contains('Extra', case=False, na=False)]
    df_filt['Día semana'] = pd.Categorical(df_filt['fecha'].dt.dayofweek.map(dias_semana_es), categories=orden_dias, ordered=True)
    if 'dwell_time' in df_filt.columns:
        df_filt['dwell_time'] /= 60.0

    try:
        org_nombre = mapa_orgs.get(org_uuid, '') if org_uuid else ''
        server_url = flask.request.host_url
        html_str = generar_reporte_html(df_filt, start, end, org_nombre, server_url=server_url)
        nombre_archivo = f"Reporte_{org_nombre or 'Consolidado'}_{start.strftime('%d%m')}_al_{end.strftime('%d%m')}.html"
        return dcc.send_string(html_str, nombre_archivo), ""
    except Exception as e:
        return dash.no_update, f"Error generando HTML: {str(e)}"


@app.callback(
    Output("download-pdf-report", "data"), Output("error-msg-html", "children", allow_duplicate=True),
    Input("btn-generar-pdf", "n_clicks"), State("drop-locs", "value"), State("tipo-fecha", "value"),
    State("date-rango", "start_date"), State("date-rango", "end_date"), State("date-dia", "date"),
    State("session-id", "data"), State("drop-org", "value"), prevent_initial_call=True
)
def generar_pdf(n_clicks, locs, tipo_fecha, start_rango, end_rango, dia_unico, session_id, org_uuid):
    archivo_usuario = os.path.join('src', 'data', f'dataset_{session_id}.csv')
    if not os.path.exists(archivo_usuario):
        return dash.no_update, "Sincroniza los datos primero."

    df_completo = pd.read_csv(archivo_usuario)
    if locs:
        df_completo = df_completo[df_completo['location_id'].isin(locs)]
    df_completo['Ubicación'] = df_completo['location_id'].map(mapa_tiendas).fillna('Desconocida')
    df_completo['Zona'] = df_completo['zone_uuid'].map(mapa_zonas).fillna('SinNombre') if 'zone_uuid' in df_completo.columns else 'SinNombre'
    df_completo['fecha'] = pd.to_datetime(df_completo['fecha'])

    res = filtrar_dataframe_fechas(df_completo, tipo_fecha, start_rango, end_rango, dia_unico)
    if res[0] is None:
        return dash.no_update, res[1]
    df_filt, start, end = res

    df_filt = df_filt[~df_filt['Zona'].str.contains('Extra', case=False, na=False)]
    df_filt['Día semana'] = pd.Categorical(df_filt['fecha'].dt.dayofweek.map(dias_semana_es), categories=orden_dias, ordered=True)
    if 'dwell_time' in df_filt.columns:
        df_filt['dwell_time'] /= 60.0

    try:
        from playwright.sync_api import sync_playwright
        org_nombre = mapa_orgs.get(org_uuid, '') if org_uuid else ''
        html_str = generar_reporte_html(df_filt, start, end, org_nombre)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.set_content(html_str, wait_until="networkidle")
            page.wait_for_timeout(2000)
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "1.5cm", "bottom": "1.5cm", "left": "1.2cm", "right": "1.2cm"},
            )
            browser.close()
        nombre_archivo = f"Reporte_{org_nombre or 'Consolidado'}_{start.strftime('%d%m')}_al_{end.strftime('%d%m')}.pdf"
        return dcc.send_bytes(pdf_bytes, nombre_archivo), ""
    except Exception as e:
        return dash.no_update, f"Error generando PDF: {str(e)}"


@app.callback(
    Output("download-bi-zip", "data"),
    Input("btn-download-all-bi", "n_clicks"),
    State({"type": "bi-graph", "index": dash.ALL}, "figure"),
    State({"type": "bi-graph", "index": dash.ALL}, "id"),
    prevent_initial_call=True
)
def descargar_todos_graficos_bi(n, figures, ids):
    if not n or not figures:
        return dash.no_update
    import zipfile as zf
    buf = io.BytesIO()
    with zf.ZipFile(buf, 'w', zf.ZIP_DEFLATED) as z:
        for fig_dict, gid in zip(figures, ids):
            if not fig_dict:
                continue
            try:
                fig = go.Figure(fig_dict)
                img_bytes = fig.to_image(format='png', width=1400, height=600, scale=2)
                nombre = (gid['index'] if isinstance(gid, dict) else str(gid))[:80]
                z.writestr(f"{nombre}.png", img_bytes)
            except Exception:
                continue
    buf.seek(0)
    return dcc.send_bytes(buf.getvalue(), "graficos_bi.zip")


@app.callback(
    Output("download-auditoria", "data"),
    Input("btn-dl-auditoria", "n_clicks"),
    State("drop-locs", "value"), State("tipo-fecha", "value"),
    State("date-rango", "start_date"), State("date-rango", "end_date"),
    State("date-dia", "date"), State("radar-drop-zonas", "value"),
    State("session-id", "data"),
    prevent_initial_call=True
)
def descargar_auditoria_excel(n, locs, t_f, sd, ed, dia, zones_bi, session_id):
    if not n or not locs or not session_id:
        return dash.no_update
    archivo = os.path.join('src', 'data', f'dataset_{session_id}.csv')
    if not os.path.exists(archivo):
        return dash.no_update
    df = pd.read_csv(archivo)
    if df.empty:
        return dash.no_update
    df = df[df['location_id'].isin(locs)]
    df['Ubicación'] = df['location_id'].map(mapa_tiendas).fillna('Desconocida')
    df['Zona'] = df['zone_uuid'].map(mapa_zonas).fillna('SinNombre') if 'zone_uuid' in df.columns else 'SinNombre'
    df['fecha'] = pd.to_datetime(df['fecha'])
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
    if df_actual.empty:
        return dash.no_update
    cols = [c for c in ['fecha', 'Ubicación', 'Zona', 'total_visits', 'unique_visitors', 'new_visitors', 'dwell_time'] if c in df_actual.columns]
    df_exp = df_actual[cols].copy()
    df_exp['fecha'] = df_exp['fecha'].dt.strftime('%Y-%m-%d')
    if 'dwell_time' in df_exp.columns:
        df_exp['dwell_time'] = (df_exp['dwell_time'] / 60).round(1)
        df_exp.rename(columns={'dwell_time': 'estancia_min'}, inplace=True)
    df_exp.sort_values(['fecha', 'Ubicación', 'Zona'], inplace=True)
    return dcc.send_string(df_exp.to_csv(index=False), f"auditoria_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv")
