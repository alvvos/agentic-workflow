import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

def preparar_contexto_anomalias(df_resultados):
    df_anomalias = df_resultados[df_resultados['es_anomalia'] == 1].copy()
    if df_anomalias.empty:
        return "El tráfico operativo se ha mantenido dentro de los márgenes previstos por el algoritmo."

    contexto = "Registro de desviaciones contra la línea base predictiva:\n"
    for _, row in df_anomalias.iterrows():
        fecha = pd.to_datetime(row['fecha']).strftime('%Y-%m-%d')
        zona = row['Zona']
        real = int(row['total_visits'])
        esperado = int(row['prediccion'])
        desviacion = round(row['porcentaje_desviacion'], 1)
        contexto += f"{fecha} en {zona}: Tráfico real {real}, modelo esperaba {esperado} ({desviacion}%).\n"

    return contexto

def generar_insight_predictivo(df_resultados):
    contexto_anomalias = preparar_contexto_anomalias(df_resultados)

    if "márgenes previstos" in contexto_anomalias:
        return "El algoritmo confirma que no existen desviaciones operativas significativas."

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return "Falta configurar la credencial de acceso en el entorno."

    prompt = f"""
    Reglas de formato: Escribe estrictamente en formato de oración normal.
    Solo puedes usar mayúscula en la primera letra de cada frase y después de un punto.
    Reglas de negocio: El modelo matemático ha detectado las siguientes desviaciones en el tráfico.
    El modelo ya conoce el clima, el histórico de hasta veintiocho días y los festivos.
    Tu tarea es proponer una hipótesis de negocio que explique por qué la realidad rompió la predicción matemática.
    Propón una acción operativa correctiva basada en este hallazgo.

    Datos del residuo predictivo:
    {contexto_anomalias}
    """

    try:
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 300
            },
            timeout=30
        )
        if res.status_code == 200:
            return res.json()['choices'][0]['message']['content']
        return f"Error de respuesta en el proveedor cognitivo HTTP {res.status_code}."
    except Exception as e:
        return f"Fallo en la comunicación externa del servidor."