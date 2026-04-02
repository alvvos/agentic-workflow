import pandas as pd
import plotly.express as px
from dash import html, dcc
import dash_bootstrap_components as dbc
import holidays
import uuid
import json

festivos_espana = holidays.ES(years=[2024, 2025, 2026])

# --- DICCIONARIO JSON DE INSIGHTS PARA TOOLTIPS ---
TOOLTIPS_JSON = """
{
    "total_visits": "Mide el volumen bruto de tráfico. Útil para entender el trasiego general y los momentos de mayor saturación operativa en el local.",
    "unique_visitors": "Cuenta personas reales. Clave para medir la cantidad de personas distintas captadas en un solo día, filtrando el ruido.",
    "new_visitors": "Muestra el poder de atracción del local. Un volumen alto indica éxito llamando la atención de público nuevo.",
    "dwell_time": "Refleja el interés y la retención. Más tiempo suele traducirse en mayor probabilidad de compra o fidelidad con el espacio.",
    "uv_7d": "Indica el tamaño real de la audiencia acumulada en 7 días, eliminando visitas duplicadas para no inflar los números.",
    "uv_28d": "Indica el tamaño real de la audiencia acumulada en 28 días, eliminando visitas duplicadas para no inflar los números.",
    "uv_month": "Indica el tamaño real de la audiencia acumulada en el mes, eliminando visitas duplicadas para no inflar los números.",
    "uv_year": "Indica el tamaño real de la audiencia acumulada en el año, eliminando visitas duplicadas para no inflar los números.",
    "freq_7d": "Mide el enganche a corto plazo. Valores más altos indican lealtad y repetición de los clientes en la última semana.",
    "freq_28d": "Mide el enganche a medio plazo. Valores más altos indican lealtad y repetición de los clientes en las últimas 4 semanas.",
    "freq_month": "Mide el enganche mensual. Valores más altos indican lealtad y repetición de los clientes en el mes en curso.",
    "freq_year": "Mide el enganche anual. Valores más altos indican lealtad y repetición de los clientes durante el año.",
    "default": "Muestra el rendimiento y evolución de esta métrica clave en el tiempo."
}
"""
insights_dict = json.loads(TOOLTIPS_JSON)
# --------------------------------------------------

def formato_fecha_es(fecha):
    dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    return f"{dias[fecha.weekday()]} {fecha.day} de {meses[fecha.month - 1]}"

def obtener_mapa_colores(zonas):
    color_map = {}
    for z in zonas:
        zl = str(z).lower()
        if 'caja' in zl:
            color_map[z] = '#8e44ad'  # Morado (Sustituye al verde para no chocar con las alertas)
        elif 'tienda' in zl:
            color_map[z] = '#e67e22'  # Naranja
        elif 'calle' in zl or 'exterior' in zl:
            color_map[z] = '#2980b9'  # Azul
        else:
            color_map[z] = '#7f8c8d'  # Gris por defecto
    return color_map

def ordenar_zonas(zonas):
    def peso(z):
        zl = str(z).lower()
        if 'exterior' in zl or 'calle' in zl: return 1
        if 'tienda' in zl: return 2
        if 'caja' in zl: return 3
        return 4
    return sorted(zonas, key=peso)

def obtener_titulo_intuitivo(col):
    mapa = {
        'uv_7d': 'Visitantes únicos procesados por día (últimos 7 días)',
        'uv_28d': 'Visitantes únicos procesados por día (últimos 28 días)',
        'uv_month': 'Visitantes únicos procesados por día (mes en curso)',
        'uv_year': 'Visitantes únicos procesados (año en curso)',
        'freq_7d': 'Frecuencia de retorno por día (últimos 7 días)',
        'freq_28d': 'Frecuencia de retorno por día (últimos 28 días)',
        'freq_month': 'Frecuencia de retorno por día (mes en curso)',
        'freq_year': 'Frecuencia de retorno por día (año en curso)',
    }
    return mapa.get(col, col)

def obtener_insight_metrica(col):
    return insights_dict.get(col, insights_dict["default"])

