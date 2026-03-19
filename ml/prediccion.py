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
        self.features = ['location_encoded', 'zone_encoded', 'day_of_week', 'month', 'day_of_month', 'is_weekend', 'es_festivo', 'lag_1', 'lag_7', 'lag_14', 'rolling_mean_7', 'rolling_std_7']
        os.makedirs(self.models_dir, exist_ok=True)

    def _calculate_smape(self, y_true, y_pred):
        denominator = (np.abs(y_true) + np.abs(y_pred)) / 2.0
        diff = np.abs(y_true - y_pred) / denominator
        diff[denominator == 0] = 0.0
        return np.mean(diff) * 100

    def entrenar(self, df):
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

        fecha_corte = df['fecha'].max() - pd.Timedelta(days=30)

        print("INICIANDO ENTRENAMIENTO Y EVALUACION POR ZONAS...")
        for z_enc in df['zone_encoded'].unique():
            df_z = df[df['zone_encoded'] == z_enc].copy()
            zona_nombre = le_zone.inverse_transform([z_enc])[0]
            
            train = df_z[df_z['fecha'] <= fecha_corte].copy()
            test = df_z[df_z['fecha'] > fecha_corte].copy()
            
            if len(train) == 0 or len(test) == 0:
                print(f"Zona {zona_nombre} (Cod: {z_enc}): No hay suficientes datos para evaluar.")
                continue

            X_train, y_train = train[self.features], np.log1p(train['total_visits'])
            X_test, y_test = test[self.features], np.log1p(test['total_visits'])
            
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
            smape = self._calculate_smape(y_test_real.values, pred_reales)
            
            print(f"Modelo Zona '{zona_nombre}' (Cod: {z_enc}) actualizado -> MAE: +- {mae:.0f} visitas | sMAPE: {smape:.2f}%")
            
            model.save_model(os.path.join(self.models_dir, f'modelo_valdi_zona_{z_enc}.json'))

        joblib.dump(le_loc, os.path.join(self.models_dir, 'encoder_locations.pkl'))
        joblib.dump(le_zone, os.path.join(self.models_dir, 'encoder_zones.pkl'))
        print("PROCESO COMPLETADO: Modelos y Encoders guardados.")

    def predecir_trafico(self, location_id, zone, fecha_futura, lag_1, lag_7, lag_14, rolling_mean_7, rolling_std_7):
        try:
            le_loc = joblib.load(os.path.join(self.models_dir, 'encoder_locations.pkl'))
            le_zone = joblib.load(os.path.join(self.models_dir, 'encoder_zones.pkl'))
            
            loc_enc = le_loc.transform([str(location_id)])[0]
            zone_enc = le_zone.transform([str(zone)])[0]
            
            model_path = os.path.join(self.models_dir, f'modelo_valdi_zona_{zone_enc}.json')
            if not os.path.exists(model_path):
                return -1
                
            model = xgb.XGBRegressor()
            model.load_model(model_path)
            
            target_date = pd.to_datetime(fecha_futura)
            esp_holidays = holidays.Spain(years=[target_date.year])
            es_festivo = 1 if target_date in esp_holidays else 0
            
            X = pd.DataFrame([{
                'location_encoded': loc_enc,
                'zone_encoded': zone_enc,
                'day_of_week': target_date.dayofweek,
                'month': target_date.month,
                'day_of_month': target_date.day,
                'is_weekend': 1 if target_date.dayofweek in [5, 6] else 0,
                'es_festivo': es_festivo,
                'lag_1': lag_1,
                'lag_7': lag_7,
                'lag_14': lag_14,
                'rolling_mean_7': rolling_mean_7,
                'rolling_std_7': rolling_std_7
            }])[self.features]
            
            pred_log = model.predict(X)[0]
            return int(np.maximum(0, np.expm1(pred_log)))
        except Exception:
            return -1