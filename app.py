import os
import json
import pandas as pd
import io
import traceback
from datetime import datetime, timedelta
import dash
from dash import html, dcc, Input, Output, State
import dash_bootstrap_components as dbc
from sincronizar_datos import actualizar_datos_csv
from excels.generador_embudos import generar_excel_embudos
from excels.generador_operativo import generar_excel_operativo
from auditor_datos import generar_tabla_auditoria
from analizador_anomalias import generar_panel_anomalias

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

app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.LUX, dbc.icons.FONT_AWESOME],
    suppress_callback_exceptions=True
)
app.title = "Panel analítico - Valdi"

server = app.server

app.layout = dbc.Container([
    html.Br(),
    dbc.Row([
        dbc.Col(html.H2("Panel central analítico", className="fw-bold"), width=6),
        dbc.Col(dbc.Button("Sincronizar", id="btn-sync", style={"backgroundColor": "#203764", "color": "white", "border": "none"}, className="w-100 fw-bold"), width=3),
        dbc.Col(dbc.Button("Flush data", id="btn-flush", style={"backgroundColor": "#c00000", "color": "white", "border": "none"}, className="w-100 fw-bold"), width=3)
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
                html.Label("Período a analizar:", className="fw-bold mb-2 text-primary"),
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
            ], width=12)
        ], className="mb-4"),

        dcc.Tabs(id="tabs-panel", value='tab-reportes', children=[
            dcc.Tab(label='Generador de reportes', value='tab-reportes', children=[
                html.Br(),
                dbc.Row([
                    dbc.Col([
                        html.Label("Adjuntar kpis oficiales:", className="fw-bold mb-2 text-success"),
                        dbc.Checklist(
                            id="kpis-oficiales", 
                            options=[
                                {"label": "7 días", "value": "7d"},
                                {"label": "28 días", "value": "28d"},
                                {"label": "Mes actual", "value": "month"},
                                {"label": "Año actual", "value": "year"}
                            ], 
                            value=["7d", "28d"], 
                            inline=True, 
                            className="mb-4"
                        )
                    ], width=6),
                    dbc.Col([
                        html.Label("Modelo de reporte:", className="fw-bold mb-2"),
                        dbc.RadioItems(id="tipo-reporte", options=[
                            {"label": "Operativo (días, visitantes, estancia y horas)", "value": "operativo"},
                            {"label": "Embudos dinámicos (flujos completos)", "value": "embudos"}
                        ], value="operativo", inline=False)
                    ], width=6)
                ]),
                dbc.Button("Descargar excel", id="btn-descargar", style={"backgroundColor": "#375623", "color": "white", "border": "none"}, className="w-100 fw-bold mt-4 mb-2"),
                html.Div(id="error-msg", className="text-danger fw-bold mt-3 text-center fs-5"),
                dcc.Download(id="download-excel")
            ]),
            
            dcc.Tab(label='Radar de datos', value='tab-auditoria', children=[
                html.Br(),
                dbc.Row([
                    dbc.Col([
                        dbc.Button("Sistema de alertas", id="btn-auditar", style={"backgroundColor": "#595959", "color": "white", "border": "none"}, className="w-100 fw-bold mb-2"),
                        dbc.Button("Minimizar tabla", id="btn-min-auditoria", color="light", size="sm", className="w-100 mb-4 text-muted border-0")
                    ], width=6),
                    dbc.Col([
                        dbc.Button("Visualizar gráficas", id="btn-anomalias", style={"backgroundColor": "#2f75b5", "color": "white", "border": "none"}, className="w-100 fw-bold mb-2"),
                        dbc.Button("Minimizar gráficos", id="btn-min-anomalias", color="light", size="sm", className="w-100 mb-4 text-muted border-0")
                    ], width=6)
                ]),
                html.Div(id="audit-results", className="mb-5"),
                html.Div(id="anomalias-results")
            ])
        ])
    ]), className="shadow-lg border-0", style={"padding": "50px", "borderRadius": "12px"})
], fluid=True, style={"padding": "30px"})

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

@app.callback(
    Output("sync-status", "children"), 
    Input("btn-sync", "n_clicks"), 
    Input("btn-flush", "n_clicks"), 
    State("drop-locs", "value"), 
    prevent_initial_call=True
)
def sync_datos(n_sync, n_flush, locs):
    if dash.ctx.triggered_id == "btn-flush":
        if os.path.exists('dataset_global_raw.csv'):
            os.remove('dataset_global_raw.csv')
        actualizar_datos_csv(locs if locs else [])
        return "Datos borrados y resincronizados desde cero."
        
    actualizar_datos_csv(locs if locs else [])
    return "Sincronizado correctamente."