def crear_grafico_anomalias(df_datos, col_y, titulo, label_y, tipo='bar'):
    alertas_dict = {}
    anomalias = {}
    
    zonas_ordenadas = ordenar_zonas(df_datos['Zona'].unique())
    df_datos['Zona'] = pd.Categorical(df_datos['Zona'], categories=zonas_ordenadas, ordered=True)
    df_datos = df_datos.sort_values(['fecha', 'Zona'])
    
    color_map = obtener_mapa_colores(zonas_ordenadas)
    
    for zona in zonas_ordenadas:
        df_z = df_datos[df_datos['Zona'] == zona]
        if len(df_z) < 3:
            continue
            
        mean_val = df_z[col_y].mean()
        std_val = df_z[col_y].std()

        for _, row in df_z.iterrows():
            fecha_obj = row['fecha']
            val = row[col_y]
            f_str = formato_fecha_es(fecha_obj)
            es_festivo = fecha_obj in festivos_espana
            
            if es_festivo:
                f_str += f" (festivo: {festivos_espana.get(fecha_obj)})"
            
            if pd.notna(std_val) and std_val > 0:
                z_score = (val - mean_val) / std_val
                
                if z_score < -2 or val == 0:
                    if f_str not in alertas_dict: alertas_dict[f_str] = []
                    alertas_dict[f_str].append((f"Aviso de descenso: la zona '{zona}' registró {val:,.1f} frente a una media de {mean_val:,.1f}.", "danger", "fas fa-arrow-down"))
                    anomalias[(fecha_obj, zona)] = 'baja'
                elif z_score > 2:
                    if f_str not in alertas_dict: alertas_dict[f_str] = []
                    alertas_dict[f_str].append((f"Pico detectado: la zona '{zona}' registró {val:,.1f} frente a una media de {mean_val:,.1f}.", "success", "fas fa-arrow-up"))
                    anomalias[(fecha_obj, zona)] = 'alta'

    if tipo == 'bar':
        fig = px.bar(
            df_datos, x='fecha', y=col_y, color='Zona', barmode='group',
            labels={col_y: label_y, 'fecha': 'Fecha'},
            color_discrete_map=color_map,
            category_orders={"Zona": zonas_ordenadas}
        )
        fig.update_layout(
            plot_bgcolor='white', 
            hovermode='x unified', 
            margin=dict(t=25, b=25, l=25, r=25),
            font=dict(size=14),
            legend_title_text=''
        )

        for trace in fig.data:
            zona_trace = trace.name
            line_colors = []
            line_widths = []
            texts = []
            text_positions = []
            
            for i, x_val in enumerate(trace.x):
                y_val = trace.y[i]
                x_dt = pd.to_datetime(x_val)
                estado = anomalias.get((x_dt, zona_trace))
                
                if estado == 'baja':
                    if y_val == 0:
                        line_colors.append('rgba(0,0,0,0)')
                        line_widths.append(0)
                        texts.append('<b style="color:#e74c3c; font-size:18px">X</b>')
                        text_positions.append("outside")
                    else:
                        line_colors.append('#e74c3c')
                        line_widths.append(3)
                        texts.append("")
                        text_positions.append("none")
                elif estado == 'alta':
                    line_colors.append('#27ae60')
                    line_widths.append(3)
                    texts.append("")
                    text_positions.append("none")
                else:
                    line_colors.append('rgba(0,0,0,0)')
                    line_widths.append(0)
                    texts.append("")
                    text_positions.append("none")
                    
            trace.marker.line.color = line_colors
            trace.marker.line.width = line_widths
            trace.text = texts
            trace.textposition = text_positions
    else:
        fig = px.line(
            df_datos, x='fecha', y=col_y, color='Zona', markers=True,
            labels={col_y: label_y, 'fecha': 'Fecha'},
            color_discrete_map=color_map,
            category_orders={"Zona": zonas_ordenadas}
        )
        fig.update_layout(
            plot_bgcolor='white', 
            hovermode='x unified', 
            margin=dict(t=25, b=25, l=25, r=25),
            font=dict(size=14),
            legend_title_text=''
        )
        
        for trace in fig.data:
            zona_trace = trace.name
            marker_colors = []
            marker_sizes = []
            default_color = trace.line.color
            
            for i, x_val in enumerate(trace.x):
                x_dt = pd.to_datetime(x_val)
                estado = anomalias.get((x_dt, zona_trace))
                
                if estado == 'baja':
                    marker_colors.append('#e74c3c')
                    marker_sizes.append(14)
                elif estado == 'alta':
                    marker_colors.append('#27ae60')
                    marker_sizes.append(14)
                else:
                    marker_colors.append(default_color)
                    marker_sizes.append(8)
                    
            trace.marker.color = marker_colors
            trace.marker.size = marker_sizes
            trace.marker.line.width = 2
            trace.marker.line.color = marker_colors

    return fig, alertas_dict

