import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

def cargar_memoria_geografica(ruta_archivo):
    memoria_geo = {}
    if os.path.exists(ruta_archivo):
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            datos_antiguos = json.load(f)
            
        for org in datos_antiguos:
            for loc in org.get('locations', []):
                if 'postal_code' in loc:
                    memoria_geo[loc['uuid']] = {
                        'postal_code': loc.get('postal_code'),
                        'region_code': loc.get('region_code'),
                        'country_code': loc.get('country_code'),
                        'lat': loc.get('lat'),
                        'lon': loc.get('lon')
                    }
    return memoria_geo

def descargar_maestro_ubicaciones():
    api_key = os.getenv("AITANNA_API_KEY")
    if not api_key:
        print("Error: No se ha encontrado AITANNA_API_KEY en el archivo .env")
        return

    url = "https://platform.aitanna.ai/api/v1/get-all-locations-and-zones"
    headers = {"x-api-key": api_key}
    ruta_json = 'src/data/todas_las_ubicaciones.json'
    
    print("Conectando con la API de Aitanna para descargar el árbol de ubicaciones...")
    
    try:
        res = requests.get(url, headers=headers, timeout=15)
        
        if res.status_code == 200:
            datos_frescos = res.json()
            memoria_geo = cargar_memoria_geografica(ruta_json)
            
            for org in datos_frescos:
                for loc in org.get('locations', []):
                    if loc['uuid'] in memoria_geo:
                        loc.update(memoria_geo[loc['uuid']])
                        
            with open(ruta_json, 'w', encoding='utf-8') as f:
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