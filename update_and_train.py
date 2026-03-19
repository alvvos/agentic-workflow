import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from ml.prediccion import MotorPredictivo

load_dotenv()
AITANNA_API_KEY = os.getenv("AITANNA_API_KEY")
CSV_PATH = "dataset_global_raw.csv"

def obtener_uuids_completos():
    url = "https://platform.aitanna.ai/api/v1/get-all-locations-and-zones"
    headers = {"x-api-key": AITANNA_API_KEY}
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        return []
    
    datos = res.json()
    uuids = set()
    for org in datos:
        for loc in org.get("locations", []):
            if loc.get("uuid"):
                uuids.add(loc.get("uuid"))
            for zona in loc.get("zones", []):
                if zona.get("uuid"):
                    uuids.add(zona.get("uuid"))
    return list(uuids)

def peticion_dia(loc_id, fecha_str):
    url = f"https://platform.aitanna.ai/api/v1/internal/get-anonymous-report/location/{loc_id}/date/{fecha_str}"
    headers = {"x-api-key": AITANNA_API_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            return fecha_str, res.json()
    except Exception:
        pass
    return fecha_str, None

def actualizar_datos():
    if os.path.exists(CSV_PATH):
        df_old = pd.read_csv(CSV_PATH)
        df_old['fecha'] = pd.to_datetime(df_old['fecha'])
        ultima_fecha = df_old['fecha'].max()
    else:
        df_old = pd.DataFrame()
        ultima_fecha = datetime.today() - timedelta(days=365)

    fecha_hoy = datetime.today()
    dias_diferencia = (fecha_hoy - ultima_fecha).days
    
    if dias_diferencia <= 0:
        return df_old

    fechas_a_descargar = [(fecha_hoy - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(dias_diferencia + 1)]
    location_ids = obtener_uuids_completos()
    
    if not location_ids:
        return df_old

    filas_buffer = []
    
    for idx, loc_id in enumerate(location_ids, 1):
        with ThreadPoolExecutor(max_workers=10) as executor:
            futuros = [executor.submit(peticion_dia, loc_id, f) for f in fechas_a_descargar]
            for futuro in as_completed(futuros):
                fecha_str, datos = futuro.result()
                if datos:
                    for zona in datos:
                        filas_buffer.append({
                            "fecha": fecha_str,
                            "location_id": loc_id,
                            "zone": zona.get("zone", "N/A"),
                            "total_visits": zona.get("totalVisits", 0)
                        })

    if filas_buffer:
        df_new = pd.DataFrame(filas_buffer)
        df_new['fecha'] = pd.to_datetime(df_new['fecha'])
        df_final = pd.concat([df_old, df_new]).drop_duplicates(subset=['fecha', 'location_id', 'zone'])
        df_final.to_csv(CSV_PATH, index=False)
        return df_final
    
    return df_old

def pipeline_actualizacion():
    print("Iniciando pipeline de actualizacion...")
    df = actualizar_datos()
    motor = MotorPredictivo()
    motor.entrenar(df)

if __name__ == "__main__":
    pipeline_actualizacion()