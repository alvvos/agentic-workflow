import os
import json
import pandas as pd
import io
import traceback
import uuid
from datetime import datetime, timedelta
import dash
from dash import html, dcc, Input, Output, State
import dash_bootstrap_components as dbc

# Importaciones de los módulos del proyecto
from src.data_ingestion.sincronizador import actualizar_datos_csv
from src.reporting.generador_embudos import generar_excel_embudos
from src.reporting.generador_operativo import generar_excel_operativo
#from src.reporting.pdf_builder import generar_documento_pdf
from src.reporting.ml_dashboard import generar_panel_ml
from src.data_processing.data_radar import generar_tabla_auditoria
from src.data_processing.feature_engineering import enriquecer_dataset_ml
from src.models.anomalys import generar_panel_anomalias
from src.models.forecaster import entrenar_modelo_volumen, calcular_anomalias_predictivas, predecir_manana
from src.llm_agents.insights_agent import generar_insight_predictivo

MODO_DESARROLLO = True

# Carga de la estructura de ubicaciones
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
app.title = "Panel analítico predictivo"
server = app.server

def serve_layout():
    if MODO_DESARROLLO:
        session_id = "local_dev"
    else:
        session_id = str(uuid.uuid4())
    
    return dbc.Container([
        dcc.Store(id='session-id', data=session_id),
        
        dbc.Modal([
            dbc.ModalBody([
                html.Div([
                    dbc.Spinner(color="primary", size="lg"),
                    html.H5("Procesando...", className="ms-3 mb-0 text-primary fw-bold")
                ], className="d-flex align-items-center p-3")
            ])
        ], id="modal-sync", is_open=False, backdrop="static", keyboard=False, centered=True),

        dbc.Toast(
            id="toast-notificacion",
            header="Notificación",
            is_open=False,
            dismissable=True,
            icon="info",
            duration=4000,
            style={"position": "fixed", "top": 20, "right": 20, "width": 350, "zIndex": 9999, "fontSize": "15px"}
        ),

        html.Br(),
        dbc.Row([
            dbc.Col(html.H2("Panel central predictivo", className="fw-bold"), width=6),
            dbc.Col(dbc.Button("Sincronizar", id="btn-sync", style={"backgroundColor": "#203764", "color": "white", "border": "none"}, className="w-100 fw-bold"), width=3),
            dbc.Col(dbc.Button("Flush data", id="btn-flush", style={"backgroundColor": "#c00000", "color": "white", "border": "none"}, className="w-100 fw-bold"), width=3)
        ], className="mb-4"),
        
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
                    html.Label("Período a visualizar:", className="fw-bold mb-2 text-primary"),
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
                    dbc.Row([
                        dbc.Col(dbc.Button("Descargar excel", id="btn-descargar", style={"backgroundColor": "#375623", "color": "white", "border": "none"}, className="w-100 fw-bold mt-4 mb-2"), width=6),
                        dbc.Col(dbc.Button("Descargar pdf ejecutivo ia", id="btn-descargar-pdf", style={"backgroundColor": "#8e44ad", "color": "white", "border": "none"}, className="w-100 fw-bold mt-4 mb-2"), width=6)
                    ]),
                    html.Div(id="error-msg", className="text-danger fw-bold mt-3 text-center fs-5"),
                    dcc.Download(id="download-excel"),
                    dcc.Download(id="download-pdf")
                ]),
                
                dcc.Tab(label='Radar de datos', value='tab-auditoria', children=[
                    html.Br(),
                    dbc.Row([
                        dbc.Col(dbc.Button("Sistema de alertas", id="btn-auditar", style={"backgroundColor": "#595959", "color": "white", "border": "none"}, className="w-100 fw-bold mb-2"), width=4),
                        dbc.Col(dbc.Button("Visualizar gráficas", id="btn-anomalias", style={"backgroundColor": "#2f75b5", "color": "white", "border": "none"}, className="w-100 fw-bold mb-2"), width=4),
                        dbc.Col(dbc.Button("Generar insight ia", id="btn-ejecutar-ia", style={"backgroundColor": "#8e44ad", "color": "white", "border": "none"}, className="w-100 fw-bold mb-2"), width=4)
                    ]),
                    
                    dbc.Spinner(html.Div(id="ia-results", className="mb-4 mt-3"), color="primary"),
                    html.Div(id="audit-results", className="mb-5 mt-3"),
                    html.Div(id="anomalias-results", className="mt-3")
                ]),

                dcc.Tab(label='Auditoría predictiva (ML)', value='tab-ml', children=[
                    html.Br(),
                    dbc.Row([
                        dbc.Col(dbc.Button("Entrenar algoritmo y evaluar", id="btn-evaluar-ml", style={"backgroundColor": "#16a085", "color": "white", "border": "none"}, className="w-100 fw-bold mb-4"), width=12)
                    ]),
                    dbc.Spinner(html.Div(id="ml-results", className="mb-4"), color="success")
                ])
            ])
        ]), className="shadow-lg border-0", style={"padding": "50px", "borderRadius": "12px"})
    ], fluid=True, style={"padding": "30px"})

