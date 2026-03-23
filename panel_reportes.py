import os
import json
import pandas as pd
import io
from datetime import datetime, timedelta
import dash
from dash import html, dcc, Input, Output, State
import dash_bootstrap_components as dbc
from sincronizar_datos import actualizar_datos_csv
from excels.generador_embudos import generar_excel_embudos
from excels.generador_operativo import generar_excel_operativo

with open('todas_las_ubicaciones.json', 'r', encoding='utf-8') as f:
    datos_loc = json.load(f)

opciones_orgs = []
mapa_locs_por_org = {}
mapa_tiendas = {}
mapa_zonas = {}

for org in datos_loc:
    if org.get('uuid'):
        opciones_orgs.append({'label': org.get('name', 'Org'), 'value': org['uuid']})
        locs_list = []
        for loc in org.get('locations', []):
            if loc.get('uuid'):
                locs_list.append({'label': loc.get('name', 'Loc'), 'value': loc['uuid']})
                mapa_tiendas[loc['uuid']] = loc.get('name', 'Loc')
                for z in loc.get('zones', []):
                    if z.get('uuid'):
                        mapa_zonas[z['uuid']] = z.get('zoneName', 'Zona')
        mapa_locs_por_org[org['uuid']] = locs_list

dias_semana_es = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
orden_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.LUX])
app.title = "Panel Analítico - Valdi"

app.layout = dbc.Container([
    html.Br(),
    dbc.Row([
        dbc.Col(html.H2("Reportes Ejecutivos", className="fw-bold"), width=8),
        dbc.Col(dbc.Button("Sincronizar", id="btn-sync", color="dark", className="w-100 fw-bold"), width=4)
    ], className="mb-4"),
    html.Div(id="sync-status", className="text-success fw-bold text-end"),
    
    dbc.Card(dbc.CardBody([
        dbc.Row([
            dbc.Col([
                html.Label("Organización:", className="fw-bold"),
                dcc.Dropdown(id="drop-org", options=opciones_orgs)
            ], width=6),
            dbc.Col([
                html.Label("Ubicaciones:", className="fw-bold"),
                dcc.Dropdown(id="drop-locs", multi=True)
            ], width=6)
        ], className="mb-4"),

        dbc.Row([
            dbc.Col([
                html.Label("1. Período a analizar en el Excel:", className="fw-bold mb-2 text-primary"),
                dbc.RadioItems(
                    id="tipo-fecha",
                    options=[
                        {"label": "Ayer", "value": "ayer"},
                        {"label": "Últimos 7 días", "value": "7d_rel"},
                        {"label": "Últimos 28 días", "value": "28d_rel"},
                        {"label": "Día concreto", "value": "dia"},
                        {"label": "Rango temporal", "value": "rango"}
                    ],
                    value="7d_rel",
                    inline=True,
                    className="mb-3"
                ),
                html.Div(
                    dcc.DatePickerRange(
                        id='date-rango',
                        start_date=datetime(2025, 9, 1).date(),
                        end_date=datetime.today().date(),
                        display_format='YYYY-MM-DD',
                        className="w-100"
                    ),
                    id="contenedor-rango", style={"display": "none"}
                ),
                html.Div(
                    dcc.DatePickerSingle(
                        id='date-dia',
                        date=datetime.today().date(),
                        display_format='YYYY-MM-DD',
                        className="w-100"
                    ),
                    id="contenedor-dia", style={"display": "none"}
                )
            ], width=6),
            dbc.Col([
                html.Label("2. Adjuntar KPIs Oficiales de la plataforma:", className="fw-bold mb-2 text-success"),
                dbc.Checklist(
                    id="kpis-oficiales", 
                    options=[
                        {"label": "7 días", "value": "7d"},
                        {"label": "28 días", "value": "28d"},
                        {"label": "Mes actual", "value": "month"},
                        {"label": "Año actual", "value": "year"}
                    ], 
                    value=["7d", "28d"], # Por defecto marcamos 7 y 28 a la vez
                    inline=True, 
                    className="mb-4"
                ),
                
                html.Label("3. Modelo de reporte:", className="fw-bold mb-2"),
                dbc.RadioItems(id="tipo-reporte", options=[
                    {"label": "Operativo (Días, Únicos, Estancia y Horas)", "value": "operativo"},
                    {"label": "Embudos Dinámicos (Zonas completas)", "value": "embudos"}
                ], value="operativo", inline=False)
            ], width=6)
        ], className="mb-5"),
        
        dbc.Button("Descargar Excel", id="btn-descargar", color="primary", className="w-100 fw-bold"),
        dcc.Download(id="download-excel")
    ]), className="shadow-lg border-0", style={"padding": "30px"})
], fluid=True)