def filtrar_dataframe(tipo_fecha, start_rango, end_rango, dia_unico, locs):
    if not os.path.exists('dataset_global_raw.csv'): 
        return None, "No se encuentra el archivo, sincroniza primero."
        
    df = pd.read_csv('dataset_global_raw.csv')
    df['fecha'] = pd.to_datetime(df['fecha'])
    
    hoy = datetime.today().date()
    if tipo_fecha == "ayer": start = end = pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "7d_rel": start, end = pd.to_datetime(hoy - timedelta(days=7)), pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "28d_rel": start, end = pd.to_datetime(hoy - timedelta(days=28)), pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "dia" and dia_unico: start = end = pd.to_datetime(dia_unico)
    elif tipo_fecha == "rango" and start_rango and end_rango: start, end = pd.to_datetime(start_rango), pd.to_datetime(end_rango)
    else: return None, "Selecciona un rango válido."
        
    df_filt = df[(df['fecha'] >= start) & (df['fecha'] <= end)].copy()
    if locs: df_filt = df_filt[df_filt['location_id'].isin(locs)]
    
    if df_filt.empty: return None, "No hay datos en las fechas seleccionadas."

    df_filt['Ubicación'] = df_filt['location_id'].map(mapa_tiendas).fillna('Desconocida')
    if 'zone_uuid' in df_filt.columns:
        df_filt['Zona'] = df_filt['zone_uuid'].map(mapa_zonas).fillna('SinNombre')
    else:
        df_filt['Zona'] = 'SinNombre'
        
    return df_filt, start

@app.callback(
    Output("download-excel", "data"),
    Output("error-msg", "children"), 
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
    df_filt, err_or_start = filtrar_dataframe(tipo_fecha, start_rango, end_rango, dia_unico, locs)
    if df_filt is None: return dash.no_update, err_or_start

    df_filt = df_filt[~df_filt['Zona'].str.contains('Extra', case=False, na=False)]
    df_filt['Día semana'] = pd.Categorical(df_filt['fecha'].dt.dayofweek.map(dias_semana_es), categories=orden_dias, ordered=True)
    if 'dwell_time' in df_filt.columns: df_filt['dwell_time'] = df_filt['dwell_time'] / 60.0

    df_filt['Día del periodo'] = (df_filt['fecha'] - err_or_start).dt.days
    df_filt['Semana del periodo'] = "Semana " + ((df_filt['Día del periodo'] // 7) + 1).astype(str)

    try:
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='xlsxwriter')
        workbook = writer.book

        if tipo_reporte == "embudos": generar_excel_embudos(df_filt, writer, workbook)
        else: generar_excel_operativo(df_filt, writer, workbook, kpis_oficiales)

        workbook.close()
        output.seek(0)
        return dcc.send_bytes(output.getvalue(), f"Reporte_{tipo_reporte}.xlsx"), ""
    except Exception as e:
        traceback.print_exc()
        return dash.no_update, f"Error generando el excel: {str(e)}"

@app.callback(
    Output("audit-results", "children"),
    Input("btn-auditar", "n_clicks"),
    Input("btn-min-auditoria", "n_clicks"),
    State("drop-locs", "value"), 
    State("tipo-fecha", "value"), 
    State("date-rango", "start_date"),
    State("date-rango", "end_date"),
    State("date-dia", "date"),
    prevent_initial_call=True
)
def auditar_datos(n_auditar, n_min, locs, tipo_fecha, start_rango, end_rango, dia_unico):
    if dash.ctx.triggered_id == "btn-min-auditoria":
        return ""
    
    df_filt, err_or_start = filtrar_dataframe(tipo_fecha, start_rango, end_rango, dia_unico, locs)
    if df_filt is None: return dbc.Alert(err_or_start, color="warning")
    return generar_tabla_auditoria(df_filt)

@app.callback(
    Output("anomalias-results", "children"),
    Input("btn-anomalias", "n_clicks"),
    Input("btn-min-anomalias", "n_clicks"),
    State("drop-locs", "value"), 
    State("tipo-fecha", "value"), 
    State("date-rango", "start_date"),
    State("date-rango", "end_date"),
    State("date-dia", "date"),
    prevent_initial_call=True
)
def analizar_anomalias(n_anomalias, n_min, locs, tipo_fecha, start_rango, end_rango, dia_unico):
    if dash.ctx.triggered_id == "btn-min-anomalias":
        return ""
        
    df_filt, err_or_start = filtrar_dataframe(tipo_fecha, start_rango, end_rango, dia_unico, locs)
    if df_filt is None: return dbc.Alert(err_or_start, color="warning")
    if 'dwell_time' in df_filt.columns: df_filt['dwell_time'] = df_filt['dwell_time'] / 60.0
    return generar_panel_anomalias(df_filt)

if __name__ == "__main__":
    app.run(debug=True, port=8051)