app.layout = serve_layout

# --- FUNCIONES AUXILIARES ---

def leer_dataset_completo(locs, session_id):
    archivo_usuario = os.path.join('data', 'raw', f'dataset_{session_id}.csv')
    if not os.path.exists(archivo_usuario): return None
    df = pd.read_csv(archivo_usuario)
    if locs: df = df[df['location_id'].isin(locs)]
    df['Ubicación'] = df['location_id'].map(mapa_tiendas).fillna('Desconocida')
    if 'zone_uuid' in df.columns:
        df['Zona'] = df['zone_uuid'].map(mapa_zonas).fillna('SinNombre')
    else:
        df['Zona'] = 'SinNombre'
    return df

def filtrar_dataframe_fechas(df, tipo_fecha, start_rango, end_rango, dia_unico):
    df['fecha'] = pd.to_datetime(df['fecha'])
    hoy = datetime.today().date()
    if tipo_fecha == "ayer": start = end = pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "7d_rel": start, end = pd.to_datetime(hoy - timedelta(days=7)), pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "28d_rel": start, end = pd.to_datetime(hoy - timedelta(days=28)), pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "dia" and dia_unico: start = end = pd.to_datetime(dia_unico)
    elif tipo_fecha == "rango" and start_rango and end_rango: start, end = pd.to_datetime(start_rango), pd.to_datetime(end_rango)
    else: return None, "Rango temporal inválido."
        
    df_filt = df[(df['fecha'] >= start) & (df['fecha'] <= end)].copy()
    if df_filt.empty: return None, "No hay datos en las fechas seleccionadas."
    return df_filt, start

# --- CALLBACKS DE UI BASE ---

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
    Output("modal-sync", "is_open", allow_duplicate=True),
    Input("btn-sync", "n_clicks"),
    prevent_initial_call=True
)
def abrir_modal_carga(n_clicks):
    return True

@app.callback(
    Output("modal-sync", "is_open", allow_duplicate=True),
    Output("toast-notificacion", "is_open", allow_duplicate=True),
    Output("toast-notificacion", "children", allow_duplicate=True),
    Output("toast-notificacion", "icon", allow_duplicate=True),
    Output("toast-notificacion", "header", allow_duplicate=True),
    Input("modal-sync", "is_open"), 
    State("drop-locs", "value"),
    State("session-id", "data"),
    prevent_initial_call=True
)
def ejecutar_sincronizacion(is_open, locs, session_id):
    if not is_open:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
        
    ruta_raw = os.path.join('data', 'raw')
    archivo_usuario = os.path.join(ruta_raw, f'dataset_{session_id}.csv')
    
    try:
        if not os.path.exists(ruta_raw):
            os.makedirs(ruta_raw, exist_ok=True)
            
        actualizar_datos_csv(locs if locs else [], archivo_usuario)
        return False, True, "Datos sincronizados correctamente.", "success", "Sincronización finalizada"
    except Exception as e:
        traceback.print_exc()
        return False, True, f"Error al descargar datos: {str(e)}", "danger", "Error de sincronización"

@app.callback(
    Output("toast-notificacion", "is_open", allow_duplicate=True),
    Output("toast-notificacion", "children", allow_duplicate=True),
    Output("toast-notificacion", "icon", allow_duplicate=True),
    Output("toast-notificacion", "header", allow_duplicate=True),
    Input("btn-flush", "n_clicks"),
    State("session-id", "data"),
    prevent_initial_call=True
)
def limpiar_memoria(n, session_id):
    archivo_usuario = os.path.join('data', 'raw', f'dataset_{session_id}.csv')
    try:
        if os.path.exists(archivo_usuario):
            os.remove(archivo_usuario)
        return True, "Memoria limpiada con éxito.", "success", "Flush data"
    except Exception as e:
        return True, f"Error al limpiar memoria: {str(e)}", "danger", "Error"

# --- CALLBACKS DE NEGOCIO Y ML ---