def crear_bloque_metrica(df_datos, col_y, titulo, label_y, tipo='bar'):
    fig, alertas_dict = crear_grafico_anomalias(df_datos, col_y, titulo, label_y, tipo)
    
    icono_titulo = "fas fa-chart-line" if tipo == 'line' else "fas fa-chart-bar"
    insight_text = obtener_insight_metrica(col_y)
    tooltip_id = f"tooltip-{uuid.uuid4().hex}"
    
    if not alertas_dict:
        div_alertas = html.Div(dbc.Alert("Valores dentro de la normalidad estadística.", color="light", className="p-3 mb-0 text-muted border-0", style={'fontSize': '14px', 'backgroundColor': '#f8f9fa'}))
    else:
        items_acordeon = []
        for dia, mensajes in alertas_dict.items():
            contenido = [
                html.Div([
                    html.I(className=f"{icon} me-2"),
                    html.Span(m)
                ], className=f"text-{estado} fw-bold", style={'fontSize': '14px', 'marginBottom': '6px'}) 
                for m, estado, icon in mensajes
            ]
            items_acordeon.append(dbc.AccordionItem(contenido, title=dia))
            
        div_alertas = html.Div([
            html.H6([html.I(className="fas fa-list-ul me-2"), "Desglose de avisos detectados"], className="text-secondary mt-3 mb-3", style={'fontSize': '15px', 'fontWeight': 'bold'}),
            dbc.Accordion(items_acordeon, start_collapsed=True, flush=True)
        ], className="bg-light p-3 rounded-bottom")
        
    return dbc.Card([
        dbc.CardHeader([
            html.Div([
                html.H5([html.I(className=f"{icono_titulo} me-2 text-primary"), titulo], className="mb-0 fw-bold text-secondary d-inline-block", style={'fontSize': '16px'}),
                html.I(className="fas fa-info-circle ms-2 text-muted", id=tooltip_id, style={"cursor": "pointer", "fontSize": "15px"}),
                dbc.Tooltip(insight_text, target=tooltip_id, placement="top", className="shadow-sm")
            ], className="d-flex align-items-center")
        ], className="bg-white border-bottom-0 pt-3 pb-0"),
        dbc.CardBody([
            dcc.Graph(figure=fig, config={'displayModeBar': False}),
            div_alertas
        ], className="p-0")
    ], className="mb-4 shadow-sm border-0 rounded-3")

