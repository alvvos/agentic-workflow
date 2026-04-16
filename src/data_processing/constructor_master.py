import pandas as pd
import json
import requests
import holidays
import os

def cargar_csv_crudo(ruta_csv='dataset_global_raw.csv'):
    if not os.path.exists(ruta_csv):
        return None
    df = pd.read_csv(ruta_csv)
    df['fecha'] = pd.to_datetime(df['fecha'])
    return df

def enriquecer_datos_ubicacion(df_crudo, location_uuid, ruta_json='src/todas_las_ubicaciones.json'):
    df_loc = df_crudo[df_crudo['location_id'] == location_uuid].copy()
    if df_loc.empty:
        return df_loc

    lat, lon, region_code = 40.4168, -3.7038, 'MD'
    try:
        with open(ruta_json, 'r', encoding='utf-8') as f:
            datos_loc = json.load(f)
            for org in datos_loc:
                for loc in org.get('locations', []):
                    if loc['uuid'] == location_uuid:
                        lat = loc.get('latitude', lat)
                        lon = loc.get('longitude', lon)
                        region_code = loc.get('region_code', region_code)
                        break
    except:
        pass

    df_loc['region_code'] = region_code
    def asignar_festivo(fecha):
        try:
            cal = holidays.Spain(subdiv=region_code, years=fecha.year)
            return 1 if fecha in cal else 0
        except:
            return 0
    
    df_loc['es_festivo'] = df_loc['fecha'].apply(asignar_festivo)

    fecha_min = df_loc['fecha'].min().strftime('%Y-%m-%d')
    fecha_max = df_loc['fecha'].max().strftime('%Y-%m-%d')
    url_clima = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={fecha_min}&end_date={fecha_max}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=Europe%2FMadrid"
    
    try:
        respuesta = requests.get(url_clima).json()
        df_clima = pd.DataFrame({
            'fecha': pd.to_datetime(respuesta['daily']['time']),
            'temp_max': respuesta['daily']['temperature_2m_max'],
            'temp_min': respuesta['daily']['temperature_2m_min'],
            'precipitacion': respuesta['daily']['precipitation_sum']
        })
        df_clima['llueve'] = (df_clima['precipitacion'] > 0).astype(int)
        df_loc = pd.merge(df_loc, df_clima, on='fecha', how='left')
        df_loc['temp_max'] = df_loc['temp_max'].ffill()
        df_loc['temp_min'] = df_loc['temp_min'].ffill()
        df_loc['llueve'] = df_loc['llueve'].fillna(0)
    except:
        df_loc['temp_max'] = 22.0
        df_loc['temp_min'] = 15.0
        df_loc['llueve'] = 0

    return df_loc