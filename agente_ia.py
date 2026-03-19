import os
import json
import pandas as pd
from datetime import datetime, timedelta
from google import genai
from google.genai import types
import dash
from dash import html, dcc, Input, Output, State
import dash_bootstrap_components as dbc
from ml.prediccion import MotorPredictivo
from dotenv import load_dotenv
import subprocess

load_dotenv()

motor = MotorPredictivo()

def herramienta_predecir_trafico(location_id: str, zone: str, fecha_futura: str) -> str:
    print(f"[HERRAMIENTA ACTIVADA] Tienda: {location_id} | Zona: {zone} | Fecha: {fecha_futura}")
    try:
        df_historico = pd.read_csv('dataset_global_raw.csv')
        df_historico['fecha'] = pd.to_datetime(df_historico['fecha'])
        df_filtro = df_historico[(df_historico['location_id'] == location_id) & (df_historico['zone'].astype(str) == str(zone))]
        
        if df_filtro.empty:
            print("[HERRAMIENTA ERROR] No hay datos en el CSV para esa tienda/zona.")
            return "Error: No hay datos historicos suficientes."

        df_diario = df_filtro.groupby('fecha')['total_visits'].sum().reset_index()
        df_diario = df_diario.set_index('fecha')
        target_date = datetime.strptime(fecha_futura, "%Y-%m-%d")
        
        ayer = target_date - timedelta(days=1)
        hace_7_dias = target_date - timedelta(days=7)
        hace_14_dias = target_date - timedelta(days=14)
        
        def obtener_visitas_o_imputar(fecha_busqueda):
            if fecha_busqueda in df_diario.index:
                return float(df_diario.loc[fecha_busqueda, 'total_visits'])
            
            dia_semana = fecha_busqueda.weekday()
            df_mismo_dia = df_diario[df_diario.index.weekday == dia_semana]
            
            if not df_mismo_dia.empty:
                return float(df_mismo_dia['total_visits'].mean())
            
            elif not df_diario.empty:
                return float(df_diario['total_visits'].mean())
            
            return 0.0
            
        visitas_ayer = obtener_visitas_o_imputar(ayer)
        visitas_7 = obtener_visitas_o_imputar(hace_7_dias)
        visitas_14 = obtener_visitas_o_imputar(hace_14_dias)
        
        fecha_inicio_semana = target_date - timedelta(days=7)
        datos_semana = df_diario.loc[fecha_inicio_semana:ayer, 'total_visits']
        
        if len(datos_semana) > 0:
            media_7 = float(datos_semana.mean())
            std_7 = float(datos_semana.std())
            if pd.isna(std_7): std_7 = 0.0
        elif not df_diario.empty:
            media_7 = float(df_diario['total_visits'].mean())
            std_7 = float(df_diario['total_visits'].std())
            if pd.isna(std_7): std_7 = 0.0
        else:
            media_7 = 0.0
            std_7 = 0.0

        prediccion = motor.predecir_trafico(
            location_id, str(zone), fecha_futura, 
            visitas_ayer, visitas_7, visitas_14, media_7, std_7
        )
        
        if prediccion == -1:
            print("[HERRAMIENTA ERROR] El motor devolvio -1.")
            return "Error interno en el calculo de la prediccion."
            
        print(f"[HERRAMIENTA EXITO] Prediccion: {prediccion}")
        return f"Prediccion final para el {fecha_futura}: {prediccion} visitantes."
    except Exception as e:
        print(f"[HERRAMIENTA CRASH] Fallo: {str(e)}")
        return f"Error en la herramienta: {str(e)}"

texto_tiendas = ""
try:
    with open('todas_las_ubicaciones.json', 'r', encoding='utf-8') as f:
        datos = json.load(f)
        for empresa in datos:
            empresa_name = empresa.get('name', 'Empresa Desconocida')
            texto_tiendas += f"\nEmpresa: {empresa_name}\n"
            for loc in empresa.get('locations', []):
                loc_name = loc.get('name', 'Ubicacion Desconocida')
                loc_uuid = loc.get('uuid', '')
                if loc_name and loc_uuid:
                    texto_tiendas += f"  - Ubicacion: '{loc_name}' -> UUID: {loc_uuid}\n"
                    zonas_names = [z.get('zoneName') for z in loc.get('zones', []) if z.get('zoneName')]
                    if zonas_names:
                        texto_tiendas += f"    Zonas: {', '.join(zonas_names)}\n"
        print(texto_tiendas)
except Exception as e:
    texto_tiendas = f"Error cargando tiendas: {e}"

hoy_str = datetime.now().strftime("%Y-%m-%d")

instrucciones_sistema = f"""
Eres Valdi, el asistente de inteligencia artificial predictiva. Eres directo y profesional. 
Usa SIEMPRE tu herramienta de prediccion cuando te pregunten por el futuro o previsiones.

FECHA ACTUAL: 
Hoy es {hoy_str}. Usa esta fecha como referencia matematica para calcular exactamente que dia es "mañana", "pasado mañana", etc. y pasale a la herramienta SIEMPRE el formato YYYY-MM-DD.

IMPORTANTE - DICCIONARIO ESTRUCTURADO DE UBICACIONES:
El usuario usara el nombre de la ubicacion o de la empresa. La herramienta necesita el UUID EXACTO de la ubicacion.
Busca en esta estructura el UUID correspondiente a la ubicacion solicitada:
{texto_tiendas}

ZONAS DE LA HERRAMIENTA (Debes pasarle a la herramienta SOLO el numero en formato texto):
- "Caja", "Pagos" o "Cobro" -> "0"
- "Tienda", "Interior" o "Dentro" -> "1"
- "Calle", "Escaparate" o "Exterior" -> "2"
- "Extra" u "Otros" -> "3"
"""

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

