import json
import requests
import pandas as pd
from datetime import datetime, timedelta
import os

def actualizar_cache_clima():
    with open('todas_las_ubicaciones.json', 'r', encoding='utf-8') as f:
        datos = json.load(f)
        
    ubicaciones = []
    for org in datos:
        for loc in org.get('locations', []):
            if 'lat' in loc and 'lon' in loc:
                ubicaciones.append({
                    'uuid': loc['uuid'],
                    'lat': loc['lat'],
                    'lon': loc['lon']
                })
                
    if not ubicaciones:
        return

    fecha_fin = datetime.now().strftime('%Y-%m-%d')
    fecha_inicio = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
    
    registros_clima = []
    
    for u in ubicaciones:
        url = f"https://archive-api.open-meteo.com/v1/archive?latitude={u['lat']}&longitude={u['lon']}&start_date={fecha_inicio}&end_date={fecha_fin}&daily=precipitation_sum&timezone=auto"
        
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                fechas = data['daily']['time']
                precipitaciones = data['daily']['precipitation_sum']
                
                for f_str, p in zip(fechas, precipitaciones):
                    llueve = 1 if p is not None and p > 0 else 0
                    registros_clima.append({
                        'fecha': f_str,
                        'location_uuid': u['uuid'],
                        'llueve': llueve
                    })
        except Exception:
            pass
            
    if registros_clima:
        df_clima = pd.DataFrame(registros_clima)
        os.makedirs('data/raw', exist_ok=True)
        df_clima.to_csv('data/raw/clima_cache.csv', index=False)

if __name__ == "__main__":
    actualizar_cache_clima()