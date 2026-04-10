import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
AITANNA_API_KEY = os.getenv("AITANNA_API_KEY")

def obtener_uuids_completos():
    url = "https://platform.aitanna.ai/api/v1/get-all-locations-and-zones"
    headers = {"x-api-key": AITANNA_API_KEY}
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        print(f"Error obteniendo UUIDs. Código: {res.status_code}")
        return []
    datos = res.json()
    uuids = set()
    for org in datos:
        for loc in org.get("locations", []):
            if loc.get("uuid"): uuids.add(loc.get("uuid"))
    return list(uuids)

def peticion_dia(loc_id, fecha_str):
    url = f"https://platform.aitanna.ai/api/v1/internal/get-anonymous-report/location/{loc_id}/date/{fecha_str}"
    headers = {"x-api-key": AITANNA_API_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200: return fecha_str, res.json(), "OK"
        elif res.status_code == 404: return fecha_str, None, "404 No Data"
        else: return fecha_str, None, f"Error {res.status_code}"
    except Exception as e:
        return fecha_str, None, f"Exception: {str(e)}"

def actualizar_datos_csv(ubicaciones_seleccionadas=None, archivo_destino="/datadataset_global_raw.csv"):
    if os.path.exists(archivo_destino):
        df_master = pd.read_csv(archivo_destino)
        df_master['fecha'] = pd.to_datetime(df_master['fecha'])
        print(f"Archivo detectado con {len(df_master)} registros.")
    else:
        df_master = pd.DataFrame()
        print("Empezando descarga masiva desde cero...")

    location_ids = ubicaciones_seleccionadas if ubicaciones_seleccionadas else obtener_uuids_completos()
    if not location_ids: return df_master

    fecha_hoy = datetime.today()
    total_locs = len(location_ids)

    registros_nuevos_totales = 0

    for idx, loc_id in enumerate(location_ids, 1):
        if not df_master.empty and 'location_id' in df_master.columns and loc_id in df_master['location_id'].values:
            ultima_fecha_loc = df_master[df_master['location_id'] == loc_id]['fecha'].max()
        else:
            ultima_fecha_loc = datetime.strptime("2025-09-01", "%Y-%m-%d")

        dias_diferencia = (fecha_hoy - ultima_fecha_loc).days
        if dias_diferencia <= 0: continue

        fechas_a_descargar = [(fecha_hoy - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(dias_diferencia + 1)]
        print(f"[{idx:02d}/{total_locs}] UUID: {loc_id[:8]}... | Descargando {len(fechas_a_descargar):03d} días...", end="\r")

        filas_buffer = []

        with ThreadPoolExecutor(max_workers=5) as executor:
            futuros = [executor.submit(peticion_dia, loc_id, f) for f in fechas_a_descargar]
            for futuro in as_completed(futuros):
                fecha_str, datos, status = futuro.result()
                
                if status == "OK" and datos:
                    for zona in datos:
                        hours_data = zona.get("visitorsHour", [])
                        hourly_array = [h.get("value", 0) for h in sorted(hours_data, key=lambda x: x.get("hour", 0))] if isinstance(hours_data, list) else [0]*24
                        
                        filas_buffer.append({
                            "fecha": fecha_str,
                            "location_id": loc_id,
                            "zone_uuid": zona.get("zoneUUID", ""),
                            "total_visits": zona.get("totalVisits", 0),
                            "unique_visitors": zona.get("uniqueVisitor", 0),
                            "new_visitors": zona.get("newVisitor", 0), 
                            
                            "uv_7d": zona.get("uniqueVisitorLast7days", 0),
                            "uv_28d": zona.get("uniqueVisitorLast28days", 0),
                            "uv_month": zona.get("uniqueVisitorCurrentMonth", 0),
                            "uv_year": zona.get("uniqueVisitorCurrentYear", 0),
                            
                            "freq_7d": zona.get("frequencyLast7days", 0.0), 
                            "freq_28d": zona.get("frequencyLast28days", 0.0),
                            "freq_month": zona.get("frequencyCurrentMonth", 0.0),
                            "freq_year": zona.get("frequencyCurrentYear", 0.0),
                            
                            "dwell_time": zona.get("dwellTime", 0.0),
                            "dwell_hist": str(zona.get("dwellTimeHistogram", [])), 
                            "hourly_visits": str(hourly_array)
                        })

        if filas_buffer:
            df_new = pd.DataFrame(filas_buffer)
            df_new['fecha'] = pd.to_datetime(df_new['fecha'])
            df_master = pd.concat([df_master, df_new]).drop_duplicates(subset=['fecha', 'location_id', 'zone_uuid'])
            df_master.to_csv(archivo_destino, index=False)
            registros_nuevos_totales += len(df_new)
            print(f"[{idx:02d}/{total_locs}] UUID: {loc_id[:8]}... | Guardado ({len(df_new):03d} regs).")
        else:
            print(f"[{idx:02d}/{total_locs}] UUID: {loc_id[:8]}... | Sin datos.               ")

    print(f"\nSincronización finalizada. Registros descargados hoy: {registros_nuevos_totales}")
    return df_master

if __name__ == "__main__":
    actualizar_datos_csv()