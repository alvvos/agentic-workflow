import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

def descargar_maestro_ubicaciones():
    api_key = os.getenv("AITANNA_API_KEY")
    if not api_key:
        print("Error: No se ha encontrado AITANNA_API_KEY en el archivo .env")
        return

    url = "https://platform.aitanna.ai/api/v1/get-all-locations-and-zones"
    headers = {"x-api-key": api_key}
    
    print("Conectando con la API de Aitanna para descargar el árbol de ubicaciones...")
    
    try:
        res = requests.get(url, headers=headers, timeout=15)
        
        if res.status_code == 200:
            datos_frescos = res.json()
            
            with open('todas_las_ubicaciones.json', 'w', encoding='utf-8') as f:
                json.dump(datos_frescos, f, ensure_ascii=False, indent=4)
                
            print("Exito: 'todas_las_ubicaciones.json' ha sido actualizado.")
            print(f"Organizaciones detectadas: {len(datos_frescos)}")
            
        else:
            print(f"Error de la API al descargar. Codigo HTTP: {res.status_code}")
            
    except requests.exceptions.Timeout:
        print("Error: La API tardo demasiado en responder (Timeout).")
    except Exception as e:
        print(f"Error critico de conexion: {str(e)}")

if __name__ == "__main__":
    descargar_maestro_ubicaciones()