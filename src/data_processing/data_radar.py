import pandas as pd
from dash import html
import dash_bootstrap_components as dbc
import holidays
from datetime import timedelta, date
import calendar
import requests
import json
import os

def obtener_info_ubicacion(nombre_ubi, ruta_json='src/data/todas_las_ubicaciones.json'):
    lat, lon, region_code = 40.4168, -3.7038, 'MD'
    if os.path.exists(ruta_json):
        try:
            with open(ruta_json, 'r', encoding='utf-8') as f:
                datos = json.load(f)
                for org in datos:
                    for loc in org.get('locations', []):
                        if loc.get('name') == nombre_ubi:
                            return loc.get('lat', lat), loc.get('lon', lon), loc.get('region_code', region_code)
        except Exception: pass
    return lat, lon, region_code

def obtener_clima_historico(lat, lon, fecha_inicio, fecha_fin):
    clima_dict = {}
    url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={fecha_inicio}&end_date={fecha_fin}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=Europe%2FMadrid"
    try:
        respuesta = requests.get(url).json()
        if 'daily' in respuesta:
            for i, dia_str in enumerate(respuesta['daily']['time']):
                clima_dict[dia_str] = {
                    'tmax': respuesta['daily']['temperature_2m_max'][i],
                    'tmin': respuesta['daily']['temperature_2m_min'][i],
                    'precip': respuesta['daily']['precipitation_sum'][i]
                }
    except Exception: pass
    return clima_dict

