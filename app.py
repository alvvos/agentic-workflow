import os
import json
import pandas as pd
import io
import traceback
import uuid
from datetime import datetime, timedelta
import dash
from dash import html, dcc, Input, Output, State, ctx
import plotly.graph_objects as go
import dash_bootstrap_components as dbc

# --- IMPORTACIONES DEL PROYECTO ---
from src.data_ingestion.sincronizador import actualizar_datos_csv
from src.reporting.generador_embudos import generar_excel_embudos
from src.reporting.generador_operativo import generar_excel_operativo
from src.reporting.ml_dashboard import generar_panel_ml
from src.data_processing.data_radar import generar_tabla_auditoria
from src.models.anomalys import generar_panel_bi_completo
from src.reporting.health_check import generar_panel_ejecutivo # <- AQUÍ ESTABA EL FALLO

MODO_DESARROLLO = True

# --- CARGA DE DATOS MAESTROS ---
with open('src/data/todas_las_ubicaciones.json', 'r', encoding='utf-8') as f:
    datos_loc = json.load(f)

opciones_orgs = []
mapa_locs_por_org = {}
mapa_tiendas = {}
mapa_zonas = {}
mapa_zonas_por_loc = {}

for org in datos_loc:
    if org.get('uuid'):
        opciones_orgs.append({'label': org.get('name'), 'value': org['uuid']})
        locs_list = []
        for loc in org.get('locations', []):
            if loc.get('uuid'):
                locs_list.append({'label': loc.get('name'), 'value': loc['uuid']})
                mapa_tiendas[loc['uuid']] = loc.get('name')
                
                zonas_loc = []
                for z in loc.get('zones', []):
                    if z.get('uuid'):
                        nombre_zona = z.get('zoneName', 'Zona')
                        mapa_zonas[z['uuid']] = nombre_zona
                        zonas_loc.append({
                            'label': nombre_zona, 
                            'value': nombre_zona,
                            'tipo': z.get('zoneType', '')  
                        })
                mapa_zonas_por_loc[loc['uuid']] = zonas_loc
                
        mapa_locs_por_org[org['uuid']] = locs_list

dias_semana_es = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
orden_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

# --- CONFIGURACIÓN DE LA APP ---
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.LUX, dbc.icons.FONT_AWESOME],
    suppress_callback_exceptions=True
)
app.title = "Panel Analítico Predictivo"
server = app.server

