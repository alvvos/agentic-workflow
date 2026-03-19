import os
import requests
import pandas as pd
import numpy as np
import xgboost as xgb
import joblib
import holidays
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_absolute_error
from datetime import datetime, timedelta
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

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

def calculate_smape(y_true, y_pred):
    denominator = (np.abs(y_true) + np.abs(y_pred)) / 2.0
    diff = np.abs(y_true - y_pred) / denominator
    diff[denominator == 0] = 0.0
    return np.mean(diff) * 100

def entrenar_modelos(df):
    if df.empty:
        print("No hay datos para entrenar.")
        return

    print("Procesando datos para el reentrenamiento...")
    df['fecha'] = pd.to_datetime(df['fecha'])
    df = df[df['fecha'] >= '2025-09-01']
    df = df[df['total_visits'] > 0]
    df = df.groupby(['fecha', 'location_id', 'zone']).agg({'total_visits': 'sum'}).reset_index()
    df = df.sort_values(by=['location_id', 'zone', 'fecha']).reset_index(drop=True)
    
    esp_holidays = holidays.Spain(years=[2025, 2026])
    df['es_festivo'] = df['fecha'].dt.date.apply(lambda x: 1 if x in esp_holidays else 0)
    df['day_of_week'] = df['fecha'].dt.dayofweek
    df['month'] = df['fecha'].dt.month
    df['day_of_month'] = df['fecha'].dt.day
    df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)

    df['lag_1'] = df.groupby(['location_id', 'zone'])['total_visits'].shift(1)
    df['lag_7'] = df.groupby(['location_id', 'zone'])['total_visits'].shift(7)
    df['lag_14'] = df.groupby(['location_id', 'zone'])['total_visits'].shift(14)
    df['rolling_mean_7'] = df.groupby(['location_id', 'zone'])['total_visits'].transform(lambda x: x.shift(1).rolling(7, 1).mean())
    df['rolling_std_7'] = df.groupby(['location_id', 'zone'])['total_visits'].transform(lambda x: x.shift(1).rolling(7, 1).std()).fillna(0)
    
    df = df.dropna().reset_index(drop=True)

    le_loc = LabelEncoder()
    le_zone = LabelEncoder()
    df['location_id'] = df['location_id'].astype(str)
    df['zone'] = df['zone'].astype(str)
    
    df['location_encoded'] = le_loc.fit_transform(df['location_id'])
    df['zone_encoded'] = le_zone.fit_transform(df['zone'])

    features = ['location_encoded', 'zone_encoded', 'day_of_week', 'month', 'day_of_month', 'is_weekend', 'es_festivo', 'lag_1', 'lag_7', 'lag_14', 'rolling_mean_7', 'rolling_std_7']

    os.makedirs("models", exist_ok=True)
    
    fecha_corte = df['fecha'].max() - pd.Timedelta(days=30)

    print("\n🚀 INICIANDO ENTRENAMIENTO Y EVALUACIÓN POR ZONAS...")
    for z_enc in df['zone_encoded'].unique():
        df_z = df[df['zone_encoded'] == z_enc].copy()
        zona_nombre = le_zone.inverse_transform([z_enc])[0]
        
        train = df_z[df_z['fecha'] <= fecha_corte].copy()
        test = df_z[df_z['fecha'] > fecha_corte].copy()
        
        if len(train) == 0 or len(test) == 0:
            print(f"Zona {zona_nombre} (Cod: {z_enc}): No hay suficientes datos para evaluar. Saltando...")
            continue

        X_train, y_train = train[features], np.log1p(train['total_visits'])
        X_test, y_test = test[features], np.log1p(test['total_visits'])
        
        model = xgb.XGBRegressor(
            n_estimators=1500, 
            learning_rate=0.03, 
            max_depth=6, 
            subsample=0.8, 
            colsample_bytree=0.8,
            early_stopping_rounds=70
        )
        
        model.fit(
            X_train, y_train,
            eval_set=[(X_train, y_train), (X_test, y_test)],
            verbose=0
        )

        pred_log = model.predict(X_test)
        pred_reales = np.maximum(0, np.expm1(pred_log))
        y_test_real = np.expm1(y_test)
        
        mae = mean_absolute_error(y_test_real, pred_reales)
        smape = calculate_smape(y_test_real.values, pred_reales)
        
        print(f"Modelo Zona '{zona_nombre}' (Cod: {z_enc}) actualizado -> MAE: +- {mae:.0f} visitas | sMAPE: {smape:.2f}%")
        
        model.save_model(f'models/modelo_valdi_zona_{z_enc}.json')

    joblib.dump(le_loc, 'models/encoder_locations.pkl')
    joblib.dump(le_zone, 'models/encoder_zones.pkl')
    print("PROCESO COMPLETADO: Modelos y Encoders guardados.")

def pipeline_actualizacion():
    print("Iniciando pipeline de actualización...")
    df = actualizar_datos()
    entrenar_modelos(df)

if __name__ == "__main__":
    pipeline_actualizacion()