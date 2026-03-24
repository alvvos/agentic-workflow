import pandas as pd
import plotly.express as px
from dash import html, dcc
import dash_bootstrap_components as dbc

def generar_panel_anomalias(df_filt):
    if df_filt.empty:
        return dbc.Alert("No hay datos para analizar anomalías.", color="warning")

    df_agrupado = df_filt.groupby(['fecha', 'Zona']).agg({
        'total_visits': 'sum',
        'dwell_time': 'mean'
    }).reset_index()

    fig_visitas = px.bar(
        df_agrupado,
        x='fecha',
        y='total_visits',
        color='Zona',
        barmode='group',
        title='Visitas Totales por Zona (Comparativa Diaria)',
        labels={'total_visits': 'Visitas Totales', 'fecha': 'Fecha'},
        color_discrete_sequence=px.colors.qualitative.Safe
    )
    fig_visitas.update_layout(plot_bgcolor='white', hovermode='x unified')

    fig_dwell = px.line(
        df_agrupado,
        x='fecha',
        y='dwell_time',
        color='Zona',
        markers=True,
        title='Tiempo Medio de Estancia en Tienda por Zona (Minutos)',
        labels={'dwell_time': 'Minutos', 'fecha': 'Fecha'},
        color_discrete_sequence=px.colors.qualitative.Vivid
    )
    fig_dwell.update_traces(line=dict(width=3), marker=dict(size=8))
    fig_dwell.update_layout(plot_bgcolor='white', hovermode='x unified')

    alertas_ui = []
    
    for zona in df_agrupado['Zona'].unique():
        df_z = df_agrupado[df_agrupado['Zona'] == zona]
        if len(df_z) < 3:
            continue
            
        mean_v = df_z['total_visits'].mean()
        std_v = df_z['total_visits'].std()
        mean_d = df_z['dwell_time'].mean()
        std_d = df_z['dwell_time'].std()

        for _, row in df_z.iterrows():
            f_str = row['fecha'].strftime('%d-%m-%Y')
            
            if pd.notna(std_v) and std_v > 0:
                z_score_v = (row['total_visits'] - mean_v) / std_v
                if z_score_v > 2:
                    alertas_ui.append(dbc.Alert(f"Pico inusual: La zona '{zona}' registró {row['total_visits']:,.0f} visitas el {f_str} (Media habitual: {mean_v:,.0f}).", color="info", style={"padding": "10px", "marginBottom": "5px"}))
                elif z_score_v < -2:
                    alertas_ui.append(dbc.Alert(f"Caída inusual: La zona '{zona}' registró solo {row['total_visits']:,.0f} visitas el {f_str} (Media habitual: {mean_v:,.0f}).", color="warning", style={"padding": "10px", "marginBottom": "5px"}))

            if pd.notna(std_d) and std_d > 0:
                z_score_d = (row['dwell_time'] - mean_d) / std_d
                if z_score_d > 2:
                    alertas_ui.append(dbc.Alert(f"Retención alta: La zona '{zona}' retuvo a los clientes {row['dwell_time']:.1f} min el {f_str} (Media habitual: {mean_d:.1f} min).", color="success", style={"padding": "10px", "marginBottom": "5px"}))

    if not alertas_ui:
        alertas_ui.append(dbc.Alert("No se han detectado desviaciones ni picos inusuales en este período.", color="success"))

    return html.Div([
        html.H5("Detección estadística de Outliers", className="fw-bold mb-3 text-primary"),
        html.Div(alertas_ui, className="mb-4"),
        dcc.Graph(figure=fig_visitas, className="mb-4 shadow-sm"),
        dcc.Graph(figure=fig_dwell, className="shadow-sm")
    ])