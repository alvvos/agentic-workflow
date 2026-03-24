import pandas as pd
from dash import html, dash_table
import dash_bootstrap_components as dbc

def generar_tabla_auditoria(df_filt):
    alertas = []
    
    for _, row in df_filt.iterrows():
        f_str = row['fecha'].strftime('%Y-%m-%d')
        ubi = row['Ubicación']
        zona = row['Zona']
        tv = row.get('total_visits', 0)
        uv = row.get('unique_visitors', 0)
        nv = row.get('new_visitors', 0)
        dt = row.get('dwell_time', 0)
        
        if uv > tv:
            alertas.append({"fecha": f_str, "ubicación": ubi, "zona": zona, "error": "Hay más personas únicas que entradas totales", "gravedad": "crítica"})
        if nv > uv:
            alertas.append({"fecha": f_str, "ubicación": ubi, "zona": zona, "error": "Hay más clientes nuevos que clientes totales", "gravedad": "crítica"})
        if dt > 0 and tv == 0:
            alertas.append({"fecha": f_str, "ubicación": ubi, "zona": zona, "error": "Marca tiempo de estancia pero nadie ha entrado", "gravedad": "crítica"})
        if tv == 0:
            alertas.append({"fecha": f_str, "ubicación": ubi, "zona": zona, "error": "El sensor está apagado o a cero", "gravedad": "aviso"})

    df_agrupado = df_filt.groupby(['fecha', 'Ubicación', 'Zona'])['unique_visitors'].sum().reset_index()
    for (fecha, ubi), group in df_agrupado.groupby(['fecha', 'Ubicación']):
        zonas_dict = dict(zip(group['Zona'].str.lower(), group['unique_visitors']))
        
        caja_val = sum(v for k, v in zonas_dict.items() if 'caja' in k)
        calle_val = sum(v for k, v in zonas_dict.items() if 'calle' in k or 'exterior' in k)
        
        if caja_val > 0 and calle_val > 0 and caja_val > calle_val:
            f_str = fecha.strftime('%Y-%m-%d')
            alertas.append({"fecha": f_str, "ubicación": ubi, "zona": "cruce de zonas", "error": "Hay más gente en la caja que en la puerta principal", "gravedad": "aviso"})

    if not alertas:
        return dbc.Alert("Auditoría de calidad completada sin errores de sistema.", color="success")
        
    df_alertas = pd.DataFrame(alertas)
    
    tabla = dash_table.DataTable(
        data=df_alertas.to_dict('records'),
        columns=[{"name": str(i).capitalize(), "id": i} for i in df_alertas.columns],
        style_cell={'textAlign': 'left', 'padding': '10px'},
        style_header={'backgroundColor': '#203764', 'color': 'white', 'fontWeight': 'bold'},
        style_data_conditional=[
            {'if': {'filter_query': '{gravedad} = "crítica"'}, 'backgroundColor': '#F8696B', 'color': 'white'},
            {'if': {'filter_query': '{gravedad} = "aviso"'}, 'backgroundColor': '#FFE082', 'color': 'black'}
        ],
        page_size=15
    )
    
    return html.Div([
        html.H5(f"Se han encontrado {len(alertas)} errores de calidad", className="text-danger fw-bold mb-3"),
        tabla
    ])