@app.callback(
    Output("ml-results", "children"),
    Input("btn-evaluar-ml", "n_clicks"),
    State("drop-locs", "value"),
    State("tipo-fecha", "value"),
    State("date-rango", "start_date"),
    State("date-rango", "end_date"),
    State("date-dia", "date"),
    State("session-id", "data"),
    prevent_initial_call=True
)
def ejecutar_pipeline_ml(n_clicks, locs, tipo_fecha, start_rango, end_rango, dia_unico, session_id):
    df_completo = leer_dataset_completo(locs, session_id)
    if df_completo is None:
        return dbc.Alert("No hay datos cargados en sesión. Ejecuta una sincronización.", color="warning")
        
    try:
        # 1. Preparar datos
        df_ml = enriquecer_dataset_ml(df_completo)
        
        # 2. Entrenar y extraer validación cruzada (ahora devuelve métricas)
        modelo, features, metricas = entrenar_modelo_volumen(df_ml)
        
        # 3. Calcular residuos en el histórico
        df_resultados = calcular_anomalias_predictivas(df_ml, modelo, features)
        
        # 4. Proyectar vector sintético para mañana
        df_proyeccion = predecir_manana(df_ml, modelo, features)
        
        # 5. Filtrar visualización
        df_resultados['fecha'] = pd.to_datetime(df_resultados['fecha'])
        filtro_resultado = filtrar_dataframe_fechas(df_resultados, tipo_fecha, start_rango, end_rango, dia_unico)
        
        df_mostrar = filtro_resultado[0] if filtro_resultado[0] is not None else df_resultados

        return generar_panel_ml(df_mostrar, metricas, df_proyeccion)
    except Exception as e:
        traceback.print_exc()
        return dbc.Alert(f"Error crítico en la capa predictiva: {str(e)}", color="danger")

@app.callback(
    Output("ia-results", "children"),
    Input("btn-ejecutar-ia", "n_clicks"),
    State("drop-locs", "value"), 
    State("tipo-fecha", "value"), 
    State("date-rango", "start_date"),
    State("date-rango", "end_date"),
    State("date-dia", "date"),
    State("session-id", "data"),
    prevent_initial_call=True
)
def solicitar_insight(n_clicks, locs, tipo_fecha, start_rango, end_rango, dia_unico, session_id):
    df_completo = leer_dataset_completo(locs, session_id)
    if df_completo is None:
        return dbc.Alert("No hay datos cargados en sesión. Ejecuta una sincronización.", color="warning")
        
    try:
        df_ml = enriquecer_dataset_ml(df_completo)
        modelo, features, metricas = entrenar_modelo_volumen(df_ml)
        df_resultados = calcular_anomalias_predictivas(df_ml, modelo, features)
        
        df_resultados['fecha'] = pd.to_datetime(df_resultados['fecha'])
        filtro_resultado = filtrar_dataframe_fechas(df_resultados, tipo_fecha, start_rango, end_rango, dia_unico)
        
        if filtro_resultado[0] is None:
            return dbc.Alert(filtro_resultado[1], color="warning")
            
        texto_insight = generar_insight_predictivo(filtro_resultado[0])
        
        return dbc.Card([
            dbc.CardHeader(html.H6("Conclusión predictiva de inteligencia artificial", className="mb-0 fw-bold", style={'color': '#2c3e50'})),
            dbc.CardBody(dcc.Markdown(texto_insight, className="mb-0", style={'fontSize': '15px'}))
        ], className="shadow-sm border-primary", style={'borderWidth': '1px'})
        
    except Exception as e:
        traceback.print_exc()
        return dbc.Alert(f"Error generando insight: {str(e)}", color="danger")

@app.callback(
    Output("audit-results", "children"),
    Input("btn-auditar", "n_clicks"),
    State("drop-locs", "value"), 
    State("tipo-fecha", "value"), 
    State("date-rango", "start_date"),
    State("date-rango", "end_date"),
    State("date-dia", "date"),
    State("session-id", "data"),
    prevent_initial_call=True
)
def auditar_datos(n_auditar, locs, tipo_fecha, start_rango, end_rango, dia_unico, session_id):
    df_completo = leer_dataset_completo(locs, session_id)
    if df_completo is None:
        return dbc.Alert("No hay datos cargados en sesión. Ejecuta una sincronización.", color="warning")
        
    df_filt, err_or_start = filtrar_dataframe_fechas(df_completo.copy(), tipo_fecha, start_rango, end_rango, dia_unico)
    if df_filt is None:
        return dbc.Alert(err_or_start, color="warning")
        
    return generar_tabla_auditoria(df_filt)

