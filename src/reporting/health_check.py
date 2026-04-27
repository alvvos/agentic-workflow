import os
import json
import pandas as pd
from dash import html
import dash_bootstrap_components as dbc
from datetime import timedelta
import holidays
from src.data_processing.data_radar import obtener_info_ubicacion, obtener_clima_historico

festivos_espana = holidays.ES(years=[2024, 2025, 2026])
dias_semana_es = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
meses_es = {1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril', 5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto', 9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'}

def obtener_zonas_validas(ruta_json='src/data/todas_las_ubicaciones.json'):
    zonas_validas = set()
    if os.path.exists(ruta_json):
        try:
            with open(ruta_json, 'r', encoding='utf-8') as f:
                datos = json.load(f)
                for org in datos:
                    for loc in org.get('locations', []):
                        for z in loc.get('zones', []):
                            tipo = z.get('zoneType', '').lower()
                            if tipo == 'last_zone':
                                zonas_validas.add(z.get('zoneName', 'SinNombre'))
        except Exception: pass
    return zonas_validas

def formatear_fecha(fecha_obj):
    dia_sem = dias_semana_es[fecha_obj.weekday()]
    return f"{dia_sem} {fecha_obj.strftime('%d/%m')}"

def calcular_delta(actual, anterior):
    if anterior == 0 or pd.isna(anterior): return 0
    return ((actual - anterior) / anterior) * 100

def evaluar_periodo_zona(df_zona, fecha_max, dias_ventana):
    fecha_min = fecha_max - timedelta(days=dias_ventana - 1)
    df_periodo = df_zona[(df_zona['fecha_dt'] >= fecha_min) & (df_zona['fecha_dt'] <= fecha_max)]
    
    fecha_max_ant = fecha_min - timedelta(days=1)
    fecha_min_ant = fecha_max_ant - timedelta(days=dias_ventana - 1)
    df_anterior = df_zona[(df_zona['fecha_dt'] >= fecha_min_ant) & (df_zona['fecha_dt'] <= fecha_max_ant)]
    
    res = {
        'visitantes': df_periodo['unique_visitors'].sum() if 'unique_visitors' in df_periodo else 0,
        'estancia': df_periodo['dwell_time'].mean() / 60 if 'dwell_time' in df_periodo else 0,
    }
    ant = {
        'visitantes': df_anterior['unique_visitors'].sum() if 'unique_visitors' in df_anterior else 0,
        'estancia': df_anterior['dwell_time'].mean() / 60 if 'dwell_time' in df_anterior else 0,
    }
    deltas = {k: calcular_delta(res[k], ant[k]) for k in res.keys()}
    
    dias_act = df_periodo.groupby('fecha_dt')['unique_visitors'].sum().reset_index()
    
    return res, ant, deltas, fecha_min, fecha_max, fecha_min_ant, fecha_max_ant, dias_act

def obtener_dia_extremo(dias_act, tipo, clima):
    if dias_act.empty: return ""
    
    if tipo == 'max':
        idx = dias_act['unique_visitors'].idxmax()
        texto_base = "El registro máximo de afluencia corresponde al"
    else:
        idx = dias_act['unique_visitors'].idxmin()
        texto_base = "El registro mínimo de afluencia corresponde al"
        
    dia_row = dias_act.loc[idx]
    fecha_extrema = dia_row['fecha_dt']
    volumen = dia_row['unique_visitors']
    
    str_fecha = formatear_fecha(fecha_extrema)
    fecha_str = fecha_extrema.strftime('%Y-%m-%d')
    
    coincidencias = []
    if fecha_extrema in festivos_espana:
        coincidencias.append(f"festividad de {festivos_espana.get(fecha_extrema)}")
        
    clima_dia = clima.get(fecha_str, {})
    precip = clima_dia.get('precip', 0)
    if precip > 2:
        coincidencias.append("precipitaciones")
        
    temp_max = clima_dia.get('tmax', clima_dia.get('temp_max', clima_dia.get('temperature_2m_max', 0)))
    if temp_max > 30:
        coincidencias.append("temperaturas elevadas")
        
    texto_final = f"{texto_base} {str_fecha} ({volumen:,.0f} visitantes)"
    if coincidencias:
        texto_final += f", jornada coincidente con {' y '.join(coincidencias)}"
        
    return texto_final

def generar_semaforo(color_activo):
    colores = {'rojo': '#e74c3c', 'ambar': '#f1c40f', 'verde': '#27ae60'}
    return html.Div([
        html.Div(style={"width": "18px", "height": "18px", "borderRadius": "50%", "backgroundColor": colores['rojo'], "opacity": '1' if color_activo == 'rojo' else '0.2', "margin": "0 4px"}),
        html.Div(style={"width": "18px", "height": "18px", "borderRadius": "50%", "backgroundColor": colores['ambar'], "opacity": '1' if color_activo == 'ambar' else '0.2', "margin": "0 4px"}),
        html.Div(style={"width": "18px", "height": "18px", "borderRadius": "50%", "backgroundColor": colores['verde'], "opacity": '1' if color_activo == 'verde' else '0.2', "margin": "0 4px"})
    ], className="d-flex bg-dark p-2 rounded-pill d-inline-flex mb-2 shadow-sm")

def crear_lista_iconos(lista, icon_class, color_class, empty_msg):
    if not lista: return html.P(empty_msg, className="text-muted small ms-4")
    return html.Ul([html.Li([html.I(className=f"{icon_class} {color_class} me-3 mt-1"), html.Span(item, className="text-secondary text-justify")], className="d-flex align-items-start mb-3 lh-base") for item in lista], className="list-unstyled mb-0")

def generar_mensajes_salud(df, ubi, zonas_seleccionadas=None):
    if df.empty: return html.Div("Ausencia de datos.", className="text-muted p-4")

    zonas_validas = obtener_zonas_validas()
    if zonas_validas: df = df[df['Zona'].isin(zonas_validas)]
    if zonas_seleccionadas: df = df[df['Zona'].isin(zonas_seleccionadas)]
        
    if df.empty: return html.Div("Ausencia de datos en la selección.", className="text-warning p-4")

    df = df.copy()
    df['fecha_dt'] = pd.to_datetime(df['fecha']).dt.date
    fecha_max = df['fecha_dt'].max()
    
    if pd.isna(fecha_max): return html.Div("Error de formato de fecha.", className="text-danger p-4")

    lat, lon, reg = obtener_info_ubicacion(ubi)
    fecha_inicio_clima = fecha_max - timedelta(days=60)
    clima = obtener_clima_historico(lat, lon, fecha_inicio_clima.strftime('%Y-%m-%d'), fecha_max.strftime('%Y-%m-%d'))

    puntos_globales = 0
    tarjetas_zonas = []
    zonas_presentes = df['Zona'].unique()

    for zona in zonas_presentes:
        df_zona = df[df['Zona'] == zona]
        res_7d, ant_7d, deltas_7d, fmin_7, fmax_7, fmin_ant_7, fmax_ant_7, dias_act_7d = evaluar_periodo_zona(df_zona, fecha_max, 7)
        res_28d, ant_28d, deltas_28d, fmin_28, fmax_28, fmin_ant_28, fmax_ant_28, dias_act_28d = evaluar_periodo_zona(df_zona, fecha_max, 28)

        alza, baja = [], []

        # --- Redacción 7 Días ---
        p_7d_alza = []
        extremos_7d_alza = []
        if deltas_7d['visitantes'] >= 5:
            p_7d_alza.append(f"un incremento de visitantes del {deltas_7d['visitantes']:.1f}% (de {ant_7d['visitantes']:,.0f} a {res_7d['visitantes']:,.0f})")
            puntos_globales += 1
            extremo = obtener_dia_extremo(dias_act_7d, 'max', clima)
            if extremo: extremos_7d_alza.append(extremo)
            
        if deltas_7d['estancia'] >= 5:
            p_7d_alza.append(f"un aumento del tiempo de estancia del {deltas_7d['estancia']:.1f}% (de {ant_7d['estancia']:.1f} min a {res_7d['estancia']:.1f} min)")
            puntos_globales += 1

        if p_7d_alza:
            txt_7_alza = f"Esta última semana ({fmin_7.strftime('%d/%m')} al {fmax_7.strftime('%d/%m')}) comparada con la anterior ({fmin_ant_7.strftime('%d/%m')} al {fmax_ant_7.strftime('%d/%m')}), se registra " + " y ".join(p_7d_alza) + "."
            if extremos_7d_alza: txt_7_alza += " " + " ".join(extremos_7d_alza) + "."
            alza.append(txt_7_alza)

        p_7d_baja = []
        extremos_7d_baja = []
        if deltas_7d['visitantes'] <= -5:
            p_7d_baja.append(f"un descenso de visitantes del {abs(deltas_7d['visitantes']):.1f}% (de {ant_7d['visitantes']:,.0f} a {res_7d['visitantes']:,.0f})")
            puntos_globales -= 1
            extremo = obtener_dia_extremo(dias_act_7d, 'min', clima)
            if extremo: extremos_7d_baja.append(extremo)
            
        if deltas_7d['estancia'] <= -10:
            p_7d_baja.append(f"una disminución del tiempo de estancia del {abs(deltas_7d['estancia']):.1f}% (de {ant_7d['estancia']:.1f} min a {res_7d['estancia']:.1f} min)")
            puntos_globales -= 1

        if p_7d_baja:
            txt_7_baja = f"Esta última semana ({fmin_7.strftime('%d/%m')} al {fmax_7.strftime('%d/%m')}) comparada con la anterior ({fmin_ant_7.strftime('%d/%m')} al {fmax_ant_7.strftime('%d/%m')}), se registra " + " y ".join(p_7d_baja) + "."
            if extremos_7d_baja: txt_7_baja += " " + " ".join(extremos_7d_baja) + "."
            baja.append(txt_7_baja)

        # --- Redacción 28 Días ---
        mes_str = meses_es[fmax_28.month]
        
        p_28d_alza = []
        extremos_28d_alza = []
        if deltas_28d['visitantes'] >= 5:
            p_28d_alza.append(f"un incremento de visitantes del {deltas_28d['visitantes']:.1f}% (de {ant_28d['visitantes']:,.0f} a {res_28d['visitantes']:,.0f})")
            extremo = obtener_dia_extremo(dias_act_28d, 'max', clima)
            if extremo: extremos_28d_alza.append(extremo)
            
        if deltas_28d['estancia'] >= 5:
            p_28d_alza.append(f"un aumento del tiempo de estancia del {deltas_28d['estancia']:.1f}% (de {ant_28d['estancia']:.1f} min a {res_28d['estancia']:.1f} min)")

        if p_28d_alza:
            txt_28_alza = f"Este último mes de {mes_str} ({fmin_28.strftime('%d/%m')} al {fmax_28.strftime('%d/%m')}) contrapuesto con el periodo pasado ({fmin_ant_28.strftime('%d/%m')} al {fmax_ant_28.strftime('%d/%m')}), se registra " + " y ".join(p_28d_alza) + "."
            if extremos_28d_alza: txt_28_alza += " " + " ".join(extremos_28d_alza) + "."
            alza.append(txt_28_alza)

        p_28d_baja = []
        extremos_28d_baja = []
        if deltas_28d['visitantes'] <= -5:
            p_28d_baja.append(f"un descenso de visitantes del {abs(deltas_28d['visitantes']):.1f}% (de {ant_28d['visitantes']:,.0f} a {res_28d['visitantes']:,.0f})")
            extremo = obtener_dia_extremo(dias_act_28d, 'min', clima)
            if extremo: extremos_28d_baja.append(extremo)
            
        if deltas_28d['estancia'] <= -10:
            p_28d_baja.append(f"una disminución del tiempo de estancia del {abs(deltas_28d['estancia']):.1f}% (de {ant_28d['estancia']:.1f} min a {res_28d['estancia']:.1f} min)")

        if p_28d_baja:
            txt_28_baja = f"Este último mes de {mes_str} ({fmin_28.strftime('%d/%m')} al {fmax_28.strftime('%d/%m')}) contrapuesto con el periodo pasado ({fmin_ant_28.strftime('%d/%m')} al {fmax_ant_28.strftime('%d/%m')}), se registra " + " y ".join(p_28d_baja) + "."
            if extremos_28d_baja: txt_28_baja += " " + " ".join(extremos_28d_baja) + "."
            baja.append(txt_28_baja)

        # Construcción de la tarjeta de zona
        tarjeta = dbc.Card(dbc.CardBody([
            html.H6([html.I(className="fas fa-bullseye me-2 text-secondary"), f"ZONA: {zona}"], className="fw-bold mb-3 text-uppercase"),
            dbc.Row([
                dbc.Col([
                    html.P("Variaciones al alza", className="fw-bold text-success mb-2 small text-uppercase"),
                    crear_lista_iconos(alza, "fas fa-arrow-up", "text-success", "Sin variaciones al alza registradas.")
                ], md=6, className="border-end border-light"),
                dbc.Col([
                    html.P("Variaciones a la baja", className="fw-bold text-danger mb-2 small text-uppercase"),
                    crear_lista_iconos(baja, "fas fa-arrow-down", "text-danger", "Sin variaciones a la baja registradas.")
                ], md=6)
            ])
        ]), className="border-0 shadow-sm rounded-4 mb-3 bg-white")
        tarjetas_zonas.append(tarjeta)

    # --- Evaluación del Semáforo Global ---
    if puntos_globales >= 1:
        color_sem = 'verde'
        estado_txt = "Estado actual: Situación favorable"
    elif puntos_globales <= -1:
        color_sem = 'rojo'
        estado_txt = "Estado actual: Situación desfavorable"
    else:
        color_sem = 'ambar'
        estado_txt = "Estado actual: Situación estable"

    # --- CABECERA DE LA PLANTILLA (Solo visible en el PDF final) ---
    zonas_txt = ", ".join(zonas_seleccionadas) if zonas_seleccionadas else "Todas las zonas analíticas"
    fecha_max_str = fecha_max.strftime('%d/%m/%Y')
    
    cabecera_pdf = html.Div([
        dbc.Row([
            dbc.Col([
                html.H2("INFORME DE RENDIMIENTO OPERATIVO", className="fw-bold text-dark mb-1", style={"letterSpacing": "1px"}),
                html.H5(f"UBICACIÓN: {ubi.upper()}", className="text-secondary fw-bold mb-0")
            ], width=8),
            dbc.Col([
                html.P(f"Fecha de emisión: {pd.Timestamp('today').strftime('%d/%m/%Y')}", className="text-end text-muted mb-0 small fw-bold"),
                html.P(f"Datos computados hasta: {fecha_max_str}", className="text-end text-muted mb-0 small")
            ], width=4, className="d-flex flex-column justify-content-center")
        ], className="mb-3"),
        html.P([html.Strong("Segmentación aplicada: "), zonas_txt], className="mb-2 text-dark"),
        html.Hr(style={"borderTop": "3px solid #2c3e50", "opacity": "1"}),
        html.Br()
    ], className="d-none d-print-block") # <- La clase d-print-block lo hace visible solo en el PDF

    # --- ENSAMBLAJE FINAL ---
    return html.Div([
        cabecera_pdf,
        
        dbc.Card(dbc.CardBody([
            html.Div(className="d-flex justify-content-between align-items-center mb-3", children=[
                html.H5("RESUMEN EJECUTIVO SEGMENTADO", className="fw-bold text-muted mb-0 text-uppercase tracking-wide"),
                generar_semaforo(color_sem)
            ]),
            html.H4(estado_txt, className="fw-bold text-dark mb-0")
        ]), className="border-0 shadow-sm rounded-4 bg-light mb-4 border-start border-4", style={"borderLeftColor": "var(--bs-primary) !important"}),
        
        html.Div(tarjetas_zonas),
        
        html.P([html.I(className="fas fa-filter me-1"), " Filtro metodológico aplicado: Exclusión de End Zones (cámaras de salida). Limitado a selección de usuario activa."], className="text-muted small mt-2 border-top pt-2")
    ])

def generar_panel_ejecutivo(df_completo, locs, zonas_sel):
    if df_completo is None or df_completo.empty: return dbc.Alert("Sincroniza los datos.", color="warning", className="rounded-4")
    if not locs: return dbc.Alert("Selecciona una ubicación.", color="info", className="rounded-4")

    paneles = []
    for ubi in df_completo[df_completo['location_id'].isin(locs)]['Ubicación'].unique():
        df_ubi = df_completo[df_completo['Ubicación'] == ubi]
        paneles.append(html.Div([generar_mensajes_salud(df_ubi, ubi, zonas_sel)]))
    return html.Div(paneles)