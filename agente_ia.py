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

def herramienta_predecir_metrica(location_id: str, zone: str, fecha_futura: str, metrica: str) -> str:
    """Predice una metrica especifica (total_visits, unique_visitors, attraction_rate, etc.) para una fecha futura."""
    print(f"[HERRAMIENTA ACTIVADA] Metrica: {metrica} | Tienda: {location_id} | Zona: {zone} | Fecha: {fecha_futura}")
    try:
        df_historico = pd.read_csv('dataset_global_raw.csv')
        df_historico['fecha'] = pd.to_datetime(df_historico['fecha'])
        df_filtro = df_historico[(df_historico['location_id'] == location_id) & (df_historico['zone'].astype(str) == str(zone))]
        
        if df_filtro.empty:
            print("[HERRAMIENTA ERROR] No hay datos en el CSV para esa tienda/zona.")
            return "Error: No hay datos historicos suficientes para esa ubicacion y zona."

        df_diario = df_filtro.groupby('fecha')[metrica].mean().reset_index()
        df_diario = df_diario.set_index('fecha')
        target_date = datetime.strptime(fecha_futura, "%Y-%m-%d")
        
        ayer = target_date - timedelta(days=1)
        hace_7_dias = target_date - timedelta(days=7)
        hace_14_dias = target_date - timedelta(days=14)
        
        def obtener_valor_o_imputar(fecha_busqueda):
            if fecha_busqueda in df_diario.index:
                return float(df_diario.loc[fecha_busqueda, metrica])
            
            dia_semana = fecha_busqueda.weekday()
            df_mismo_dia = df_diario[df_diario.index.weekday == dia_semana]
            
            if not df_mismo_dia.empty:
                return float(df_mismo_dia[metrica].mean())
            elif not df_diario.empty:
                return float(df_diario[metrica].mean())
            return 0.0
            
        valor_ayer = obtener_valor_o_imputar(ayer)
        valor_7 = obtener_valor_o_imputar(hace_7_dias)
        valor_14 = obtener_valor_o_imputar(hace_14_dias)
        
        fecha_inicio_semana = target_date - timedelta(days=7)
        datos_semana = df_diario.loc[fecha_inicio_semana:ayer, metrica]
        
        if len(datos_semana) > 0:
            media_7 = float(datos_semana.mean())
            std_7 = float(datos_semana.std())
            if pd.isna(std_7): std_7 = 0.0
        elif not df_diario.empty:
            media_7 = float(df_diario[metrica].mean())
            std_7 = float(df_diario[metrica].std())
            if pd.isna(std_7): std_7 = 0.0
        else:
            media_7, std_7 = 0.0, 0.0

        prediccion = motor.predecir_metrica(
            location_id, str(zone), fecha_futura, metrica,
            valor_ayer, valor_7, valor_14, media_7, std_7
        )
        
        if prediccion == -1:
            print("[HERRAMIENTA ERROR] El motor devolvio -1. Modelo no encontrado.")
            return f"Error: No existe un modelo entrenado para la metrica '{metrica}' en esa zona."
            
        if metrica in ['total_visits', 'unique_visitors', 'new_visitors']:
            resultado_final = int(prediccion)
            unidad = "personas"
        elif metrica == 'attraction_rate':
            resultado_final = round(prediccion, 2)
            unidad = "%"
        elif metrica == 'dwell_time':
            resultado_final = round(prediccion, 2)
            unidad = "minutos"
        else:
            resultado_final = round(prediccion, 2)
            unidad = ""
            
        print(f"[HERRAMIENTA EXITO] Prediccion: {resultado_final} {unidad}")
        return f"Prediccion final de {metrica} para el {fecha_futura}: {resultado_final} {unidad}."
    except Exception as e:
        print(f"[HERRAMIENTA CRASH] Fallo: {str(e)}")
        return f"Error interno en la herramienta: {str(e)}"

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
except Exception as e:
    texto_tiendas = f"Error cargando tiendas: {e}"

hoy_str = datetime.now().strftime("%Y-%m-%d")

# 4. Instrucciones del Sistema para Gemini
instrucciones_sistema = f"""
Eres Valdi, el analista de inteligencia artificial predictiva avanzado del sector retail. 
Eres directo, profesional y muy preciso. Usa SIEMPRE tu herramienta de prediccion cuando te pregunten por el futuro o previsiones.

FECHA ACTUAL: 
Hoy es {hoy_str}. Usa esta fecha como referencia matematica para calcular exactamente que dia es "mañana", "pasado mañana", etc. y pasale a la herramienta SIEMPRE el formato YYYY-MM-DD.

IMPORTANTE - DICCIONARIO ESTRUCTURADO DE UBICACIONES:
El usuario usara el nombre de la ubicacion o de la empresa. La herramienta necesita el UUID EXACTO de la ubicacion.
Busca en esta estructura el UUID correspondiente a la ubicacion solicitada:
{texto_tiendas}

ZONAS (Debes pasarle a la herramienta SOLO el numero en formato texto):
- "Caja", "Pagos" o "Cobro" -> "0"
- "Tienda", "Interior" o "Dentro" -> "1"
- "Calle", "Escaparate" o "Exterior" -> "2"
- "Extra" u "Otros" -> "3"

METRICAS DISPONIBLES (El parametro 'metrica' debe ser EXACTAMENTE uno de estos textos):
- "total_visits" -> Úsalo si preguntan por trafico general, visitas o afluencia.
- "unique_visitors" -> Úsalo si preguntan por visitantes unicos.
- "new_visitors" -> Úsalo si preguntan por clientes nuevos.
- "attraction_rate" -> Úsalo si preguntan por ratio de atraccion o captacion de escaparate.
- "dwell_time" -> Úsalo si preguntan por tiempo de estancia o cuanto se quedan.
"""

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

config = types.GenerateContentConfig(
    system_instruction=instrucciones_sistema,
    tools=[herramienta_predecir_metrica],
    temperature=0.2,
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False)
)

chat_session = client.chats.create(model="gemini-2.5-flash", config=config)

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.LUX])
app.title = "Valdi IA - Multimétrica"

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
                placeholder="Ej: ¿Cual sera el tiempo de estancia en Gran Via interior mañana?", 
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

# 7. Callbacks
@app.callback(
    Output("sync-status", "children"),
    Input("btn-sync", "n_clicks"),
    prevent_initial_call=True
)
def run_sync(n_clicks):
    global motor
    try:
        subprocess.run(["python", "update_and_train.py"], check=True)
        motor = MotorPredictivo() # Recarga los modelos nuevos en memoria
        return "Sincronizacion finalizada: Todos los modelos multimétrica han sido reentrenados."
    except subprocess.CalledProcessError:
        return "Error en el script de actualizacion. Revisa la consola."
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
        print(f"\n[USUARIO]: {user_input}")
        respuesta = chat_session.send_message(user_input)
        texto_respuesta = respuesta.text
        
        if not texto_respuesta:
            if respuesta.function_calls:
                texto_respuesta = "Fallo del SDK: La IA intento usar la herramienta pero no obtuvo retorno automatico."
            else:
                texto_respuesta = f"Respuesta vacia o bloqueada por seguridad."
                
        print(f"[VALDI]: {texto_respuesta}")
        
    except Exception as e:
        texto_respuesta = f"Error critico de conexion con Gemini: {str(e)}"
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