# --- INTERFAZ VISUAL (LAYOUT) ---
def serve_layout():
    session_id = "local_dev" if MODO_DESARROLLO else str(uuid.uuid4())
    
    sidebar = html.Div([
        dbc.Card([
            dbc.CardBody([
                html.H5([html.I(className="fas fa-sliders-h me-2 text-primary"), "Filtros Globales"], className="fw-bold mb-4 text-dark"),
                
                html.Label("Organización", className="fw-bold text-muted small text-uppercase mb-1"),
                dcc.Dropdown(id="drop-org", options=opciones_orgs, value=opciones_orgs[0]['value'] if opciones_orgs else None, className="mb-3 shadow-sm"),
                
                html.Label("Ubicaciones", className="fw-bold text-muted small text-uppercase mb-1 mt-2"),
                dcc.Dropdown(id="drop-locs", multi=True, className="mb-4 shadow-sm"),
                
                html.Hr(className="text-muted"),
                
                html.Label("Período a visualizar", className="fw-bold text-muted small text-uppercase mb-3 mt-3"),
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
                    className="mb-3"
                ),
                html.Div(
                    dcc.DatePickerRange(
                        id='date-rango', start_date=datetime(2025, 9, 1).date(), end_date=datetime.today().date(),
                        display_format='YYYY-MM-DD', className="w-100 shadow-sm"
                    ), id="contenedor-rango", style={"display": "none"}
                ),
                html.Div(
                    dcc.DatePickerSingle(
                        id='date-dia', date=datetime.today().date(), display_format='YYYY-MM-DD',
                        className="w-100 shadow-sm"
                    ), id="contenedor-dia", style={"display": "none"}
                )
            ])
        ], className="border-0 shadow-sm rounded-4")
    ], className="sticky-top", style={"top": "30px", "zIndex": 1020})

    main_content = html.Div([
        dbc.Row([
            dbc.Col(html.H2("Panel Analítico Predictivo", className="fw-bold text-dark mb-0"), xs=12, md=7, className="mb-3 mb-md-0"),
            dbc.Col([
                dbc.Button([html.I(className="fas fa-sync-alt me-2"), "Sincronizar"], id="btn-sync", color="primary", outline=True, className="fw-bold rounded-pill shadow-sm me-2"),
                dbc.Button([html.I(className="fas fa-trash-alt me-2"), "Flush"], id="btn-flush", color="danger", outline=True, className="fw-bold rounded-pill shadow-sm")
            ], xs=12, md=5, className="text-md-end")
        ], className="mb-4 align-items-center"),
        
        dbc.Card([
            dbc.CardBody([
                dcc.Tabs(id="tabs-panel", value='tab-ejecutivo', className="custom-tabs", children=[
                    
                    # --- NUEVA PESTAÑA: RESUMEN EJECUTIVO (AQUÍ FALTABA EL ID) ---
                    dcc.Tab(label='Resumen ejecutivo', value='tab-ejecutivo', className="fw-bold", children=[
                        html.Br(),
                        html.Div(id="panel-ejecutivo-content")
                    ]),

                    dcc.Tab(label='Panel BI', value='tab-auditoria', className="fw-bold", children=[
                        html.Br(),
                        
                        html.Div(id="bi-status-visor", className="mb-4 p-3 bg-light rounded-4 border-start border-primary border-4 shadow-sm"),
                        
                        dbc.Row([
                            dbc.Col([
                                html.Label([html.I(className="fas fa-filter me-2 text-primary"), "Zonas activas:"], className="fw-bold mb-3 text-secondary"),
                                dbc.Checklist(
                                    id="radar-drop-zonas", options=[], value=[], inline=True,
                                    input_class_name="btn-check", label_class_name="btn btn-outline-primary mb-2 me-2 fw-bold shadow-sm rounded-pill"
                                )
                            ], width=12)
                        ], className="mb-4"),
                        
                        dbc.Row([
                            dbc.Col([
                                html.Label([html.I(className="fas fa-balance-scale me-2 text-primary"), "Comparativa temporal:"], className="fw-bold mb-2 mt-2 text-secondary"),
                                dbc.RadioItems(
                                    id="bi-comparativa",
                                    options=[
                                        {"label": "Ninguna", "value": "none"},
                                        {"label": "vs. Semana Ant. (WoW)", "value": "wow"},
                                        {"label": "vs. Mes Ant. (MoM)", "value": "mom"},
                                        {"label": "vs. Año Ant. (YoY)", "value": "yoy"}
                                    ],
                                    value="none", inline=True, className="mb-2"
                                )
                            ], xs=12, lg=8),
                            dbc.Col([
                                dbc.Button([html.I(className="fas fa-times me-2"), "Borrar filtro cruzado"], id="btn-clear-bi", color="danger", outline=True, className="mt-lg-4 mt-2 w-100 rounded-pill fw-bold shadow-sm")
                            ], xs=12, lg=4)
                        ], className="align-items-center mb-4"),
                        
                        html.Div(id="bi-dynamic-content"),
                        html.Hr(className="text-muted my-5"),
                        html.Div(id="audit-results")
                    ]),

                    dcc.Tab(label='Generador de reportes', value='tab-reportes', className="fw-bold", children=[
                        html.Br(),
                        dbc.Row([
                            dbc.Col([
                                html.H4([html.I(className="fas fa-file-export me-2 text-primary"), "Exportación de Datos"], className="fw-bold mb-1 text-dark"),
                                html.P("Configura y descarga reportes detallados en formato Excel listos para presentar.", className="text-muted small")
                            ], width=12)
                        ], className="mb-4"),

                        dbc.Card([
                            dbc.CardBody([
                                dbc.Row([
                                    dbc.Col([
                                        html.Label("Adjuntar KPIs oficiales:", className="fw-bold text-secondary small text-uppercase mb-2"),
                                        dbc.Checklist(
                                            id="kpis-oficiales", 
                                            options=[
                                                {"label": "7 días", "value": "7d"}, 
                                                {"label": "28 días", "value": "28d"}, 
                                                {"label": "Mes actual", "value": "month"}, 
                                                {"label": "Año actual", "value": "year"}
                                            ], 
                                            value=["7d", "28d"], inline=True, input_class_name="btn-check", 
                                            label_class_name="btn btn-outline-primary mb-2 me-2 fw-bold shadow-sm rounded-pill"
                                        )
                                    ], xs=12, xl=6, className="mb-4 mb-xl-0"),
                                    
                                    dbc.Col([
                                        html.Label("Modelo de reporte:", className="fw-bold text-secondary small text-uppercase mb-2"),
                                        dbc.RadioItems(
                                            id="tipo-reporte", 
                                            options=[
                                                {"label": "Operativo (Visitas, horas...)", "value": "operativo"}, 
                                                {"label": "Embudos dinámicos", "value": "embudos"}
                                            ], 
                                            value="operativo", inline=True, input_class_name="btn-check", 
                                            label_class_name="btn btn-outline-secondary mb-2 me-2 fw-bold shadow-sm rounded-pill"
                                        )
                                    ], xs=12, xl=6)
                                ]),
                                html.Hr(className="text-muted my-4"),
                                dbc.Row([
                                    dbc.Col([
                                        dbc.Button([html.I(className="fas fa-file-excel me-2"), "Generar y Descargar Excel"], id="btn-descargar", color="success", className="w-100 fw-bold rounded-pill shadow-sm")
                                    ], xs=12, md=6, lg=4, className="mx-auto")
                                ]),
                                html.Div(id="error-msg", className="text-danger fw-bold mt-3 text-center small"),
                            ])
                        ], className="border-0 shadow-sm rounded-4 bg-light mb-4"),
                        dcc.Download(id="download-excel")
                    ]),

                    dcc.Tab(label='Machine learning', value='tab-ml', className="fw-bold", children=[
                        html.Br(),
                        generar_panel_ml()
                    ])
                ])
            ])
        ], className="border-0 shadow-sm rounded-4 bg-white")
    ])

    return dbc.Container([
        dcc.Store(id='session-id', data=session_id),
        dcc.Store(id='bi-filtro-zona', data=None),
        
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle(id="modal-bi-title", className="fw-bold text-primary")),
            dbc.ModalBody(dcc.Graph(id="modal-bi-graph", style={"height": "75vh"})),
        ], id="modal-bi-fullscreen", size="xl", is_open=False, centered=True),
        
        dbc.Modal([
            dbc.ModalBody(html.Div([dbc.Spinner(color="primary", size="lg"), html.H5("Procesando...", className="ms-3 mb-0 text-primary fw-bold")], className="d-flex align-items-center p-3"))
        ], id="modal-sync", is_open=False, backdrop="static", keyboard=False, centered=True),

        dbc.Toast(id="toast-notificacion", header="Notificación", is_open=False, dismissable=True, icon="info", duration=4000, style={"position": "fixed", "top": 20, "right": 20, "width": 350, "zIndex": 9999, "fontSize": "15px"}),

        dbc.Row([
            dbc.Col(sidebar, xs=12, lg=3, xl=2, className="mb-4 mb-lg-0"),
            dbc.Col(main_content, xs=12, lg=9, xl=10)
        ])
    ], fluid=True, style={"padding": "30px", "backgroundColor": "#f4f6f9", "minHeight": "100vh"})

