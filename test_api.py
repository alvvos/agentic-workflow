import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()
AITANNA_API_KEY = os.getenv("AITANNA_API_KEY")

def guardar_json_prueba(loc_id, fecha_str):
    url = f"https://platform.aitanna.ai/api/v1/internal/get-anonymous-report/location/{loc_id}/date/{fecha_str}"
    headers = {"x-api-key": AITANNA_API_KEY}
    
    try:
        res = requests.get(url, headers=headers)
        datos = res.json()
        
        nombre_archivo = f"debug_api_{loc_id[:8]}_{fecha_str}.json"
        with open(nombre_archivo, 'w', encoding='utf-8') as f:
            json.dump(datos, f, indent=4, ensure_ascii=False)
            
        print(f"Archivo guardado con exito: {nombre_archivo}")
    except Exception as e:
        print(f"Error en la peticion: {e}")

if __name__ == "__main__":
    UBICACION_PRUEBA = "251e7f40-95c7-4678-aa48-df1b90e3461c"
    FECHA_PRUEBA = "2026-01-6"
    
    guardar_json_prueba(UBICACION_PRUEBA, FECHA_PRUEBA)