import pandas as pd
import plotly.express as px
from dash import html, dcc
import dash_bootstrap_components as dbc
import holidays

festivos_espana = holidays.ES(years=[2024, 2025, 2026])

def formato_fecha_es(fecha):
    dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    return f"{dias[fecha.weekday()]} {fecha.day} de {meses[fecha.month - 1]}"

def crear_grafico_anomalias(df_datos, col_y, titulo, label_y, tipo='bar'):
    alertas = []
    anomalias = {}
    
    for zona in df_datos['Zona'].unique():
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
                    alertas.append(dbc.Alert(f"Caída o aviso: la zona '{zona}' registró {val:,.1f} el {f_str} frente a una media de {mean_val:,.1f}.", color="danger", class_name="p-2 mb-2"))
                    anomalias[(fecha_obj, zona)] = 'baja'
                elif z_score > 2:
                    alertas.append(dbc.Alert(f"Pico inusual: la zona '{zona}' registró {val:,.1f} el {f_str} frente a una media de {mean_val:,.1f}.", color="success", class_name="p-2 mb-2"))
                    anomalias[(fecha_obj, zona)] = 'alta'

    if tipo == 'bar':
        fig = px.bar(
            df_datos, x='fecha', y=col_y, color='Zona', barmode='group',
            labels={col_y: label_y, 'fecha': 'Fecha'},
            color_discrete_sequence=px.colors.qualitative.Safe
        )
        fig.update_layout(plot_bgcolor='white', hovermode='x unified', margin=dict(t=20, b=20, l=20, r=20))

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
                        texts.append('<b style="color:red; font-size:16px">X</b>')
                        text_positions.append("outside")
                    else:
                        line_colors.append('red')
                        line_widths.append(4)
                        texts.append("")
                        text_positions.append("none")
                elif estado == 'alta':
                    line_colors.append('#2ca02c')
                    line_widths.append(4)
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
            color_discrete_sequence=px.colors.qualitative.Vivid
        )
        fig.update_layout(plot_bgcolor='white', hovermode='x unified', margin=dict(t=20, b=20, l=20, r=20))
        
        for trace in fig.data:
            zona_trace = trace.name
            marker_colors = []
            marker_sizes = []
            default_color = trace.line.color
            
            for i, x_val in enumerate(trace.x):
                x_dt = pd.to_datetime(x_val)
                estado = anomalias.get((x_dt, zona_trace))
                
                if estado == 'baja':
                    marker_colors.append('red')
                    marker_sizes.append(15)
                elif estado == 'alta':
                    marker_colors.append('#2ca02c')
                    marker_sizes.append(15)
                else:
                    marker_colors.append(default_color)
                    marker_sizes.append(8)
                    
            trace.marker.color = marker_colors
            trace.marker.size = marker_sizes
            trace.marker.line.width = 2
            trace.marker.line.color = marker_colors

    return fig, alertas

def crear_bloque_metrica(df_datos, col_y, titulo, label_y, tipo='bar'):
    fig, alertas = crear_grafico_anomalias(df_datos, col_y, titulo, label_y, tipo)
    
    if not alertas:
        div_alertas = html.Div(dbc.Alert("Valores dentro de la normalidad estadística.", color="light", class_name="p-2 mb-2 text-muted border-0"))
    else:
        div_alertas = html.Div(alertas)
        
    return dbc.Card([
        dbc.CardHeader(html.H5(titulo, className="mb-0 fw-bold text-secondary")),
        dbc.CardBody([
            div_alertas,
            dcc.Graph(figure=fig, config={'displayModeBar': False})
        ])
    ], className="mb-4 shadow-sm border-0")

def generar_panel_anomalias(df_filt):
    if df_filt.empty:
        return dbc.Alert("No hay datos para analizar anomalías.", color="warning")

    df_laborales = df_filt[df_filt['fecha'].dt.dayofweek < 5].copy()
    
    if df_laborales.empty:
        return dbc.Alert("No hay datos de días laborales para analizar.", color="warning")

    df_laborales['Zona'] = df_laborales['Zona'].fillna('')
    mask_calle = df_laborales['Zona'].str.lower().str.contains('calle|exterior')
    df_calle = df_laborales[mask_calle]
    df_interior = df_laborales[~mask_calle]

    cols_agg = {'total_visits': 'sum', 'dwell_time': 'mean'}
    if 'unique_visitors' in df_laborales.columns: cols_agg['unique_visitors'] = 'sum'
    if 'new_visitors' in df_laborales.columns: cols_agg['new_visitors'] = 'sum'
    
    for col in df_laborales.columns:
        if ('7d' in col.lower() or '28d' in col.lower()) and col not in cols_agg:
            cols_agg[col] = 'mean'

    df_agg_int = df_interior.groupby(['fecha', 'Zona']).agg(cols_agg).reset_index() if not df_interior.empty else pd.DataFrame()
    df_agg_calle = df_calle.groupby(['fecha', 'Zona']).agg(cols_agg).reset_index() if not df_calle.empty else pd.DataFrame()

    bloques_ui = []
    
    metricas_basicas = [
        ('total_visits', 'Visitas totales', 'Visitas'),
        ('unique_visitors', 'Visitantes diarios', 'Visitantes'),
        ('new_visitors', 'Nuevos visitantes', 'Visitantes')
    ]
    
    for col, titulo, label in metricas_basicas:
        if col in cols_agg:
            if not df_agg_int.empty:
                bloques_ui.append(crear_bloque_metrica(df_agg_int, col, f'{titulo} (interior)', label))
            if not df_agg_calle.empty:
                bloques_ui.append(crear_bloque_metrica(df_agg_calle, col, f'{titulo} (calle y exterior)', label))
                
    for col in cols_agg:
        if '7d' in col.lower() or '28d' in col.lower():
            if not df_agg_int.empty:
                bloques_ui.append(crear_bloque_metrica(df_agg_int, col, f'Frecuencia recurrente: {col} (interior)', col, tipo='line'))

    if not df_agg_int.empty:
        bloques_ui.append(crear_bloque_metrica(df_agg_int, 'dwell_time', 'Tiempo medio de estancia (interior)', 'Minutos', tipo='line'))

    return html.Div([
        html.H4("Análisis estadístico segmentado", className="fw-bold mb-4 text-primary"),
        html.Div(bloques_ui)
    ])