app.layout = serve_layout

# --- FUNCIONES AUXILIARES ---
def filtrar_dataframe_fechas(df, tipo_fecha, start_rango, end_rango, dia_unico):
    hoy = datetime.today().date()
    if tipo_fecha == "ayer": start = end = pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "7d_rel": start, end = pd.to_datetime(hoy - timedelta(days=7)), pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "28d_rel": start, end = pd.to_datetime(hoy - timedelta(days=28)), pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "dia" and dia_unico: start = end = pd.to_datetime(dia_unico)
    elif tipo_fecha == "rango" and start_rango and end_rango: start, end = pd.to_datetime(start_rango), pd.to_datetime(end_rango)
    else: return None, "Rango temporal inválido."
        
    df_filt = df[(df['fecha'] >= start) & (df['fecha'] <= end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))].copy()
    if df_filt.empty: return None, "No hay datos en las fechas seleccionadas."
    return df_filt, start, end

# --- CALLBACKS BASE ---
@app.callback(Output("contenedor-rango", "style"), Output("contenedor-dia", "style"), Input("tipo-fecha", "value"))
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
    [Output("radar-drop-zonas", "options"), Output("radar-drop-zonas", "value")],
    [Input("drop-locs", "value")]
)
def auto_fill_zonas(locs):
    if not locs: return [], []
    opts, vals, vistos = [], [], set()
    for l in locs:
        for z in mapa_zonas_por_loc.get(l, []):
            if z['value'] not in vistos:
                opts.append(z)
                vistos.add(z['value'])
                if z.get('tipo') == 'end_zone' or any(x in z['value'].lower() for x in ['tienda','caja']): vals.append(z['value'])
    return opts, vals

