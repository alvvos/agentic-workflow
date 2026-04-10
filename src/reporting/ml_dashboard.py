import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table
import plotly.graph_objects as go
import pandas as pd

def generar_tarjeta_metrica(titulo, valor, color):
    return dbc.Card([
        dbc.CardBody([
            html.H6(titulo, className="text-muted mb-2 text-uppercase", style={"fontSize": "12px", "fontWeight": "bold"}),
            html.H3(valor, className=f"text-{color} mb-0 fw-bold")
        ])
    ], className="shadow-sm border-0 h-100")

def generar_grafico_prediccion(df, df_proyeccion=None):
    fig = go.Figure()
    
    df_agrupado = df.groupby('fecha').agg({
        'total_visits': 'sum',
        'prediccion': 'sum',
        'es_anomalia': 'max'
    }).reset_index()

    fig.add_trace(go.Scatter(
        x=df_agrupado['fecha'], 
        y=df_agrupado['total_visits'],
        mode='lines',
        name='Tráfico real',
        line=dict(color='#203764', width=2)
    ))

    fig.add_trace(go.Scatter(
        x=df_agrupado['fecha'], 
        y=df_agrupado['prediccion'],
        mode='lines',
        name='Línea base esperada',
        line=dict(color='#2ecc71', width=2, dash='dash')
    ))
    
    if df_proyeccion is not None:
        manana = df_proyeccion['fecha'].iloc[0]
        valor_manana = df_proyeccion['prediccion'].sum()
        
        fig.add_trace(go.Scatter(
            x=[df_agrupado['fecha'].iloc[-1], manana],
            y=[df_agrupado['prediccion'].iloc[-1], valor_manana],
            mode='lines+markers',
            name='Proyección mañana',
            line=dict(color='#8e44ad', width=3, dash='dot'),
            marker=dict(size=8)
        ))

    fig.update_layout(
        title="Auditoría y proyección operativa",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=60, b=40)
    )
    
    return fig

def generar_panel_ml(df_resultados, metricas, df_proyeccion=None):
    mae = f"{metricas['error_absoluto_medio']} pax"
    wmape = f"{metricas['error_porcentual_medio']}%"
    
    pax_manana = "N/A"
    if df_proyeccion is not None:
        pax_manana = f"{int(df_proyeccion['prediccion'].sum())} pax"
    
    panel = html.Div([
        dbc.Row([
            dbc.Col(generar_tarjeta_metrica("Previsión para mañana", pax_manana, "dark"), width=4),
            dbc.Col(generar_tarjeta_metrica("Precisión histórica (wmape)", wmape, "info"), width=4),
            dbc.Col(generar_tarjeta_metrica("Error medio (mae)", mae, "primary"), width=4),
        ], className="mb-4"),
        
        dbc.Card(dbc.CardBody(dcc.Graph(figure=generar_grafico_prediccion(df_resultados, df_proyeccion))), className="shadow-sm border-0 mb-4")
    ])
    
    return panel