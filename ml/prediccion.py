import pandas as pd
import numpy as np
import xgboost as xgb
import joblib
import holidays
from datetime import datetime

class MotorPredictivo:
    def __init__(self, ruta_modelos="models/"):
        self.ruta_modelos = ruta_modelos
        self.le_loc = joblib.load(f"{ruta_modelos}encoder_locations.pkl")
        self.le_zone = joblib.load(f"{ruta_modelos}encoder_zones.pkl")
        self.festivos_espana = holidays.Spain(years=[2025, 2026])
        self.modelos_cargados = {}

    def obtener_modelo_zona(self, zone_encoded):
        if zone_encoded not in self.modelos_cargados:
            modelo = xgb.XGBRegressor()
            ruta_modelo = f"{self.ruta_modelos}modelo_valdi_zona_{zone_encoded}.json"
            modelo.load_model(ruta_modelo)
            self.modelos_cargados[zone_encoded] = modelo
        return self.modelos_cargados[zone_encoded]

    def predecir_trafico(self, location_id: str, zone_name: str, fecha_objetivo: str, 
                         visitas_ayer: int, visitas_hace_7_dias: int, visitas_hace_14_dias: int, 
                         media_7_dias: float, std_7_dias: float) -> int:
        """
        Calcula la predicción exacta usando el modelo especialista de la zona.
        """
        try:
            loc_encoded = self.le_loc.transform([location_id])[0]
            zone_encoded = self.le_zone.transform([str(zone_name)])[0]
            
            fecha_dt = datetime.strptime(fecha_objetivo, "%Y-%m-%d")
            day_of_week = fecha_dt.weekday()
            month = fecha_dt.month
            day_of_month = fecha_dt.day
            is_weekend = 1 if day_of_week >= 5 else 0
            es_festivo = 1 if fecha_dt.date() in self.festivos_espana else 0
            
            datos_entrada = pd.DataFrame([{
                'location_encoded': loc_encoded,
                'zone_encoded': zone_encoded,
                'day_of_week': day_of_week,
                'month': month,
                'day_of_month': day_of_month,
                'is_weekend': is_weekend,
                'es_festivo': es_festivo,
                'lag_1': visitas_ayer,
                'lag_7': visitas_hace_7_dias,
                'lag_14': visitas_hace_14_dias,
                'rolling_mean_7': media_7_dias,
                'rolling_std_7': std_7_dias
            }])
            
            modelo_especialista = self.obtener_modelo_zona(zone_encoded)
            prediccion_log = modelo_especialista.predict(datos_entrada)[0]
            
            prediccion_real = np.expm1(prediccion_log)
            
            return max(0, int(round(prediccion_real)))
            
        except Exception as e:
            print(f"Error en predicción: {e}")
            return -1