# --- CALLBACKS DE SISTEMA ---
@app.callback(Output("modal-sync", "is_open", allow_duplicate=True), Input("btn-sync", "n_clicks"), prevent_initial_call=True)
def abrir_modal_carga(n_clicks): return True

@app.callback(
    Output("modal-sync", "is_open", allow_duplicate=True), Output("toast-notificacion", "is_open", allow_duplicate=True),
    Output("toast-notificacion", "children", allow_duplicate=True), Output("toast-notificacion", "icon", allow_duplicate=True), Output("toast-notificacion", "header", allow_duplicate=True),
    Input("modal-sync", "is_open"), State("drop-locs", "value"), State("session-id", "data"), prevent_initial_call=True
)
def ejecutar_sincronizacion(is_open, locs, session_id):
    if not is_open: return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
    ruta_raw = os.path.join('data', 'raw')
    archivo_usuario = os.path.join(ruta_raw, f'dataset_{session_id}.csv')
    try:
        if not os.path.exists(ruta_raw): os.makedirs(ruta_raw, exist_ok=True)
        actualizar_datos_csv(locs if locs else [], archivo_usuario)
        return False, True, "Datos sincronizados correctamente.", "success", "Sincronización finalizada"
    except Exception as e:
        return False, True, f"Error al descargar datos: {str(e)}", "danger", "Error de sincronización"

@app.callback(
    Output("toast-notificacion", "is_open", allow_duplicate=True), Output("toast-notificacion", "children", allow_duplicate=True),
    Output("toast-notificacion", "icon", allow_duplicate=True), Output("toast-notificacion", "header", allow_duplicate=True),
    Input("btn-flush", "n_clicks"), State("session-id", "data"), prevent_initial_call=True
)
def limpiar_memoria(n, session_id):
    archivo_usuario = os.path.join('data', 'raw', f'dataset_{session_id}.csv')
    try:
        if os.path.exists(archivo_usuario): os.remove(archivo_usuario)
        return True, "Memoria limpiada con éxito.", "success", "Flush data"
    except Exception as e: return True, f"Error al limpiar memoria: {str(e)}", "danger", "Error"

# --- LÓGICA REACTIVA DE ANALÍTICA (BI + AUDITORÍA + EJECUTIVO) ---
@app.callback(
    Output("bi-filtro-zona", "data"), Input({"type": "bi-graph", "index": dash.ALL}, "clickData"),
    Input("btn-clear-bi", "n_clicks"), State("bi-filtro-zona", "data"), prevent_initial_call=True
)
def update_click_filter(clickData_list, clear_btn, current_filter):
    if ctx.triggered_id == "btn-clear-bi": return None
    if not ctx.triggered: return current_filter
    val = ctx.triggered[0]['value']
    if val and 'points' in val:
        zona = val['points'][0].get('customdata')
        if zona: return zona
    return current_filter

