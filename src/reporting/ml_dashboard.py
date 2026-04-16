from dash import dcc, html, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from datetime import date
import os
import json
from src.services.ml_predictivo import ejecutar_auditoria_predictiva
from src.data_processing.constructor_master import cargar_csv_crudo, enriquecer_datos_ubicacion

RUTA_DATASET = 'src/dataset_global_raw.csv'
DF_CRUDO_GLOBAL = cargar_csv_crudo(RUTA_DATASET)
RUTA_JSON = 'src/todas_las_ubicaciones.json'

opciones_orgs = []
mapa_locs_por_org = {}
mapa_zonas_por_loc = {}

if os.path.exists(RUTA_JSON):
    with open(RUTA_JSON, 'r', encoding='utf-8') as f:
        datos_json = json.load(f)
        for org in datos_json:
            org_id = org.get('uuid')
            if not org_id: continue
            
            locs_validas = []
            for loc in org.get('locations', []):
                if loc.get('uuid'):
                    locs_validas.append({'label': loc.get('name', 'Tienda'), 'value': loc['uuid']})
                    
                    zonas = [{'label': z.get('zoneName', 'Zona'), 'value': z['uuid']} 
                             for z in loc.get('zones', []) if z.get('uuid')]
                    mapa_zonas_por_loc[loc['uuid']] = zonas
            
            if locs_validas:
                opciones_orgs.append({'label': org.get('name', 'Org'), 'value': org_id})
                mapa_locs_por_org[org_id] = locs_validas

def generar_panel_ml():
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Label("Organización:"),
                dcc.Dropdown(id='ml-drop-org', options=opciones_orgs, 
                             value=opciones_orgs[0]['value'] if opciones_orgs else None, clearable=False)
            ], width=4),
            dbc.Col([
                html.Label("Ubicación:"),
                dcc.Dropdown(id='ml-drop-loc', clearable=False)
            ], width=4),
            dbc.Col([
                html.Label("Zona:"),
                dcc.Dropdown(id='ml-drop-zone', clearable=False)
            ], width=4),
        ], className="mb-4"),
        
        dbc.Row([
            dbc.Col([
                html.Label("Fecha auditoría (Falso Hoy):"),
                dcc.DatePickerSingle(id='ml-date-falso', date=date(2026, 3, 1), display_format='YYYY-MM-DD', className="w-100")
            ], width=6),
            dbc.Col([
                html.Label("Horizonte de predicción (Días):"),
                dcc.Slider(id='ml-slider-horiz', min=1, max=14, step=1, value=7, 
                           marks={i: f'{i}d' for i in [1, 3, 7, 10, 14]})
            ], width=6)
        ], className="mb-4 align-items-center"),
        
        dbc.Button("ENTRENAR ALGORITMO Y EVALUAR", id="ml-btn-run", color="dark", className="w-100 fw-bold mb-4"),
        html.Div(id="ml-error-msg", className="text-danger fw-bold mb-3"),
        
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([html.H6("Accuracy"), html.H4(id="ml-card-acc", children="-")])), width=3),
            dbc.Col(dbc.Card(dbc.CardBody([html.H6("MAE"), html.H4(id="ml-card-mae", children="-")])), width=3),
            dbc.Col(dbc.Card(dbc.CardBody([html.H6("WMAPE"), html.H4(id="ml-card-wmape", children="-")])), width=3),
            dbc.Col(dbc.Card(dbc.CardBody([html.H6("Iteración Óptima"), html.H4(id="ml-card-iter", children="-")])), width=3),
        ], className="mb-4"),
        
        dcc.Graph(id='ml-graph-res')
    ], className="p-4")

@callback(
    [Output('ml-drop-loc', 'options'), Output('ml-drop-loc', 'value')],
    [Input('ml-drop-org', 'value')]
)
def filtrar_ubicaciones(org_uuid):
    if not org_uuid: return [], None
    locs = mapa_locs_por_org.get(org_uuid, [])
    return locs, locs[0]['value'] if locs else None

@callback(
    [Output('ml-drop-zone', 'options'), Output('ml-drop-zone', 'value')],
    [Input('ml-drop-loc', 'value')]
)
def filtrar_zonas(loc_uuid):
    if not loc_uuid: return [], None
    zonas = mapa_zonas_por_loc.get(loc_uuid, [])
    return zonas, zonas[0]['value'] if zonas else None

@callback(
    [Output('ml-card-acc', 'children'), Output('ml-card-mae', 'children'), Output('ml-card-wmape', 'children'),
     Output('ml-card-iter', 'children'), Output('ml-graph-res', 'figure'), Output('ml-error-msg', 'children')],
    [Input('ml-btn-run', 'n_clicks')],
    [State('ml-drop-loc', 'value'), State('ml-drop-zone', 'value'), State('ml-date-falso', 'date'), State('ml-slider-horiz', 'value')]
)
def ejecutar_auditoria(n, loc, zone, fecha, horiz):
    if n is None: return no_update, no_update, no_update, no_update, go.Figure(), ""
    if DF_CRUDO_GLOBAL is None: return "-", "-", "-", "-", go.Figure(), "Error: dataset_global_raw.csv no encontrado"
    if not loc or not zone: return "-", "-", "-", "-", go.Figure(), "Aviso: Faltan ubicación o zona."
    
    try:
        df_e = enriquecer_datos_ubicacion(DF_CRUDO_GLOBAL, loc, RUTA_JSON)
        res = ejecutar_auditoria_predictiva(df_e, loc, zone, fecha, horiz)
        
        if "error" in res: return "-", "-", "-", "-", go.Figure(), f"Error motor: {res['error']}"
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=res['grafica']['fechas'], y=res['grafica']['reales'], name='Real', mode='lines+markers', line=dict(color='#2c3e50')))
        fig.add_trace(go.Scatter(x=res['grafica']['fechas'], y=res['grafica']['predichos'], name='Predicción', mode='lines+markers', line=dict(color='#18bc9c', dash='dot')))
        fig.update_layout(template='plotly_white', margin=dict(l=20, r=20, t=40, b=20), legend=dict(orientation="h", y=1.1))

        m = res['metricas']
        return f"{m['accuracy']}%", f"{m['mae']} vis.", f"{m['wmape_pct']}%", str(m['arboles_optimos']), fig, ""
    except Exception as e:
        return "-", "-", "-", "-", go.Figure(), f"Error crítico: {str(e)}"