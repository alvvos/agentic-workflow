import pandas as pd
from dash import html
import dash_bootstrap_components as dbc
from datetime import timedelta
import holidays
from src.data_processing.data_radar import obtener_info_ubicacion, obtener_clima_historico

festivos_espana = holidays.ES(years=[2024, 2025, 2026])

def calcular_delta(actual, anterior):
    if anterior == 0 or pd.isna(anterior): return 0
    return ((actual - anterior) / anterior) * 100

def evaluar_periodo(df, fecha_max, dias_ventana):
    fecha_min = fecha_max - timedelta(days=dias_ventana - 1)
    df_periodo = df[(df['fecha_dt'] >= fecha_min) & (df['fecha_dt'] <= fecha_max)]
    
    fecha_max_ant = fecha_min - timedelta(days=1)
    fecha_min_ant = fecha_max_ant - timedelta(days=dias_ventana - 1)
    df_anterior = df[(df['fecha_dt'] >= fecha_min_ant) & (df['fecha_dt'] <= fecha_max_ant)]
    
    res = {
        'visitas': df_periodo['total_visits'].sum() if 'total_visits' in df_periodo else 0,
        'unicos': df_periodo['unique_visitors'].sum() if 'unique_visitors' in df_periodo else 0,
        'nuevos': df_periodo['new_visitors'].sum() if 'new_visitors' in df_periodo else 0,
        'estancia': df_periodo['dwell_time'].mean() / 60 if 'dwell_time' in df_periodo else 0,
    }
    
    ant = {
        'visitas': df_anterior['total_visits'].sum() if 'total_visits' in df_anterior else 0,
        'unicos': df_anterior['unique_visitors'].sum() if 'unique_visitors' in df_anterior else 0,
        'nuevos': df_anterior['new_visitors'].sum() if 'new_visitors' in df_anterior else 0,
        'estancia': df_anterior['dwell_time'].mean() / 60 if 'dwell_time' in df_anterior else 0,
    }
    
    deltas = {k: calcular_delta(res[k], ant[k]) for k in res.keys()}
    return res, deltas, df_periodo

