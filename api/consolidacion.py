import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
AITANNA_API_KEY = os.getenv("AITANNA_API_KEY")

def obtener_uuids_completos():
    print("Obteniendo la lista completa de ubicaciones y zonas de la plataforma...")
    url = "https://platform.aitanna.ai/api/v1/get-all-locations-and-zones"
    headers = {"x-api-key": AITANNA_API_KEY}
    res = requests.get(url, headers=headers)
    
    if res.status_code != 200:
        print(f"Error al obtener ubicaciones: HTTP {res.status_code}")
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
                    
    lista_uuids = list(uuids)
    print(f"¡Hecho! Se han extraído {len(lista_uuids)} UUIDs únicos para procesar.\n")
    return lista_uuids

def peticion_dia(loc_id, fecha_str):
    """Función aislada para que un 'hilo' la ejecute de forma independiente"""
    url = f"https://platform.aitanna.ai/api/v1/internal/get-anonymous-report/location/{loc_id}/date/{fecha_str}"
    headers = {"x-api-key": AITANNA_API_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            return fecha_str, res.json()
    except Exception:
        pass
    return fecha_str, None

def descargar_historico_global(dias_historia=365):
    location_ids = obtener_uuids_completos()
    
    if not location_ids:
        print("No se encontraron UUIDs. Saliendo...")
        return

    # Preparar fechas
    fecha_fin = datetime.today()
    fechas = [(fecha_fin - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(dias_historia + 1)]

    # Preparar el archivo de destino (si existe de una ejecución anterior, lo borramos para no duplicar)
    os.makedirs("../../data/raw", exist_ok=True)
    ruta_csv = "../../data/raw/dataset_global_raw.csv"
    if os.path.exists(ruta_csv):
        os.remove(ruta_csv)

    filas_buffer = [] # Nuestra memoria temporal
    
    print(f"Iniciando descarga acelerada de {dias_historia} días...")
    print("-" * 60)

    for idx, loc_id in enumerate(location_ids, 1):
        print(f"Procesando [{idx}/{len(location_ids)}] UUID: {loc_id} (Descargando 365 días en paralelo...)")
        
        # Lanzamos hasta 10 peticiones simultáneas
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Creamos todas las tareas
            futuros = [executor.submit(peticion_dia, loc_id, f) for f in fechas]
            
            # Recogemos los resultados a medida que cada hilo termina su petición
            for futuro in as_completed(futuros):
                fecha_str, datos = futuro.result()
                if datos:
                    for zona in datos:
                        filas_buffer.append({
                            "fecha": fecha_str,
                            "location_id": loc_id,
                            "zone": zona.get("zone", "N/A"),
                            "total_visits": zona.get("totalVisits", 0),
                            "unique_visitors": zona.get("uniqueVisitor", 0),
                            "new_visitors": zona.get("newVisitor", 0),
                            "attraction_rate": zona.get("attractionRate", 0),
                            "dwell_time": zona.get("dwellTime", 0)
                        })

        # --- SISTEMA DE GUARDADO PARCIAL CADA 5 LOCALIZACIONES ---
        if idx % 5 == 0 or idx == len(location_ids):
            if filas_buffer:
                df = pd.DataFrame(filas_buffer)
                # 'mode=a' significa Append. header=True solo si el archivo es nuevo.
                es_nuevo = not os.path.exists(ruta_csv)
                df.to_csv(ruta_csv, mode='a', header=es_nuevo, index=False)
                
                print(f"  => [PUNTO DE GUARDADO] Se han volcado {len(filas_buffer)} registros al CSV.")
                filas_buffer = [] # Vaciamos el búfer para liberar memoria RAM

    print("-" * 60)
    print(f"¡EXTRACCIÓN FINALIZADA Y SEGURA! Puedes revisar tu archivo en: {ruta_csv}")

if __name__ == "__main__":
    descargar_historico_global(365)