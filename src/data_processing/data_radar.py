import pandas as pd
from dash import html
import dash_bootstrap_components as dbc
import holidays
from datetime import timedelta, date
import calendar
from collections import defaultdict
import hashlib

years_list = [2024, 2025, 2026]
es_national = holidays.ES(years=years_list)
fechas_info = defaultdict(lambda: defaultdict(list))

for dt, name in es_national.items():
    fechas_info[dt][name].append("Nacional")

for region in holidays.ES.subdivisions:
    es_region = holidays.ES(subdiv=region, years=years_list)
    for dt, name in es_region.items():
        if dt not in es_national or es_national.get(dt) != name:
            fechas_info[dt][name].append(region)

festivos_espana_dict = {}
for dt, dict_nombres in fechas_info.items():
    nombres_finales = []
    for name, regiones in dict_nombres.items():
        if "Nacional" in regiones:
            nombres_finales.append(f"{name} (Nacional)")
        else:
            if len(regiones) > 4:
                nombres_finales.append(f"{name} ({len(regiones)} CCAA)")
            else:
                nombres_finales.append(f"{name} ({', '.join(regiones)})")
    festivos_espana_dict[dt] = " / ".join(nombres_finales)
# --------------------------------------------------------------------

# --- SIMULADOR DETERMINISTA DE CLIMA PENINSULAR (FONT AWESOME) ---
def obtener_clima_espana(fecha):
    hash_val = int(hashlib.md5(str(fecha).encode()).hexdigest(), 16)
    
    mod = hash_val % 10
    if mod <= 3:
        return "fas fa-sun", "#f39c12", "Soleado general"
    elif mod <= 6:
        return "fas fa-cloud-sun", "#f39c12", "Poco nuboso"
    elif mod <= 8:
        return "fas fa-cloud", "#7f8c8d", "Nublado"
    else:
        return "fas fa-cloud-showers-heavy", "#3498db", "Lluvias aisladas"
# --------------------------------------------------------------------