config = types.GenerateContentConfig(
    system_instruction=instrucciones_sistema,
    tools=[herramienta_predecir_trafico],
    temperature=0.2,
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False)
)

chat_session = client.chats.create(model="gemini-2.5-flash", config=config)

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.LUX])
app.title = "Valdi IA"

app.layout = dbc.Container([
    html.Br(),
    dbc.Row([
        dbc.Col(html.H2("Valdi Intelligence", style={"fontWeight": "bold", "letterSpacing": "2px"}), width=8),
        dbc.Col(dbc.Button("Sincronizar y Reentrenar", id="btn-sync", color="primary", className="w-100 fw-bold", style={"borderRadius": "25px"}), width=4)
    ], className="mb-3 align-items-center"),
    
    dbc.Row(dbc.Col(
        dcc.Loading(
            id="loading-sync",
            type="circle",
            color="#2c3e50",
            children=html.Div(id="sync-status", className="text-center text-success fw-bold mb-3")
        )
    )),

    dbc.Row(dbc.Col(
        dbc.Card(
            dbc.CardBody(
                html.Div(id="chat-history", style={
                    "height": "60vh", 
                    "overflowY": "auto", 
                    "padding": "20px", 
                    "backgroundColor": "#f4f6f9", 
                    "borderRadius": "10px",
                    "display": "flex",
                    "flexDirection": "column"
                })
            ),
            className="shadow-lg border-0 mb-4",
            style={"borderRadius": "15px"}
        )
    )),
    
    dbc.Row([
        dbc.Col(
            dbc.Input(
                id="user-input", 
                placeholder="Pregunta por la prevision de trafico...", 
                type="text", 
                n_submit=0,
                style={"borderRadius": "25px", "padding": "12px 20px"}
            ), 
            width=10
        ),
        dbc.Col(
            dbc.Button(
                "Enviar", 
                id="send-button", 
                color="dark", 
                className="w-100 fw-bold",
                style={"borderRadius": "25px", "padding": "12px"}
            ), 
            width=2
        )
    ])
], fluid=True, style={"maxWidth": "1000px", "paddingTop": "20px"})

@app.callback(
    Output("sync-status", "children"),
    Input("btn-sync", "n_clicks"),
    prevent_initial_call=True
)
def run_sync(n_clicks):
    global motor
    try:
        subprocess.run(["python", "update_and_train.py"], check=True)
        motor = MotorPredictivo()
        return "Sincronizacion finalizada: Datos al dia y modelos actualizados."
    except subprocess.CalledProcessError as e:
        return f"Error en el script de actualizacion. Revisa la consola."
    except Exception as e:
        return f"Error: {str(e)}"

@app.callback(
    Output("chat-history", "children"),
    Output("user-input", "value"),
    Input("send-button", "n_clicks"),
    Input("user-input", "n_submit"),
    State("user-input", "value"),
    State("chat-history", "children"),
    prevent_initial_call=True
)
def update_chat(n_clicks, n_submit, user_input, chat_history):
    if not user_input:
        return chat_history, ""
        
    if chat_history is None:
        chat_history = []

    burbuja_usuario = html.Div([
        html.Div(user_input, style={
            "backgroundColor": "#2c3e50", 
            "color": "white", 
            "padding": "12px 18px", 
            "borderRadius": "20px 20px 0px 20px", 
            "maxWidth": "75%",
            "display": "inline-block",
            "boxShadow": "0 2px 4px rgba(0,0,0,0.1)"
        })
    ], style={"textAlign": "right", "marginBottom": "15px", "width": "100%"})
    
    chat_history.append(burbuja_usuario)

    try:
        print(f"\n[USUARIO HA ESCRITO]: {user_input}")
        respuesta = chat_session.send_message(user_input)
        texto_respuesta = respuesta.text
        
        if not texto_respuesta:
            if respuesta.function_calls:
                texto_respuesta = "Fallo del SDK: La IA intento usar la herramienta pero no se ejecuto de forma automatica."
            else:
                texto_respuesta = f"Gemini devolvio una respuesta vacia. Crudo: {respuesta}"
                
        print(f"[RESPUESTA GEMINI]: {texto_respuesta}")
        
    except Exception as e:
        texto_respuesta = f"Error critico de conexion con IA: {str(e)}"
        print(f"[ERROR IA]: {str(e)}")

    burbuja_bot = html.Div([
        html.Div([
            dcc.Markdown(texto_respuesta, style={"margin": "0"})
        ], style={
            "backgroundColor": "#ffffff", 
            "color": "#333333", 
            "padding": "12px 18px", 
            "borderRadius": "20px 20px 20px 0px", 
            "maxWidth": "75%",
            "display": "inline-block",
            "boxShadow": "0 2px 4px rgba(0,0,0,0.05)",
            "border": "1px solid #eaeaea"
        })
    ], style={"textAlign": "left", "marginBottom": "15px", "width": "100%"})

    chat_history.append(burbuja_bot)

    return chat_history, ""

if __name__ == "__main__":
    app.run(debug=True, port=8050)