@app.callback(
    [Output("bi-dynamic-content", "children"), Output("bi-status-visor", "children"), 
     Output("audit-results", "children"), Output("panel-ejecutivo-content", "children")],
    [Input("drop-locs", "value"), Input("tipo-fecha", "value"), Input("date-rango", "start_date"), 
     Input("date-rango", "end_date"), Input("radar-drop-zonas", "value"), Input("bi-comparativa", "value"),
     Input("bi-filtro-zona", "data")],
    [State("session-id", "data")], prevent_initial_call=False
)
def master_reactive_analytics(locs, t_f, sd, ed, zones, comp, cross, s_id):
    # SALIDAS DE SEGURIDAD (Evitan que colapse)
    if not locs: 
        return html.Div(), "Esperando selección de ubicación...", html.Div(), html.Div()
        
    archivo_usuario = os.path.join('data', 'raw', f'dataset_{s_id}.csv')
    if not os.path.exists(archivo_usuario): 
        return html.Div(), "Sincroniza para descargar datos.", html.Div(), html.Div()

    df = pd.read_csv(archivo_usuario)
    if df.empty: 
        return html.Div(), "El dataset está vacío.", html.Div(), html.Div()

    # LECTURA DE DATOS
    df = df[df['location_id'].isin(locs)]
    df['Ubicación'] = df['location_id'].map(mapa_tiendas).fillna('Desconocida')
    df['Zona'] = df['zone_uuid'].map(mapa_zonas).fillna('SinNombre') if 'zone_uuid' in df.columns else 'SinNombre'
    df['fecha'] = pd.to_datetime(df['fecha'])
    
    # 1. INFORME EJECUTIVO (Usa todo el histórico)
    informe_ejecutivo = generar_panel_ejecutivo(df, locs)
    
    # 2. FILTRO TEMPORAL PARA BI Y RADAR
    hoy = datetime.today().date()
    start = end = pd.to_datetime(hoy - timedelta(days=1))
    if t_f == "7d_rel": start, end = pd.to_datetime(hoy - timedelta(days=7)), pd.to_datetime(hoy - timedelta(days=1))
    elif t_f == "28d_rel": start, end = pd.to_datetime(hoy - timedelta(days=28)), pd.to_datetime(hoy - timedelta(days=1))
    elif t_f == "rango" and sd and ed: start, end = pd.to_datetime(sd), pd.to_datetime(ed)
    
    df_actual = df[(df['fecha'] >= start) & (df['fecha'] <= end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))].copy()
    if zones: df_actual = df_actual[df_actual['Zona'].isin(zones)]
    
    df_hist = pd.DataFrame()
    if comp != 'none':
        off = {'wow': 7, 'mom': 28, 'yoy': 365}[comp]
        s_h, e_h = start - pd.Timedelta(days=off), end - pd.Timedelta(days=off)
        df_hist = df[(df['fecha'] >= s_h) & (df['fecha'] <= e_h + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))].copy()
        if zones: df_hist = df_hist[df_hist['Zona'].isin(zones)]

    df_bi = df_actual.copy()
    df_bi_hist = df_hist.copy()
    if 'dwell_time' in df_bi.columns: df_bi['dwell_time'] /= 60.0
    if not df_bi_hist.empty and 'dwell_time' in df_bi_hist.columns: df_bi_hist['dwell_time'] /= 60.0

    comparativa_txt = {'wow': 'vs. Semana Anterior', 'mom': 'vs. Mes Anterior', 'yoy': 'vs. Año Anterior', 'none': ''}[comp]
    visor = html.Div([
        html.Span([html.I(className="fas fa-calendar-day me-2"), f"{start.strftime('%d %b')} - {end.strftime('%d %b')}"], className="badge bg-white text-primary me-2 shadow-sm fs-6"),
        html.Span([html.I(className="fas fa-layer-group me-2"), f"{len(zones) if zones else 'Todas las'} Zonas"], className="badge bg-white text-secondary me-2 shadow-sm fs-6"),
        html.Span(comparativa_txt, className="badge bg-primary text-white shadow-sm fs-6") if comparativa_txt else None,
        html.Span(f" • Filtrando por: {cross}", className="ms-2 text-danger fw-bold small") if cross else None
    ])

    bi_content = generar_panel_bi_completo(df_bi, df_bi_hist, comp, cross)
    audit_content = generar_tabla_auditoria(df_actual) if not df_actual.empty else dbc.Alert("No hay datos para el radar en estas fechas.", color="info", className="rounded-4")

    return bi_content, visor, audit_content, informe_ejecutivo