def generar_mensajes_salud(df, ubi):
    if df.empty:
        return html.Div("No hay datos suficientes para generar un diagnóstico.", className="text-muted")

    df = df.copy()
    df['fecha_dt'] = pd.to_datetime(df['fecha']).dt.date
    fecha_max = df['fecha_dt'].max()
    
    if pd.isna(fecha_max): return html.Div("Error en fechas.", className="text-danger")

    res_7d, deltas_7d, df_7d = evaluar_periodo(df, fecha_max, 7)
    res_28d, deltas_28d, df_28d = evaluar_periodo(df, fecha_max, 28)
    
    año_actual = fecha_max.year
    df_ytd = df[pd.to_datetime(df['fecha']).dt.year == año_actual]
    
    # --- CORRECCIÓN: Conversión segura para restar 1 año en Pandas ---
    fecha_max_ant = (pd.to_datetime(fecha_max) - pd.DateOffset(years=1)).date()
    df_ytd_ant = df[(pd.to_datetime(df['fecha']).dt.year == año_actual - 1) & (df['fecha_dt'] <= fecha_max_ant)]
    # -------------------------------------------------------------------
    
    delta_ytd_visitas = calcular_delta(df_ytd['total_visits'].sum(), df_ytd_ant['total_visits'].sum()) if not df_ytd_ant.empty else 0

    green_flags = []
    red_flags = []
    info_context = []

    # REGLAS DETERMINISTAS (7 DÍAS)
    if deltas_7d['unicos'] > 5:
        green_flags.append(f"Fuerte captación a corto plazo: Los visitantes únicos han subido un {deltas_7d['unicos']:.1f}% esta semana.")
    elif deltas_7d['unicos'] < -5:
        red_flags.append(f"Alerta de tráfico semanal: Caída del {abs(deltas_7d['unicos']):.1f}% en visitantes únicos respecto a la semana anterior.")

    if deltas_7d['estancia'] > 10:
        green_flags.append(f"Retención en alza: El público pasa un {deltas_7d['estancia']:.1f}% más de tiempo en la ubicación estos últimos 7 días.")
    elif deltas_7d['estancia'] < -10:
        red_flags.append(f"Fugas rápidas: El tiempo medio de estancia se ha desplomado un {abs(deltas_7d['estancia']):.1f}% recientemente.")

    # REGLAS DETERMINISTAS (28 DÍAS)
    if deltas_28d['nuevos'] > 5:
        green_flags.append(f"Expansión de audiencia: En los últimos 28 días, el volumen de usuarios nuevos creció un {deltas_28d['nuevos']:.1f}%.")
    elif deltas_28d['nuevos'] < -10:
        red_flags.append(f"Estancamiento: Dificultad para atraer público nuevo este mes (descenso del {abs(deltas_28d['nuevos']):.1f}%).")

    if deltas_28d['visitas'] > 0 and deltas_28d['unicos'] < 0:
        red_flags.append("Falsa sensación de volumen: Hay más visitas totales este mes, pero menos personas únicas (aumento de duplicidades).")

    # CONTEXTO
    lat, lon, reg = obtener_info_ubicacion(ubi)
    clima = obtener_clima_historico(lat, lon, (fecha_max - timedelta(days=6)).strftime('%Y-%m-%d'), fecha_max.strftime('%Y-%m-%d'))
    
    dias_lluvia = sum(1 for d, vals in clima.items() if vals.get('precip', 0) > 2)
    if dias_lluvia > 0 and deltas_7d['visitas'] < 0:
        info_context.append(f"La caída semanal coincide con {dias_lluvia} días de precipitaciones relevantes, lo que explica gran parte del descenso.")
        
    dias_festivos = sum(1 for d in df_7d['fecha_dt'].unique() if d in festivos_espana)
    if dias_festivos > 0:
        info_context.append(f"La semana analizada incluye {dias_festivos} día(s) festivo(s), alterando los flujos habituales.")

    # DIAGNÓSTICO
    puntuacion = len(green_flags) - len(red_flags)
    if puntuacion >= 1:
        salud, color_salud = "SALUDABLE", "text-success"
        texto_gen = f"La ubicación {ubi} muestra una inercia positiva. Los indicadores clave de atracción y retención están mejorando frente a sus periodos equivalentes anteriores."
    elif puntuacion <= -1:
        salud, color_salud = "EN RIESGO", "text-danger"
        texto_gen = f"La ubicación {ubi} requiere atención. Se están registrando contracciones operativas en el tráfico o en la capacidad de retención."
    else:
        salud, color_salud = "ESTABLE", "text-warning"
        texto_gen = f"La ubicación {ubi} mantiene una tendencia plana, sin variaciones drásticas frente al histórico reciente."

    if delta_ytd_visitas != 0:
        texto_gen += f" En el acumulado del año (YTD), el tráfico va un {abs(delta_ytd_visitas):.1f}% por {'encima' if delta_ytd_visitas > 0 else 'debajo'} del año pasado."

    ui_greens = [html.Li([html.I(className="fas fa-check-circle text-success me-2"), f]) for f in green_flags] if green_flags else [html.Li("No hay hitos positivos destacables.", className="text-muted")]
    ui_reds = [html.Li([html.I(className="fas fa-exclamation-circle text-danger me-2"), f]) for f in red_flags] if red_flags else [html.Li("No se han detectado caídas críticas.", className="text-muted")]
    ui_ctx = [html.Li([html.I(className="fas fa-info-circle text-info me-2"), f]) for f in info_context]

    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.H6("DIAGNÓSTICO GENERAL", className="fw-bold text-muted mb-1"),
                html.H3(salud, className=f"fw-bold {color_salud} mb-3"),
                html.P(texto_gen, className="fs-5 text-dark")
            ], className="bg-light p-4 rounded-4 mb-4 border"),
            
            dbc.Row([
                dbc.Col([
                    html.H5("Green Flags", className="fw-bold text-success mb-3"),
                    html.Ul(ui_greens, className="list-unstyled lh-lg")
                ], md=6, className="border-end"),
                dbc.Col([
                    html.H5("Red Flags", className="fw-bold text-danger mb-3"),
                    html.Ul(ui_reds, className="list-unstyled lh-lg")
                ], md=6)
            ]),
            
            html.Div([
                html.Hr(),
                html.H6("Factores Exógenos", className="fw-bold text-muted mb-2"),
                html.Ul(ui_ctx, className="list-unstyled text-secondary small") if ui_ctx else html.P("Sin alteraciones exógenas relevantes (clima/festivos).", className="text-muted small")
            ]) if info_context else html.Div()
        ])
    ], className="border-0 shadow-sm rounded-4 bg-white mb-4")

def generar_panel_ejecutivo(df_completo, locs):
    if df_completo is None or df_completo.empty:
        return dbc.Alert("Sincroniza los datos para visualizar el resumen ejecutivo.", color="warning", className="rounded-4")

    if not locs:
        return dbc.Alert("Selecciona una ubicación en el menú lateral.", color="info", className="rounded-4")

    paneles = []
    for ubi in df_completo[df_completo['location_id'].isin(locs)]['Ubicación'].unique():
        df_ubi = df_completo[df_completo['Ubicación'] == ubi]
        paneles.append(html.Div([
            html.H4([html.I(className="fas fa-file-contract me-2 text-primary"), f"Informe Ejecutivo: {ubi}"], className="fw-bold mb-4 mt-3 text-secondary"),
            generar_mensajes_salud(df_ubi, ubi)
        ]))

    return html.Div(paneles)