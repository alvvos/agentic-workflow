import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import mean_absolute_error
import holidays
import gc
from datetime import timedelta

# Instanciamos el calendario oficial para el futuro
festivos_espana = holidays.ES(years=[2024, 2025, 2026])

def ejecutar_auditoria_predictiva(df_master, location_uuid, zone_uuid, falso_hoy, horizonte_dias):
    modelo = None
    try:
        # 1. EXTRACCIÓN DE HISTÓRICO
        df_tienda = df_master[(df_master['location_id'] == location_uuid) & 
                              (df_master['zone_uuid'] == zone_uuid)].copy()
        
        if df_tienda.empty:
            return {"error": "No hay datos históricos para esta zona."}

        df_tienda['fecha'] = pd.to_datetime(df_tienda['fecha'])
        df_tienda = df_tienda.groupby('fecha').agg({
            'total_visits': 'sum',
            'llueve': 'max',
            'temp_max': 'max',
            'temp_min': 'min',
            'es_festivo': 'max'
        }).reset_index().sort_values('fecha').reset_index(drop=True)

        # 2. SEPARACIÓN DEL PASADO (TRAIN SET)
        fecha_corte = pd.to_datetime(falso_hoy)
        train = df_tienda[df_tienda['fecha'] < fecha_corte].copy()
        
        if len(train) < 30:
            return {"error": "Muestra histórica insuficiente para entrenar (mínimo 30 días previos)."}

        # Generación de variables temporales para el entrenamiento
        train['es_finde'] = train['fecha'].dt.dayofweek.isin([5, 6]).astype(int)
        train['dia_semana'] = train['fecha'].dt.dayofweek
        train['dia_mes'] = train['fecha'].dt.day
        train['mes'] = train['fecha'].dt.month
        train['quincena'] = (train['dia_mes'] > 15).astype(int)
        train['vispera_festivo'] = train['fecha'].apply(lambda d: 1 if (d + timedelta(days=1)) in festivos_espana else 0)
        
        train['mucho_calor'] = (train['temp_max'] >= 32.0).astype(int)
        train['mucho_frio'] = (train['temp_min'] <= 8.0).astype(int)
        train['clima_ideal'] = ((train['temp_max'] >= 18.0) & (train['temp_max'] <= 26.0) & (train['llueve'] == 0)).astype(int)
        train['finde_lluvioso'] = train['es_finde'] * train['llueve']

        # Variables Autorregresivas (Lags)
        train['lag_1d'] = train['total_visits'].shift(1)
        train['lag_7d'] = train['total_visits'].shift(7)
        train['media_7d'] = train['total_visits'].rolling(7).mean()
        train['lag_14d'] = train['total_visits'].shift(14)
        train['media_14d'] = train['total_visits'].rolling(14).mean()
        train['std_7d'] = train['total_visits'].rolling(7).std().fillna(0)
        
        train = train.dropna().reset_index(drop=True)

        features = ['es_finde', 'es_festivo', 'llueve', 'dia_semana', 'dia_mes', 'mes', 
                    'lag_1d', 'lag_7d', 'media_7d', 'quincena', 'vispera_festivo', 
                    'lag_14d', 'media_14d', 'std_7d', 'finde_lluvioso', 'mucho_calor', 'mucho_frio', 'clima_ideal']
        
        X_train, y_train = train[features], train['total_visits']

        # 3. ENTRENAMIENTO HERMÉTICO
        # Usamos el último 15% del pasado para validación interna y early stopping
        split_idx = int(len(X_train) * 0.85)
        X_t, y_t = X_train.iloc[:split_idx], y_train.iloc[:split_idx]
        X_v, y_v = X_train.iloc[split_idx:], y_train.iloc[split_idx:]

        modelo = xgb.XGBRegressor(
            n_estimators=250, 
            learning_rate=0.05, 
            max_depth=4, 
            random_state=42,
            early_stopping_rounds=20 
        )
        
        modelo.fit(X_t, y_t, eval_set=[(X_t, y_t), (X_v, y_v)], verbose=False)

        # 4. PREDICCIÓN AUTORREGRESIVA HACIA EL FUTURO
        df_work = df_tienda[df_tienda['fecha'] < fecha_corte].copy()
        fechas_pred = []
        valores_pred = []
        valores_reales = []

        for i in range(horizonte_dias):
            current_date = fecha_corte + timedelta(days=i)
            fechas_pred.append(current_date.strftime('%Y-%m-%d'))
            
            # Buscar datos reales (por si simulamos sobre el pasado)
            real_row = df_tienda[df_tienda['fecha'] == current_date]
            tiene_real = not real_row.empty
            
            # Gestión Exógena: Si es el futuro puro, asumimos clima medio
            llueve = real_row['llueve'].values[0] if tiene_real else 0
            t_max = real_row['temp_max'].values[0] if tiene_real else 22.0
            t_min = real_row['temp_min'].values[0] if tiene_real else 12.0
            
            real_visits = real_row['total_visits'].values[0] if tiene_real else None
            valores_reales.append(real_visits)

            es_festivo = 1 if current_date in festivos_espana else 0
            es_finde = 1 if current_date.dayofweek in [5, 6] else 0

            # Cálculo en bucle de los Lags (Se alimentan de las propias predicciones generadas)
            visits_array = df_work['total_visits'].values
            lag_1d = visits_array[-1] if len(visits_array) >= 1 else 0
            lag_7d = visits_array[-7] if len(visits_array) >= 7 else 0
            lag_14d = visits_array[-14] if len(visits_array) >= 14 else 0
            media_7d = np.mean(visits_array[-7:]) if len(visits_array) >= 7 else 0
            media_14d = np.mean(visits_array[-14:]) if len(visits_array) >= 14 else 0
            std_7d = np.std(visits_array[-7:]) if len(visits_array) >= 7 else 0

            row = pd.DataFrame([{
                'es_finde': es_finde,
                'es_festivo': es_festivo,
                'llueve': llueve,
                'dia_semana': current_date.dayofweek,
                'dia_mes': current_date.day,
                'mes': current_date.month,
                'lag_1d': lag_1d,
                'lag_7d': lag_7d,
                'media_7d': media_7d,
                'quincena': 1 if current_date.day > 15 else 0,
                'vispera_festivo': 1 if (current_date + timedelta(days=1)) in festivos_espana else 0,
                'lag_14d': lag_14d,
                'media_14d': media_14d,
                'std_7d': std_7d,
                'finde_lluvioso': es_finde * llueve,
                'mucho_calor': 1 if t_max >= 32.0 else 0,
                'mucho_frio': 1 if t_min <= 8.0 else 0,
                'clima_ideal': 1 if (18.0 <= t_max <= 26.0 and llueve == 0) else 0
            }])

            # Predicción del día X
            pred = np.maximum(0, np.round(modelo.predict(row[features])[0]))
            valores_pred.append(pred)

            # Inyectamos la predicción en el array histórico para poder calcular el día X+1
            new_row = pd.DataFrame({'fecha': [current_date], 'total_visits': [pred]})
            df_work = pd.concat([df_work, new_row], ignore_index=True)

        # 5. CÁLCULO INTELIGENTE DE MÉTRICAS
        # Separamos la parte real de la pura ficción para que las matemáticas no exploten
        reales_validos = [r for r in valores_reales if pd.notna(r)]
        pred_validos = valores_pred[:len(reales_validos)]

        if len(reales_validos) > 0:
            mae = mean_absolute_error(reales_validos, pred_validos)
            sum_reales = np.sum(reales_validos)
            wmape = np.sum(np.abs(np.array(reales_validos) - np.array(pred_validos))) / sum_reales if sum_reales > 0 else 0
            
            acc_val = round((1 - wmape) * 100, 2)
            mae_val = round(mae, 1)
            wmape_val = round(wmape * 100, 2)
        else:
            # Si es el futuro puro, mostramos N/A
            acc_val = "N/A"
            mae_val = "N/A"
            wmape_val = "N/A"

        return {
            "status": "success",
            "metricas": {"accuracy": acc_val, "mae": mae_val, "wmape_pct": wmape_val, "arboles_optimos": modelo.best_iteration},
            "grafica": {"fechas": fechas_pred, "reales": valores_reales, "predichos": valores_pred}
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        del modelo
        gc.collect()