@app.callback(
    Output("contenedor-rango", "style"), Output("contenedor-dia", "style"), Input("tipo-fecha", "value")
)
def toggle_fecha(tipo):
    if tipo == "dia": return {"display": "none"}, {"display": "block"}
    if tipo == "rango": return {"display": "block"}, {"display": "none"}
    return {"display": "none"}, {"display": "none"}

@app.callback(Output("drop-locs", "options"), Output("drop-locs", "value"), Input("drop-org", "value"))
def actualizar_locs(org_uuid):
    if not org_uuid: return [], []
    opciones = mapa_locs_por_org.get(org_uuid, [])
    return opciones, [opc['value'] for opc in opciones]

@app.callback(Output("sync-status", "children"), Input("btn-sync", "n_clicks"), State("drop-locs", "value"), prevent_initial_call=True)
def sync_datos(n_clicks, locs):
    actualizar_datos_csv(locs if locs else [])
    return "Sincronizado correctamente."

@app.callback(
    Output("download-excel", "data"),
    Input("btn-descargar", "n_clicks"),
    State("drop-locs", "value"), 
    State("tipo-fecha", "value"), 
    State("date-rango", "start_date"),
    State("date-rango", "end_date"),
    State("date-dia", "date"),
    State("kpis-oficiales", "value"),
    State("tipo-reporte", "value"),
    prevent_initial_call=True
)
def generar_excel(n_clicks, locs, tipo_fecha, start_rango, end_rango, dia_unico, kpis_oficiales, tipo_reporte):
    if not os.path.exists('dataset_global_raw.csv'): return dash.no_update
    df = pd.read_csv('dataset_global_raw.csv')
    df['fecha'] = pd.to_datetime(df['fecha'])
    
    # 1. DETERMINAR LAS FECHAS DEL EXCEL DE FORMA INDEPENDIENTE A LOS KPIS
    hoy = datetime.today().date()
    if tipo_fecha == "ayer": start = end = pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "7d_rel": start, end = pd.to_datetime(hoy - timedelta(days=7)), pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "28d_rel": start, end = pd.to_datetime(hoy - timedelta(days=28)), pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "dia" and dia_unico: start = end = pd.to_datetime(dia_unico)
    elif tipo_fecha == "rango" and start_rango and end_rango: start, end = pd.to_datetime(start_rango), pd.to_datetime(end_rango)
    else: return dash.no_update
        
    df_filt = df[(df['fecha'] >= start) & (df['fecha'] <= end)].copy()
    if locs: df_filt = df_filt[df_filt['location_id'].isin(locs)]
    if df_filt.empty: return dash.no_update

    df_filt['Ubicación'] = df_filt['location_id'].map(mapa_tiendas).fillna('Desconocida')
    
    if 'zone_uuid' in df_filt.columns:
        df_filt['Zona'] = df_filt['zone_uuid'].map(mapa_zonas).fillna('SinNombre')
    elif 'zone' in df_filt.columns:
        df_filt['Zona'] = df_filt['zone'].astype(str).map({'0': 'Caja', '1': 'Tienda', '2': 'Exterior', '3': 'Extra'}).fillna('SinNombre')
    else:
        df_filt['Zona'] = 'SinNombre'
    
    df_filt = df_filt[~df_filt['Zona'].str.contains('Extra', case=False, na=False)]
    df_filt['Día semana'] = pd.Categorical(df_filt['fecha'].dt.dayofweek.map(dias_semana_es), categories=orden_dias, ordered=True)

    if 'dwell_time' in df_filt.columns: df_filt['dwell_time'] = df_filt['dwell_time'] / 60.0

    df_filt['Día del periodo'] = (df_filt['fecha'] - start).dt.days
    df_filt['Semana del periodo'] = "Semana " + ((df_filt['Día del periodo'] // 7) + 1).astype(str)

    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    workbook = writer.book

    if tipo_reporte == "embudos": generar_excel_embudos(df_filt, writer, workbook)
    else: generar_excel_operativo(df_filt, writer, workbook, kpis_oficiales)

    workbook.close()
    output.seek(0)
    return dcc.send_bytes(output.getvalue(), f"Reporte_{tipo_reporte}.xlsx")

if __name__ == "__main__":
    app.run(debug=True, port=8051)