from dash import dcc, html, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from datetime import date
import os
import json
import pandas as pd
from src.services.ml_predictivo import ejecutar_auditoria_predictiva
from src.data_processing.constructor_master import cargar_csv_crudo, enriquecer_datos_ubicacion

RUTA_JSON = 'src/data/todas_las_ubicaciones.json'
mapa_zonas_por_loc = {}

if os.path.exists(RUTA_JSON):
    with open(RUTA_JSON, 'r', encoding='utf-8') as f:
        datos_json = json.load(f)
        for org in datos_json:
            for loc in org.get('locations', []):
                if loc.get('uuid'):
                    zonas = [{'label': z.get('zoneName', 'Zona'), 'value': z['uuid']} 
                             for z in loc.get('zones', []) if z.get('uuid')]
                    mapa_zonas_por_loc[loc['uuid']] = zonas

def generar_panel_ml():
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.H4([html.I(className="fas fa-brain me-2 text-primary"), "Motor Predictivo (Machine Learning)"], className="fw-bold mb-1 text-dark"),
                html.P("Entrena un modelo de forecasting al instante para predecir el flujo futuro de visitantes basado en el histórico sincronizado.", className="text-muted small")
            ], width=12)
        ], className="mb-4"),
        
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Zona a predecir:", className="fw-bold text-secondary small text-uppercase mb-1"),
                        dcc.Dropdown(id='ml-drop-zone', clearable=False, className="shadow-sm", placeholder="Esperando ubicación global...")
                    ], xs=12, md=4, className="mb-3 mb-md-0"),
                    dbc.Col([
                        html.Label("Fecha de inicio (Simulación):", className="fw-bold text-secondary small text-uppercase mb-1"),
                        dcc.DatePickerSingle(id='ml-date-falso', date=date(2026, 3, 1), display_format='YYYY-MM-DD', className="w-100 shadow-sm")
                    ], xs=12, md=4, className="mb-3 mb-md-0"),
                    dbc.Col([
                        html.Label("Horizonte a futuro (Días):", className="fw-bold text-secondary small text-uppercase mb-1"),
                        dcc.Slider(id='ml-slider-horiz', min=1, max=14, step=1, value=7, 
                                   marks={i: f'{i}d' for i in [1, 3, 7, 10, 14]}, className="mt-2")
                    ], xs=12, md=4)
                ], className="align-items-center mb-4"),
                
                dbc.Button([html.I(className="fas fa-cogs me-2"), "ENTRENAR Y EVALUAR MODELO"], id="ml-btn-run", color="primary", className="w-100 fw-bold rounded-pill shadow-sm mb-2"),
                html.Div(id="ml-error-msg", className="text-danger fw-bold mt-2 text-center small"),
            ])
        ], className="border-0 shadow-sm rounded-4 bg-light mb-4"),
        
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([html.H6("Precisión (Accuracy)", className="text-muted small text-uppercase fw-bold"), html.H3(id="ml-card-acc", children="-", className="text-success fw-bold mb-0")]), className="border-0 shadow-sm rounded-4 text-center"), xs=6, md=3, className="mb-3 mb-md-0"),
            dbc.Col(dbc.Card(dbc.CardBody([html.H6("Error Medio (MAE)", className="text-muted small text-uppercase fw-bold"), html.H3(id="ml-card-mae", children="-", className="text-warning fw-bold mb-0")]), className="border-0 shadow-sm rounded-4 text-center"), xs=6, md=3, className="mb-3 mb-md-0"),
            dbc.Col(dbc.Card(dbc.CardBody([html.H6("Desviación (WMAPE)", className="text-muted small text-uppercase fw-bold"), html.H3(id="ml-card-wmape", children="-", className="text-danger fw-bold mb-0")]), className="border-0 shadow-sm rounded-4 text-center"), xs=6, md=3, className="mb-3 mb-md-0"),
            dbc.Col(dbc.Card(dbc.CardBody([html.H6("Iteraciones (Trees)", className="text-muted small text-uppercase fw-bold"), html.H3(id="ml-card-iter", children="-", className="text-info fw-bold mb-0")]), className="border-0 shadow-sm rounded-4 text-center"), xs=6, md=3),
        ], className="mb-4"),
        
        dbc.Card([
            dbc.CardBody([
                dcc.Graph(id='ml-graph-res', style={"height": "400px"}, config={'displayModeBar': False})
            ], className="p-2")
        ], className="border-0 shadow-sm rounded-4 bg-white")
    ], className="p-2")

