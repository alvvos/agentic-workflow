import os
import numpy as np
import pandas as pd
import xgboost as xgb
import joblib
import holidays
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_absolute_error

class MotorPredictivo:
    def __init__(self, models_dir="models"):
        self.models_dir = models_dir
        self.metricas = ['total_visits', 'unique_visitors', 'new_visitors', 'attraction_rate', 'dwell_time']
        os.makedirs(self.models_dir, exist_ok=True)

    def entrenar(self, df):
        if df.empty: return
        print("Procesando datos para el entrenamiento Multimetrica...")
        
        df['fecha'] = pd.to_datetime(df['fecha'])
        df = df[df['fecha'] >= '2025-09-01']
        df = df[df['total_visits'] > 0] 
        
        df = df.groupby(['fecha', 'location_id', 'zone'])[self.metricas].mean().reset_index()
        df = df.sort_values(by=['location_id', 'zone', 'fecha']).reset_index(drop=True)
        
        esp_holidays = holidays.Spain(years=[2025, 2026])
        df['es_festivo'] = df['fecha'].dt.date.apply(lambda x: 1 if x in esp_holidays else 0)
        df['day_of_week'] = df['fecha'].dt.dayofweek
        df['month'] = df['fecha'].dt.month
        df['day_of_month'] = df['fecha'].dt.day
        df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)

        for m in self.metricas:
            df[f'lag_1_{m}'] = df.groupby(['location_id', 'zone'])[m].shift(1)
            df[f'lag_7_{m}'] = df.groupby(['location_id', 'zone'])[m].shift(7)
            df[f'lag_14_{m}'] = df.groupby(['location_id', 'zone'])[m].shift(14)
            df[f'rolling_mean_7_{m}'] = df.groupby(['location_id', 'zone'])[m].transform(lambda x: x.shift(1).rolling(7, 1).mean())
            df[f'rolling_std_7_{m}'] = df.groupby(['location_id', 'zone'])[m].transform(lambda x: x.shift(1).rolling(7, 1).std()).fillna(0)
        
        df = df.dropna().reset_index(drop=True)

        le_loc = LabelEncoder()
        le_zone = LabelEncoder()
        df['location_encoded'] = le_loc.fit_transform(df['location_id'].astype(str))
        df['zone_encoded'] = le_zone.fit_transform(df['zone'].astype(str))

        fecha_corte = df['fecha'].max() - pd.Timedelta(days=30)

        print("INICIANDO ENTRENAMIENTO MULTIMODELO...")
        for z_enc in df['zone_encoded'].unique():
            df_z = df[df['zone_encoded'] == z_enc].copy()
            zona_nombre = le_zone.inverse_transform([z_enc])[0]
            
            train = df_z[df_z['fecha'] <= fecha_corte].copy()
            test = df_z[df_z['fecha'] > fecha_corte].copy()
            
            if len(train) == 0 or len(test) == 0: continue

            for metrica in self.metricas:
                features = ['location_encoded', 'zone_encoded', 'day_of_week', 'month', 'day_of_month', 'is_weekend', 'es_festivo', 
                            f'lag_1_{metrica}', f'lag_7_{metrica}', f'lag_14_{metrica}', f'rolling_mean_7_{metrica}', f'rolling_std_7_{metrica}']
                
                X_train, y_train = train[features], train[metrica]
                X_test, y_test = test[features], test[metrica]
                
                model = xgb.XGBRegressor(n_estimators=1000, learning_rate=0.03, max_depth=5, early_stopping_rounds=50)
                model.fit(X_train, y_train, eval_set=[(X_train, y_train), (X_test, y_test)], verbose=0)
                
                pred = model.predict(X_test)
                mae = mean_absolute_error(y_test, pred)
                print(f"[{zona_nombre}] Modelo {metrica.upper()} -> MAE: {mae:.2f}")
                
                model.save_model(os.path.join(self.models_dir, f'modelo_valdi_zona_{z_enc}_{metrica}.json'))

        joblib.dump(le_loc, os.path.join(self.models_dir, 'encoder_locations.pkl'))
        joblib.dump(le_zone, os.path.join(self.models_dir, 'encoder_zones.pkl'))
        print("Modelos y Encoders guardados con exito.")

    def predecir_metrica(self, location_id, zone, fecha_futura, metrica, lag_1, lag_7, lag_14, rolling_mean_7, rolling_std_7):
        try:
            le_loc = joblib.load(os.path.join(self.models_dir, 'encoder_locations.pkl'))
            le_zone = joblib.load(os.path.join(self.models_dir, 'encoder_zones.pkl'))
            
            loc_enc = le_loc.transform([str(location_id)])[0]
            zone_enc = le_zone.transform([str(zone)])[0]
            
            model_path = os.path.join(self.models_dir, f'modelo_valdi_zona_{zone_enc}_{metrica}.json')
            if not os.path.exists(model_path): return -1
                
            model = xgb.XGBRegressor()
            model.load_model(model_path)
            
            target_date = pd.to_datetime(fecha_futura)
            es_festivo = 1 if target_date in holidays.Spain(years=[target_date.year]) else 0
            
            features = ['location_encoded', 'zone_encoded', 'day_of_week', 'month', 'day_of_month', 'is_weekend', 'es_festivo', 
                        f'lag_1_{metrica}', f'lag_7_{metrica}', f'lag_14_{metrica}', f'rolling_mean_7_{metrica}', f'rolling_std_7_{metrica}']
            
            X = pd.DataFrame([{
                'location_encoded': loc_enc, 'zone_encoded': zone_enc, 'day_of_week': target_date.dayofweek,
                'month': target_date.month, 'day_of_month': target_date.day, 'is_weekend': 1 if target_date.dayofweek in [5, 6] else 0,
                'es_festivo': es_festivo, f'lag_1_{metrica}': lag_1, f'lag_7_{metrica}': lag_7, 
                f'lag_14_{metrica}': lag_14, f'rolling_mean_7_{metrica}': rolling_mean_7, f'rolling_std_7_{metrica}': rolling_std_7
            }])[features]
            
            pred = model.predict(X)[0]
            return float(np.maximum(0, pred))
        except Exception as e:
            return -1