@app.callback(
    Output("anomalias-results", "children"),
    Input("btn-anomalias", "n_clicks"),
    State("drop-locs", "value"), 
    State("tipo-fecha", "value"), 
    State("date-rango", "start_date"),
    State("date-rango", "end_date"),
    State("date-dia", "date"),
    State("session-id", "data"),
    prevent_initial_call=True
)
def analizar_anomalias(n_anomalias, locs, tipo_fecha, start_rango, end_rango, dia_unico, session_id):
    df_completo = leer_dataset_completo(locs, session_id)
    if df_completo is None:
        return dbc.Alert("No hay datos cargados en sesión. Ejecuta una sincronización.", color="warning")
        
    df_filt, err_or_start = filtrar_dataframe_fechas(df_completo.copy(), tipo_fecha, start_rango, end_rango, dia_unico)
    if df_filt is None:
        return dbc.Alert(err_or_start, color="warning")
        
    if 'dwell_time' in df_filt.columns:
        df_filt['dwell_time'] = df_filt['dwell_time'] / 60.0
        
    return generar_panel_anomalias(df_filt)

@app.callback(
    Output("download-excel", "data"),
    Output("error-msg", "children", allow_duplicate=True), 
    Input("btn-descargar", "n_clicks"),
    State("drop-locs", "value"), 
    State("tipo-fecha", "value"), 
    State("date-rango", "start_date"),
    State("date-rango", "end_date"),
    State("date-dia", "date"),
    State("kpis-oficiales", "value"),
    State("tipo-reporte", "value"),
    State("session-id", "data"),
    prevent_initial_call=True
)
def generar_excel(n_clicks, locs, tipo_fecha, start_rango, end_rango, dia_unico, kpis_oficiales, tipo_reporte, session_id):
    df_completo = leer_dataset_completo(locs, session_id)
    if df_completo is None:
        return dash.no_update, "Sincroniza los datos primero."
        
    df_filt, err_or_start = filtrar_dataframe_fechas(df_completo.copy(), tipo_fecha, start_rango, end_rango, dia_unico)
    if df_filt is None:
        return dash.no_update, err_or_start

    df_filt = df_filt[~df_filt['Zona'].str.contains('Extra', case=False, na=False)]
    df_filt['Día semana'] = pd.Categorical(df_filt['fecha'].dt.dayofweek.map(dias_semana_es), categories=orden_dias, ordered=True)
    
    if 'dwell_time' in df_filt.columns:
        df_filt['dwell_time'] = df_filt['dwell_time'] / 60.0

    df_filt['Día del periodo'] = (df_filt['fecha'] - err_or_start).dt.days
    df_filt['Semana del periodo'] = "Semana " + ((df_filt['Día del periodo'] // 7) + 1).astype(str)

    try:
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='xlsxwriter')
        workbook = writer.book

        if tipo_reporte == "embudos":
            generar_excel_embudos(df_filt, writer, workbook)
        else:
            generar_excel_operativo(df_filt, writer, workbook, kpis_oficiales)

        workbook.close()
        output.seek(0)
        return dcc.send_bytes(output.getvalue(), f"Reporte_{tipo_reporte}.xlsx"), ""
    except Exception as e:
        traceback.print_exc()
        return dash.no_update, f"Error generando el excel: {str(e)}"

@app.callback(
    Output("download-pdf", "data"),
    Output("error-msg", "children", allow_duplicate=True),
    Output("modal-sync", "is_open", allow_duplicate=True),
    Input("btn-descargar-pdf", "n_clicks"),
    State("drop-locs", "value"), 
    State("tipo-fecha", "value"), 
    State("date-rango", "start_date"),
    State("date-rango", "end_date"),
    State("date-dia", "date"),
    State("session-id", "data"),
    prevent_initial_call=True
)
def descargar_pdf_ejecutivo(n_clicks, locs, tipo_fecha, start_rango, end_rango, dia_unico, session_id):
    df_completo = leer_dataset_completo(locs, session_id)
    if df_completo is None:
        return dash.no_update, "Sincroniza los datos primero.", False
        
    df_filt, err_or_start = filtrar_dataframe_fechas(df_completo.copy(), tipo_fecha, start_rango, end_rango, dia_unico)
    if df_filt is None:
        return dash.no_update, err_or_start, False

    try:
        pdf_bytes = generar_documento_pdf(df_filt)
        return dcc.send_bytes(pdf_bytes, "Reporte_ejecutivo_ia.pdf"), "", False
    except Exception as e:
        traceback.print_exc()
        return dash.no_update, f"Error generando pdf: {str(e)}", False

if __name__ == "__main__":
    app.run(debug=True, port=8051)