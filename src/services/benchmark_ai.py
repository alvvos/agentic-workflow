import os
import json
import pandas as pd
from datetime import timedelta
import google.generativeai as genai
import holidays
from src.data_processing.data_radar import obtener_info_ubicacion, obtener_clima_historico

# Configura tu API Key (Lo ideal es tenerla en variables de entorno)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

festivos_espana = holidays.ES(years=[2024, 2025, 2026])
RUTA_JSON = 'src/data/todas_las_ubicaciones.json'

def obtener_org_por_ubicacion(ubi_nombre):
    """Busca el nombre de la organización (ej. Miniso España) a partir del nombre de la ubicación."""
    if os.path.exists(RUTA_JSON):
        try:
            with open(RUTA_JSON, 'r', encoding='utf-8') as f:
                datos = json.load(f)
                for org in datos:
                    for loc in org.get('locations', []):
                        if loc.get('name') == ubi_nombre:
                            return org.get('name', 'Organización Desconocida')
        except Exception:
            pass
    return 'Organización Desconocida'

def generar_benchmark_contextual(ubi_nombre, fecha_max_str):
    try:
        fecha_max = pd.to_datetime(fecha_max_str)
        fecha_7d = fecha_max - timedelta(days=7)
        fecha_28d = fecha_max - timedelta(days=28)
        
        # 1. Extracción de contexto
        org_name = obtener_org_por_ubicacion(ubi_nombre)
        lat, lon, reg = obtener_info_ubicacion(ubi_nombre)
        clima_reciente = obtener_clima_historico(lat, lon, fecha_28d.strftime('%Y-%m-%d'), fecha_max.strftime('%Y-%m-%d'))
        
        dias_lluvia_7d = sum(1 for d, vals in clima_reciente.items() if pd.to_datetime(d) >= fecha_7d and vals.get('precip', 0) > 2)
        dias_lluvia_28d = sum(1 for d, vals in clima_reciente.items() if vals.get('precip', 0) > 2)
        
        festivos_7d = [festivos_espana.get(fecha_max - timedelta(days=i)) for i in range(7) if (fecha_max - timedelta(days=i)) in festivos_espana]
        
        # 2. Construcción del Prompt (Sin Sector y con la Organización dinámica)
        prompt = f"""
        Eres un Analista de Datos Senior en Retail. Calcula el 'Benchmark de Atracción Teórico' (porcentaje de conversión de Calle a Tienda).
        
        DATOS DE LA UBICACIÓN:
        - Marca/Organización: {org_name}
        - Ubicación: {ubi_nombre}
        - Región: {reg}
        
        CONTEXTO EXÓGENO:
        - Clima Últimos 7D: {dias_lluvia_7d} días de lluvia significativa.
        - Clima Últimos 28D: {dias_lluvia_28d} días de lluvia significativa.
        - Festivos recientes (7D): {', '.join(filter(None, festivos_7d)) if festivos_7d else 'Ninguno'}
        
        Devuelve ÚNICAMENTE un JSON válido con esta estructura exacta, sin markdown ni comillas invertidas:
        {{
            "ratio_7d":,
            "ratio_28d":,
            "justificacion": "Texto formal de máximo 4 líneas explicando el impacto del clima y festivos en este benchmark."
        }}
        """
        
        model = genai.GenerativeModel('gemini-2.5-flash-lite', generation_config={"response_mime_type": "application/json"})
        response = model.generate_content(prompt)
        
        return json.loads(response.text)
        
    except Exception as e:
        return {"error": str(e)}