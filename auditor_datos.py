import pandas as pd
from dash import html, dash_table
import dash_bootstrap_components as dbc
import holidays

festivos_espana = holidays.ES(years=[2024, 2025, 2026])

def formato_fecha_es(fecha):
    dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    return f"{dias[fecha.weekday()]} {fecha.day} de {meses[fecha.month - 1]}"

def crear_tarjeta_auditoria(titulo, descripcion, alertas, color_header, color_texto_header='white'):
    if not alertas:
        contenido = dbc.Alert("No se han detectado incidencias en esta categoría.", color="light", class_name="p-2 mb-0 text-muted border-0")
    else:
        df_alertas = pd.DataFrame(alertas)
        contenido = dash_table.DataTable(
            data=df_alertas.to_dict('records'),
            columns=[{"name": str(i).capitalize(), "id": i} for i in df_alertas.columns],
            style_cell={'textAlign': 'left', 'padding': '10px'},
            style_header={'backgroundColor': color_header, 'color': color_texto_header, 'fontWeight': 'bold'},
            style_data_conditional=[
                {'if': {'row_index': 'odd'}, 'backgroundColor': '#f9f9f9'}
            ],
            page_size=10
        )
        
    return dbc.Card([
        dbc.CardHeader(html.Div([
            html.H5(titulo, className="mb-1 fw-bold text-secondary"),
            html.Small(descripcion, className="text-muted")
        ])),
        dbc.CardBody(contenido)
    ], className="mb-4 shadow-sm border-0")

def generar_tabla_auditoria(df_filt):
    alertas_matematicas = []
    alertas_sensor = []
    alertas_fisicas = []
    
    for _, row in df_filt.iterrows():
        fecha_obj = row['fecha']
        es_fin_semana = fecha_obj.weekday() >= 5
        
        if es_fin_semana:
            continue
            
        f_str = formato_fecha_es(fecha_obj)
        if fecha_obj in festivos_espana:
            f_str += f" (festivo: {festivos_espana.get(fecha_obj)})"
            
        ubi = row['Ubicación']
        zona = row['Zona']
        tv = row.get('total_visits', 0)
        uv = row.get('unique_visitors', 0)
        nv = row.get('new_visitors', 0)
        dt = row.get('dwell_time', 0)
        
        if uv > tv:
            alertas_matematicas.append({"fecha": f_str, "ubicación": ubi, "zona": zona, "incidencia": "Hay más personas únicas que entradas totales."})
        if nv > uv:
            alertas_matematicas.append({"fecha": f_str, "ubicación": ubi, "zona": zona, "incidencia": "Hay más clientes nuevos que clientes totales."})
        if dt > 0 and tv == 0:
            alertas_matematicas.append({"fecha": f_str, "ubicación": ubi, "zona": zona, "incidencia": "Marca tiempo de estancia pero nadie ha entrado."})
        if tv == 0:
            alertas_sensor.append({"fecha": f_str, "ubicación": ubi, "zona": zona, "incidencia": "Esta zona no tiene visitas en todo el día."})

    df_agrupado = df_filt.groupby(['fecha', 'Ubicación', 'Zona'])['unique_visitors'].sum().reset_index()
    for (fecha_obj, ubi), group in df_agrupado.groupby(['fecha', 'Ubicación']):
        if fecha_obj.weekday() >= 5:
            continue
            
        f_str = formato_fecha_es(fecha_obj)
        if fecha_obj in festivos_espana:
            f_str += f" (festivo: {festivos_espana.get(fecha_obj)})"
            
        zonas_dict = dict(zip(group['Zona'].str.lower(), group['unique_visitors']))
        caja_val = sum(v for k, v in zonas_dict.items() if 'caja' in k)
        tienda_val = sum(v for k, v in zonas_dict.items() if 'tienda' in k)
        calle_val = sum(v for k, v in zonas_dict.items() if 'calle' in k or 'exterior' in k)
        
        if caja_val > 0 and calle_val > 0 and caja_val > calle_val:
            alertas_fisicas.append({"fecha": f_str, "ubicación": ubi, "zona": "cruce de zonas", "incidencia": "Hay más gente en la caja que en la puerta principal."})
        if caja_val > 0 and tienda_val > 0 and caja_val > tienda_val:
            alertas_fisicas.append({"fecha": f_str, "ubicación": ubi, "zona": "cruce de zonas", "incidencia": "Hay más visitantes en caja que en tienda."})

    tarjeta_mat = crear_tarjeta_auditoria(
        "Inconsistencias matemáticas",
        "Errores críticos donde los datos de visitantes o estancia son físicamente imposibles.",
        alertas_matematicas,
        "#F8696B"
    )
    
    tarjeta_fis = crear_tarjeta_auditoria(
        "Inconsistencias físicas de flujo",
        "Avisos sobre el comportamiento del embudo que indican posibles fallos de calibración en los cruces.",
        alertas_fisicas,
        "#F28A2E"
    )
    
    tarjeta_sen = crear_tarjeta_auditoria(
        "Alertas de inactividad de sensor",
        "Zonas que han registrado exactamente cero visitas durante un día laboral completo.",
        alertas_sensor,
        "#FFE082",
        "black"
    )

    return html.Div([
        html.H4("Auditoría de calidad de datos segmentada", className="fw-bold mb-4 text-primary"),
        tarjeta_mat,
        tarjeta_fis,
        tarjeta_sen
    ])