@app.callback(
    Output("modal-bi-fullscreen", "is_open"), Output("modal-bi-graph", "figure"), Output("modal-bi-title", "children"),
    Input({"type": "btn-expand", "index": dash.ALL}, "n_clicks"), State({"type": "bi-graph", "index": dash.ALL}, "figure"),
    State({"type": "bi-graph", "index": dash.ALL}, "id"), prevent_initial_call=True
)
def expandir_grafico(n_clicks_list, figures, ids):
    if not ctx.triggered: return dash.no_update
    trigger_val = ctx.triggered[0]['value']
    if not trigger_val: return dash.no_update
    trigger_id = ctx.triggered_id
    if not trigger_id: return dash.no_update
    index_buscado = trigger_id['index']
    for fig, item_id in zip(figures, ids):
        if item_id['index'] == index_buscado:
            titulo = fig['layout']['title']['text'] if 'title' in fig['layout'] else "Análisis en detalle"
            fig_copy = go.Figure(fig)
            fig_copy.update_layout(height=None, margin=dict(t=50, b=80, l=40, r=20))
            return True, fig_copy, titulo
    return dash.no_update

# --- EXCEL ---
@app.callback(
    Output("download-excel", "data"), Output("error-msg", "children", allow_duplicate=True), 
    Input("btn-descargar", "n_clicks"), State("drop-locs", "value"), State("tipo-fecha", "value"), 
    State("date-rango", "start_date"), State("date-rango", "end_date"), State("date-dia", "date"),
    State("kpis-oficiales", "value"), State("tipo-reporte", "value"), State("session-id", "data"), prevent_initial_call=True
)
def generar_excel(n_clicks, locs, tipo_fecha, start_rango, end_rango, dia_unico, kpis_oficiales, tipo_reporte, session_id):
    archivo_usuario = os.path.join('data', 'raw', f'dataset_{session_id}.csv')
    if not os.path.exists(archivo_usuario): return dash.no_update, "Sincroniza los datos primero."
    df_completo = pd.read_csv(archivo_usuario)
    if locs: df_completo = df_completo[df_completo['location_id'].isin(locs)]
    df_completo['Ubicación'] = df_completo['location_id'].map(mapa_tiendas).fillna('Desconocida')
    df_completo['Zona'] = df_completo['zone_uuid'].map(mapa_zonas).fillna('SinNombre') if 'zone_uuid' in df_completo.columns else 'SinNombre'
    df_completo['fecha'] = pd.to_datetime(df_completo['fecha'])

    res = filtrar_dataframe_fechas(df_completo, tipo_fecha, start_rango, end_rango, dia_unico)
    if res[0] is None: return dash.no_update, res[1]
    df_filt, start, end = res

    df_filt = df_filt[~df_filt['Zona'].str.contains('Extra', case=False, na=False)]
    df_filt['Día semana'] = pd.Categorical(df_filt['fecha'].dt.dayofweek.map(dias_semana_es), categories=orden_dias, ordered=True)
    if 'dwell_time' in df_filt.columns: df_filt['dwell_time'] /= 60.0
    df_filt['Día del periodo'] = (df_filt['fecha'] - start).dt.days
    df_filt['Semana del periodo'] = "Semana " + ((df_filt['Día del periodo'] // 7) + 1).astype(str)

    try:
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='xlsxwriter')
        if tipo_reporte == "embudos": generar_excel_embudos(df_filt, writer, writer.book)
        else: generar_excel_operativo(df_filt, writer, writer.book, kpis_oficiales)
        writer.close()
        output.seek(0)
        return dcc.send_bytes(output.getvalue(), f"Reporte_{tipo_reporte}.xlsx"), ""
    except Exception as e:
        return dash.no_update, f"Error generando excel: {str(e)}"

if __name__ == "__main__":
    app.run(debug=True, port=8051)