def generar_tabla_auditoria(df_filt):
    if df_filt.empty:
        return html.Div()

    meses_es = {1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio', 
                7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'}

    leyenda = html.Div([
        html.Strong("Estado de los Nodos:", className="me-3 text-secondary"),
        html.Span([html.I(className="fas fa-check-circle me-1"), "Normal"], className="badge bg-success bg-opacity-10 text-success border border-success border-opacity-25 rounded-pill px-3 py-2 me-2"),
        html.Span([html.I(className="fas fa-exclamation-triangle me-1"), "Aviso"], className="badge bg-warning bg-opacity-10 text-warning border border-warning border-opacity-25 rounded-pill px-3 py-2 me-2"),
        html.Span([html.I(className="fas fa-times-circle me-1"), "Anomalía"], className="badge bg-danger bg-opacity-10 text-danger border border-danger border-opacity-25 rounded-pill px-3 py-2 me-2"),
        html.Span([html.I(className="fas fa-calendar-alt me-1"), "Festivo"], className="badge bg-primary bg-opacity-10 text-primary border border-primary border-opacity-25 rounded-pill px-3 py-2")
    ], className="p-3 bg-white border-0 shadow-sm rounded-4 mb-4 d-flex align-items-center flex-wrap")

    paneles_ubicacion = []

    for ubi in df_filt['Ubicación'].unique():
        df_ubi = df_filt[df_filt['Ubicación'] == ubi].copy()
        df_ubi['fecha_dt'] = pd.to_datetime(df_ubi['fecha']).dt.date
        df_ubi['year_month'] = df_ubi['fecha_dt'].apply(lambda x: (x.year, x.month))
        
        lat, lon, region_code = obtener_info_ubicacion(ubi)
        años_presentes = list(df_ubi['fecha_dt'].apply(lambda x: x.year).unique())
        
        try: festivos_locales = holidays.Spain(subdiv=region_code, years=años_presentes)
        except: festivos_locales = holidays.Spain(years=años_presentes)
            
        fecha_min_str, fecha_max_str = df_ubi['fecha_dt'].min().strftime('%Y-%m-%d'), df_ubi['fecha_dt'].max().strftime('%Y-%m-%d')
        clima_datos = obtener_clima_historico(lat, lon, fecha_min_str, fecha_max_str)

        tabs_meses = []
        for (year, month) in sorted(df_ubi['year_month'].unique()):
            nombre_mes = f"{meses_es[month]} {year}"
            
            primer_dia = date(year, month, 1)
            ultimo_dia = date(year, month, calendar.monthrange(year, month)[1])
            lunes_inicial = primer_dia - timedelta(days=primer_dia.weekday())
            dias_totales = ((ultimo_dia + timedelta(days=6 - ultimo_dia.weekday())) - lunes_inicial).days + 1
            rango_fechas = [lunes_inicial + timedelta(days=i) for i in range(dias_totales)]

            cabeceras = [html.Div(dia, className="text-center fw-bold py-2 text-secondary bg-light rounded-top-3 small text-uppercase") 
                         for dia in ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']]
            
            celdas_calendario = []
            for fecha_actual in rango_fechas:
                if fecha_actual.month != month:
                    celdas_calendario.append(html.Div(className="bg-light opacity-50 rounded-4 border-0", style={'minHeight': '140px'}))
                    continue

                es_festivo = fecha_actual in festivos_locales
                df_dia = df_ubi[df_ubi['fecha_dt'] == fecha_actual]
                fecha_str = fecha_actual.strftime('%Y-%m-%d')
                
                tmax, tmin, precip = None, None, 0
                if fecha_str in clima_datos:
                    tmax, tmin, precip = clima_datos[fecha_str].get('tmax'), clima_datos[fecha_str].get('tmin'), clima_datos[fecha_str].get('precip', 0)

                icon_class, icon_color, desc_clima = "fas fa-cloud-sun", "#95a5a6", "Poco nuboso"
                if precip and precip > 1.0: icon_class, icon_color, desc_clima = "fas fa-cloud-showers-heavy", "#3498db", f"Lluvia ({precip}mm)"
                elif tmax and tmax >= 25: icon_class, icon_color, desc_clima = "fas fa-sun", "#f39c12", "Calor"
                elif tmax and tmax < 12: icon_class, icon_color, desc_clima = "fas fa-snowflake", "#3498db", "Frío"

                clima_ui = html.Span(f"{round(tmax)}°/{round(tmin)}°", className="small text-muted fw-bold") if tmax is not None and tmin is not None else html.Div()

                header_left = html.Div([
                    html.Span(str(fecha_actual.day), className="fs-5 fw-bold me-2 text-dark"),
                    html.I(className=f"{icon_class} me-1", title=desc_clima, style={'color': icon_color, 'fontSize': '14px'}),
                    clima_ui
                ], className="d-flex align-items-center")

                header_elements = [header_left]
                if es_festivo: header_elements.append(html.Span(festivos_locales.get(fecha_actual), className="small fw-bold text-primary text-end ms-2", style={'lineHeight': '1.1', 'maxWidth': '50%'}))

                if df_dia.empty:
                    celdas_calendario.append(html.Div([
                        html.Div(header_elements, className=f"p-2 d-flex justify-content-between align-items-center rounded-top-4 {'bg-primary bg-opacity-10' if es_festivo else 'bg-light'}"),
                        html.Div("Sin datos.", className="p-3 small text-muted text-center")
                    ], className="bg-white border shadow-sm rounded-4", style={'minHeight': '140px'}))
                    continue

                inactivos, errores_mat, errores_fis = [], [], []
                for _, row in df_dia.iterrows():
                    zona = row.get('Zona', '').lower()
                    tv, uv, nv, dt = row.get('total_visits', 0), row.get('unique_visitors', 0), row.get('new_visitors', 0), row.get('dwell_time', 0)
                    if dt == 0 and (tv == 0 or uv == 0): inactivos.append(zona)
                    elif uv > tv: errores_mat.append(f"Únicos > Totales ({zona})")
                    elif nv > uv: errores_mat.append(f"Nuevos > Únicos ({zona})")
                    elif dt > 0 and tv == 0: errores_mat.append(f"Estancia fantasma ({zona})")

                df_agrupado = df_dia.groupby('Zona')['unique_visitors'].sum().reset_index()
                zonas_dict = dict(zip(df_agrupado['Zona'].str.lower(), df_agrupado['unique_visitors']))
                caja_val = sum(v for k, v in zonas_dict.items() if 'caja' in k)
                tienda_val = sum(v for k, v in zonas_dict.items() if 'tienda' in k)
                calle_val = sum(v for k, v in zonas_dict.items() if 'calle' in k or 'exterior' in k)

                if caja_val > 0 and calle_val > 0 and caja_val > calle_val: errores_fis.append("Caja > Exterior")
                if caja_val > 0 and tienda_val > 0 and caja_val > tienda_val: errores_fis.append("Caja > Interior")

                mensajes, estado_dia = [], 'success'
                if inactivos:
                    estado_dia = 'warning'
                    mensajes.append((f"Inactivo: {', '.join(set(inactivos))}", 'warning', "fas fa-exclamation-triangle"))
                else: mensajes.append(("Sensores OK", 'success', "fas fa-check-circle"))

                if errores_mat or errores_fis:
                    estado_dia = 'danger'
                    for err in set(errores_mat + errores_fis): mensajes.append((err, 'danger', "fas fa-times-circle"))
                elif not inactivos: mensajes.append(("Flujo coherente", 'success', "fas fa-check-circle"))

                bg_color, bg_header, border_class = "bg-white", "bg-light", "border-light"
                if estado_dia == 'danger': bg_color, bg_header, border_class = "bg-danger bg-opacity-10", "bg-danger bg-opacity-25", "border-danger border-opacity-25"
                elif estado_dia == 'warning': bg_color, bg_header, border_class = "bg-warning bg-opacity-10", "bg-warning bg-opacity-25", "border-warning border-opacity-25"
                elif estado_dia == 'success': bg_color, bg_header, border_class = "bg-white", "bg-success bg-opacity-10", "border-success border-opacity-25"
                
                if es_festivo: bg_header = "bg-primary bg-opacity-10"

                celda_content = [html.Div(header_elements, className=f"p-2 d-flex justify-content-between align-items-center rounded-top-4 {bg_header}")]
                lista_html = [html.Div([html.I(className=f"{icon} me-2"), html.Span(msg)], className=f"small fw-bold text-{tipo} mb-1") for msg, tipo, icon in mensajes]
                celda_content.append(html.Div(lista_html, className="p-2"))
                celdas_calendario.append(html.Div(celda_content, className=f"{bg_color} border {border_class} shadow-sm rounded-4", style={'minHeight': '140px'}))

            grilla = html.Div(cabeceras + celdas_calendario, style={'display': 'grid', 'gridTemplateColumns': 'repeat(7, 1fr)', 'gap': '15px'})
            tabs_meses.append(dbc.Tab(html.Div(grilla, className="pt-4"), label=nombre_mes, tab_id=nombre_mes, className="fw-bold"))

        paneles_ubicacion.append(dbc.Card(dbc.CardBody([
            html.H5([html.I(className="fas fa-building me-2 text-primary"), f"{ubi} ({region_code})"], className="fw-bold mb-3 text-dark"),
            dbc.Tabs(tabs_meses, active_tab=tabs_meses[0].tab_id) if tabs_meses else html.Div()
        ]), className="mb-4 shadow-sm border-0 rounded-4 bg-white"))

    return html.Div([
        html.H4([html.I(className="fas fa-calendar-check me-2 text-primary"), "Calendario de Auditoría Operativa"], className="fw-bold mb-3 mt-5 text-dark"),
        leyenda
    ] + paneles_ubicacion)