@callback(
    [Output('ml-drop-zone', 'options'), Output('ml-drop-zone', 'value')],
    [Input('drop-locs', 'value')]
)
def filtrar_zonas_desde_global(locs):
    if not locs: return [], None
    zonas_combinadas = []
    for loc in locs:
        zonas_combinadas.extend(mapa_zonas_por_loc.get(loc, []))
    return zonas_combinadas, zonas_combinadas[0]['value'] if zonas_combinadas else None

@callback(
    [Output('ml-card-acc', 'children'), Output('ml-card-mae', 'children'), Output('ml-card-wmape', 'children'),
     Output('ml-card-iter', 'children'), Output('ml-graph-res', 'figure'), Output('ml-error-msg', 'children')],
    [Input('ml-btn-run', 'n_clicks')],
    [State('drop-locs', 'value'), State('ml-drop-zone', 'value'), State('ml-date-falso', 'date'), 
     State('ml-slider-horiz', 'value'), State('session-id', 'data')] 
)
def ejecutar_auditoria(n, locs, zone, fecha, horiz, session_id):
    if n is None: return no_update, no_update, no_update, no_update, go.Figure().update_layout(template='plotly_white'), ""
    if not locs or not zone: return "-", "-", "-", "-", go.Figure(), "Aviso: Selecciona una ubicación en el filtro global (izquierda) y una zona."
    if not session_id: return "-", "-", "-", "-", go.Figure(), "Error de sesión: No se puede identificar el usuario."

    archivo_usuario = os.path.join('data', 'raw', f'dataset_{session_id}.csv')
    if not os.path.exists(archivo_usuario):
        return "-", "-", "-", "-", go.Figure(), "Error: Sincroniza los datos desde el panel principal antes de usar el Motor Predictivo."

    try:
        # Usamos TU función original para que formatee las columnas correctamente
        df_crudo = cargar_csv_crudo(archivo_usuario)
        loc_principal = locs[0]
        
        # Procesar para ML (pasando la fecha tal cual)
        df_e = enriquecer_datos_ubicacion(df_crudo, loc_principal, RUTA_JSON)
        res = ejecutar_auditoria_predictiva(df_e, loc_principal, zone, fecha, horiz)
        
        if "error" in res: return "-", "-", "-", "-", go.Figure(), f"Error en el motor ML: {res['error']}"
        
        # Gráfica
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=res['grafica']['fechas'], y=res['grafica']['reales'], name='Datos Reales', mode='lines+markers', line=dict(color='#bdc3c7', width=2), marker=dict(size=6, color='#7f8c8d')))
        fig.add_trace(go.Scatter(x=res['grafica']['fechas'], y=res['grafica']['predichos'], name='Predicción del Algoritmo', mode='lines+markers', line=dict(color='#27ae60', width=3, dash='dot', shape='spline'), marker=dict(size=8, symbol='diamond', color='#2ecc71')))
        
        fig.update_layout(
            title=dict(text="Proyección Predictiva vs Datos Reales", font=dict(size=16, color='#2c3e50', family='Arial, sans-serif')),
            template='plotly_white', 
            margin=dict(l=40, r=20, t=50, b=40), 
            legend=dict(orientation="h", y=1.1, x=0.5, xanchor='center'),
            hovermode='x unified',
            plot_bgcolor='white'
        )
        fig.update_xaxes(showgrid=True, gridcolor='#f0f0f0')
        fig.update_yaxes(showgrid=True, gridcolor='#f0f0f0', rangemode='tozero')

        m = res['metricas']
        
        acc = f"{m['accuracy']}%" if m['accuracy'] != "N/A" else "N/A"
        mae = f"{int(m['mae'])} vis." if m['mae'] != "N/A" else "N/A"
        wmape = f"{m['wmape_pct']}%" if m['wmape_pct'] != "N/A" else "N/A"
        
        return acc, mae, wmape, str(m['arboles_optimos']), fig, ""
        
    except Exception as e:
        return "-", "-", "-", "-", go.Figure(), f"Error crítico durante el entrenamiento: {str(e)}"