def generar_panel_anomalias(df_filt):
    if df_filt.empty:
        return dbc.Alert("No hay datos para mostrar gráficas en este periodo.", color="warning", className="mt-3", style={'fontSize': '16px'})

    paneles_ubicacion = []

    for ubi in df_filt['Ubicación'].unique():
        df_ubi = df_filt[df_filt['Ubicación'] == ubi].copy()

        alertas_embudo_dict = {}
        if 'unique_visitors' in df_ubi.columns:
            df_agrupado_embudo = df_ubi.groupby(['fecha', 'Zona'])['unique_visitors'].sum().reset_index()
            for fecha_obj, group in df_agrupado_embudo.groupby('fecha'):
                zonas_dict = dict(zip(group['Zona'].str.lower(), group['unique_visitors']))
                caja_val = sum(v for k, v in zonas_dict.items() if 'caja' in k)
                tienda_val = sum(v for k, v in zonas_dict.items() if 'tienda' in k)
                
                if caja_val > 0 and tienda_val > 0 and caja_val > tienda_val:
                    f_str = formato_fecha_es(fecha_obj)
                    if fecha_obj in festivos_espana:
                        f_str += f" (festivo: {festivos_espana.get(fecha_obj)})"
                    
                    if f_str not in alertas_embudo_dict:
                        alertas_embudo_dict[f_str] = []
                    alertas_embudo_dict[f_str].append(f"Inversión de flujo: hay más visitantes en caja ({caja_val:,.0f}) que en tienda ({tienda_val:,.0f}).")

        df_ubi['Zona'] = df_ubi['Zona'].fillna('')
        mask_calle = df_ubi['Zona'].str.lower().str.contains('calle|exterior')
        df_calle = df_ubi[mask_calle]
        df_interior = df_ubi[~mask_calle]

        cols_agg = {'total_visits': 'sum', 'dwell_time': 'mean'}
        if 'unique_visitors' in df_ubi.columns: cols_agg['unique_visitors'] = 'sum'
        if 'new_visitors' in df_ubi.columns: cols_agg['new_visitors'] = 'sum'
        
        for col in df_ubi.columns:
            if ('7d' in col.lower() or '28d' in col.lower()) and col not in cols_agg:
                cols_agg[col] = 'mean'

        df_agg_int = df_interior.groupby(['fecha', 'Zona']).agg(cols_agg).reset_index() if not df_interior.empty else pd.DataFrame()
        df_agg_calle = df_calle.groupby(['fecha', 'Zona']).agg(cols_agg).reset_index() if not df_calle.empty else pd.DataFrame()

        bloques_ui = []
        
        metricas_basicas = [
            ('total_visits', 'Visitas totales', 'Visitas'),
            ('unique_visitors', 'Visitantes diarios', 'Visitantes'),
            ('new_visitors', 'Nuevos visitantes (velocidad de captación)', 'Nuevos visitantes')
        ]
        
        for col, titulo, label in metricas_basicas:
            if col in cols_agg:
                if not df_agg_calle.empty:
                    bloques_ui.append(crear_bloque_metrica(df_agg_calle, col, f'{titulo} (exterior)', label))
                if not df_agg_int.empty:
                    bloques_ui.append(crear_bloque_metrica(df_agg_int, col, f'{titulo} (interior)', label))
                    
        for col in cols_agg:
            if '7d' in col.lower() or '28d' in col.lower():
                titulo_base = obtener_titulo_intuitivo(col)
                label_y = "Frecuencia" if "freq" in col else "Visitantes"
                if not df_agg_calle.empty:
                    bloques_ui.append(crear_bloque_metrica(df_agg_calle, col, f'{titulo_base} (exterior)', label_y, tipo='line'))
                if not df_agg_int.empty:
                    bloques_ui.append(crear_bloque_metrica(df_agg_int, col, f'{titulo_base} (interior)', label_y, tipo='line'))

        if not df_agg_calle.empty:
            bloques_ui.append(crear_bloque_metrica(df_agg_calle, 'dwell_time', 'Tiempo medio de estancia en minutos (exterior)', 'Minutos', tipo='line'))
        if not df_agg_int.empty:
            bloques_ui.append(crear_bloque_metrica(df_agg_int, 'dwell_time', 'Tiempo medio de estancia en minutos (interior)', 'Minutos', tipo='line'))

        if alertas_embudo_dict:
            items_embudo = []
            for dia, mensajes in alertas_embudo_dict.items():
                contenido = [
                    html.Div([
                        html.I(className="fas fa-exclamation-circle me-2"),
                        html.Span(m)
                    ], className="text-danger fw-bold", style={'fontSize': '14px', 'marginBottom': '6px'}) 
                    for m in mensajes
                ]
                items_embudo.append(dbc.AccordionItem(contenido, title=dia))
                
            bloques_ui.append(dbc.Card([
                dbc.CardHeader(html.H5([html.I(className="fas fa-random me-2"), "Avisos deterministas de flujo"], className="mb-0 fw-bold text-danger", style={'fontSize': '16px'})),
                dbc.CardBody([
                    html.P("Incongruencias detectadas en la captación física.", className="text-muted mb-3", style={'fontSize': '14px'}),
                    dbc.Accordion(items_embudo, start_collapsed=True, flush=True)
                ], className="bg-light p-3")
            ], className="mb-4 shadow-sm border-0 border-danger rounded-3"))

        paneles_ubicacion.append(html.Div([
            html.H5([
                html.I(className="fas fa-map-marker-alt me-2 text-danger"),
                ubi
            ], className="fw-bold mb-3 mt-4 text-secondary"),
            html.Div(bloques_ui)
        ]))

    return html.Div([
        html.H4([
            html.I(className="fas fa-chart-pie me-2"),
            "Visualización de gráficas"
        ], className="fw-bold mb-4 text-primary"),
        html.Div(paneles_ubicacion)
    ])