def generar_tabla_auditoria(df_filt):
    if df_filt.empty:
        return dbc.Alert("No hay datos para procesar en este periodo.", color="warning", style={'fontSize': '16px'})

    meses_es = {1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio', 
                7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'}

    leyenda = html.Div([
        html.Strong("Leyenda de estados: ", style={'marginRight': '12px'}),
        html.Span([html.I(className="fas fa-check-circle", style={'marginRight': '6px'}), "Operación normal"], style={'marginRight': '18px', 'color': '#155724'}),
        html.Span([html.I(className="fas fa-exclamation-triangle", style={'marginRight': '6px'}), "Posible inactividad"], style={'marginRight': '18px', 'color': '#856404'}),
        html.Span([html.I(className="fas fa-times-circle", style={'marginRight': '6px'}), "Anomalía de flujo"], style={'marginRight': '18px', 'color': '#721c24'}),
        html.Span([html.I(className="fas fa-calendar-alt", style={'marginRight': '6px'}), "Día Festivo"], style={'color': '#004085'})
    ], style={'padding': '16px', 'backgroundColor': '#f8f9fa', 'border': '1px solid #dee2e6', 'borderRadius': '6px', 'marginBottom': '25px', 'fontSize': '16px'})

    paneles_ubicacion = []

    for ubi in df_filt['Ubicación'].unique():
        df_ubi = df_filt[df_filt['Ubicación'] == ubi].copy()
        df_ubi['fecha_dt'] = pd.to_datetime(df_ubi['fecha']).dt.date
        
        df_ubi['year_month'] = df_ubi['fecha_dt'].apply(lambda x: (x.year, x.month))
        meses_presentes = sorted(df_ubi['year_month'].unique())
        
        tabs_meses = []

        for (year, month) in meses_presentes:
            nombre_mes = f"{meses_es[month]} {year}"
            
            primer_dia = date(year, month, 1)
            ultimo_dia = date(year, month, calendar.monthrange(year, month)[1])
            lunes_inicial = primer_dia - timedelta(days=primer_dia.weekday())
            domingo_final = ultimo_dia + timedelta(days=6 - ultimo_dia.weekday())

            dias_totales = (domingo_final - lunes_inicial).days + 1
            rango_fechas = [lunes_inicial + timedelta(days=i) for i in range(dias_totales)]

            celdas_calendario = []
            nombres_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

            cabeceras = [html.Div(dia, style={'textAlign': 'center', 'fontWeight': 'bold', 'padding': '12px', 'backgroundColor': '#f8f9fa', 'border': '1px solid #dee2e6', 'fontSize': '15px'}) for dia in nombres_dias]

            for fecha_actual in rango_fechas:
                if fecha_actual.month != month:
                    celdas_calendario.append(html.Div(style={'backgroundColor': '#f8f9fa', 'border': '1px solid #e9ecef', 'minHeight': '140px', 'opacity': '0.5', 'borderRadius': '6px'}))
                    continue

                es_festivo = fecha_actual in festivos_espana_dict
                df_dia = df_ubi[df_ubi['fecha_dt'] == fecha_actual]
                
                icon_class, icon_color, desc_clima = obtener_clima_espana(fecha_actual)

                header_elements = [
                    html.Div([
                        html.I(className=icon_class, title=desc_clima, style={'color': icon_color, 'fontSize': '18px', 'marginRight': '8px'}),
                        html.Span(str(fecha_actual.day), style={'fontSize': '16px', 'fontWeight': 'bold'})
                    ], style={'display': 'flex', 'alignItems': 'center'})
                ]
                
                if es_festivo:
                    fest_name = festivos_espana_dict[fecha_actual]
                    fest_html = html.Span(fest_name, style={'fontSize': '11px', 'color': '#004085', 'fontWeight': 'bold', 'textAlign': 'right', 'lineHeight': '1.1', 'maxWidth': '70%'})
                    header_elements.append(fest_html)

                if df_dia.empty:
                    header_bg = '#cce5ff' if es_festivo else 'rgba(0,0,0,0.04)'
                    header_color = '#004085' if es_festivo else 'inherit'
                    
                    celdas_calendario.append(html.Div([
                        html.Div(header_elements, style={'padding': '8px 10px', 'borderBottom': '1px solid #dee2e6', 'backgroundColor': header_bg, 'color': header_color, 'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between'}),
                        html.Div("Sin datos registrados.", style={'padding': '10px', 'fontSize': '14px', 'color': '#6c757d'})
                    ], style={'backgroundColor': '#ffffff', 'border': '1px solid #dee2e6', 'minHeight': '140px', 'borderRadius': '6px', 'overflow': 'hidden'}))
                    continue

                inactivos = []
                errores_mat = []
                errores_fis = []

                for _, row in df_dia.iterrows():
                    zona = row.get('Zona', '').lower()
                    tv = row.get('total_visits', 0)
                    uv = row.get('unique_visitors', 0)
                    nv = row.get('new_visitors', 0)
                    dt = row.get('dwell_time', 0)

                    if dt == 0 and (tv == 0 or uv == 0):
                        inactivos.append(zona)
                    elif uv > tv:
                        errores_mat.append(f"más únicos que totales en {zona}")
                    elif nv > uv:
                        errores_mat.append(f"más nuevos que únicos en {zona}")
                    elif dt > 0 and tv == 0:
                        errores_mat.append(f"estancia sin visitas en {zona}")

                df_agrupado = df_dia.groupby('Zona')['unique_visitors'].sum().reset_index()
                zonas_dict = dict(zip(df_agrupado['Zona'].str.lower(), df_agrupado['unique_visitors']))
                caja_val = sum(v for k, v in zonas_dict.items() if 'caja' in k)
                tienda_val = sum(v for k, v in zonas_dict.items() if 'tienda' in k)
                calle_val = sum(v for k, v in zonas_dict.items() if 'calle' in k or 'exterior' in k)

                if caja_val > 0 and calle_val > 0 and caja_val > calle_val:
                    errores_fis.append("más gente en caja que en puerta")
                if caja_val > 0 and tienda_val > 0 and caja_val > tienda_val:
                    errores_fis.append("más visitantes en caja que en tienda")

                mensajes = []
                estado_dia = 'success' 

                if inactivos:
                    estado_dia = 'warning'
                    zonas_str = ", ".join(set(inactivos))
                    mensajes.append((f"Nodo posiblemente inactivo en: {zonas_str}.", 'warning', "fas fa-exclamation-triangle"))
                else:
                    mensajes.append(("Todos los sensores operativos.", 'success', "fas fa-check-circle"))

                if errores_mat or errores_fis:
                    estado_dia = 'danger'
                    for err in set(errores_mat + errores_fis):
                        mensajes.append((err.capitalize() + ".", 'danger', "fas fa-times-circle"))
                else:
                    mensajes.append(("Flujo y datos coherentes.", 'success', "fas fa-check-circle"))

                bg_color = '#ffffff'
                border_color = '#dee2e6'
                if estado_dia == 'danger':
                    border_color = '#f5c6cb'
                    bg_color = '#f8d7da'
                elif estado_dia == 'warning':
                    border_color = '#ffeeba'
                    bg_color = '#fff3cd'
                elif estado_dia == 'success':
                    border_color = '#c3e6cb'
                    bg_color = '#d4edda'

                header_bg = '#cce5ff' if es_festivo else 'rgba(0,0,0,0.04)'
                header_border_color = '#b8daff' if es_festivo else border_color
                header_color = '#004085' if es_festivo else 'inherit'

                celda_content = [
                    html.Div(header_elements, style={
                        'padding': '8px 10px', 
                        'borderBottom': f'1px solid {header_border_color}', 
                        'backgroundColor': header_bg,
                        'display': 'flex',
                        'alignItems': 'center',
                        'justifyContent': 'space-between',
                        'color': header_color
                    })
                ]

                lista_html = []
                for msg, tipo, icon in mensajes:
                    color_texto = '#155724' if tipo == 'success' else ('#856404' if tipo == 'warning' else '#721c24')
                    lista_html.append(html.Div([
                        html.I(className=icon, style={'marginRight': '6px'}),
                        html.Span(msg)
                    ], style={'fontSize': '14px', 'color': color_texto, 'marginBottom': '5px', 'lineHeight': '1.3'}))

                celda_content.append(html.Div(lista_html, style={'padding': '10px'}))
                celdas_calendario.append(html.Div(celda_content, style={'backgroundColor': bg_color, 'border': f'1px solid {border_color}', 'minHeight': '140px', 'borderRadius': '6px', 'overflow': 'hidden'}))

            grilla_calendario = html.Div(cabeceras + celdas_calendario, style={
                'display': 'grid',
                'gridTemplateColumns': 'repeat(7, 1fr)',
                'gap': '10px',
                'marginBottom': '10px'
            })
            
            tabs_meses.append(dbc.Tab(html.Div(grilla_calendario, className="pt-4"), label=nombre_mes, tab_id=nombre_mes))

        if tabs_meses:
            slide_meses = dbc.Tabs(tabs_meses, active_tab=tabs_meses[0].tab_id, className="mt-3")
        else:
            slide_meses = html.Div()

        paneles_ubicacion.append(html.Div([
            html.H3(f"📍 Ubicación: {ubi}", className="fw-bold mb-3 mt-4 text-secondary"),
            slide_meses
        ], className="mb-5"))

    return html.Div([
        html.H2("Sistema de alarmas", className="fw-bold mb-2 text-primary"),
        html.P("Calendario consolidado con eventos de flujo operativo, avisos y climatología diaria.", className="text-muted mb-4", style={'fontSize': '16px'}),
        leyenda
    ] + paneles_ubicacion)