import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import mean_absolute_error
import gc

def ejecutar_auditoria_predictiva(df_master, location_uuid, zone_uuid, falso_hoy, horizonte_dias):
    modelo = None
    try:
        df_tienda = df_master[(df_master['location_id'] == location_uuid) & 
                              (df_master['zone_uuid'] == zone_uuid)].copy()
        
        if df_tienda.empty:
            return {"error": "No hay datos para esta zona."}

        df_tienda = df_tienda.groupby('fecha').agg({
            'total_visits': 'sum',
            'llueve': 'max',
            'temp_max': 'max',
            'temp_min': 'min',
            'es_festivo': 'max'
        }).reset_index().sort_values('fecha').reset_index(drop=True)

        df_tienda['es_finde'] = df_tienda['fecha'].dt.dayofweek.isin([5, 6]).astype(int)
        df_tienda['dia_semana'] = df_tienda['fecha'].dt.dayofweek
        df_tienda['dia_mes'] = df_tienda['fecha'].dt.day
        df_tienda['mes'] = df_tienda['fecha'].dt.month
        df_tienda['quincena'] = (df_tienda['dia_mes'] > 15).astype(int)
        df_tienda['vispera_festivo'] = df_tienda['es_festivo'].shift(-1).fillna(0)
        
        df_tienda['mucho_calor'] = (df_tienda['temp_max'] >= 32.0).astype(int)
        df_tienda['mucho_frio'] = (df_tienda['temp_min'] <= 8.0).astype(int)
        df_tienda['clima_ideal'] = ((df_tienda['temp_max'] >= 18.0) & (df_tienda['temp_max'] <= 26.0) & (df_tienda['llueve'] == 0)).astype(int)
        df_tienda['finde_lluvioso'] = df_tienda['es_finde'] * df_tienda['llueve']

        df_tienda['lag_1d'] = df_tienda['total_visits'].shift(1)
        df_tienda['lag_7d'] = df_tienda['total_visits'].shift(7)
        df_tienda['media_7d'] = df_tienda['total_visits'].rolling(7).mean()
        df_tienda['lag_14d'] = df_tienda['total_visits'].shift(14)
        df_tienda['media_14d'] = df_tienda['total_visits'].rolling(14).mean()
        df_tienda['std_7d'] = df_tienda['total_visits'].rolling(7).std().fillna(0)
        
        df_tienda = df_tienda.dropna().reset_index(drop=True)

        fecha_corte = pd.to_datetime(falso_hoy)
        fecha_fin = fecha_corte + pd.Timedelta(days=horizonte_dias - 1)

        train = df_tienda[df_tienda['fecha'] < fecha_corte].copy()
        test = df_tienda[(df_tienda['fecha'] >= fecha_corte) & (df_tienda['fecha'] <= fecha_fin)].copy()

        if len(train) < 20 or len(test) == 0:
            return {"error": "Muestra insuficiente."}

        features = ['es_finde', 'es_festivo', 'llueve', 'dia_semana', 'dia_mes', 'mes', 
                    'lag_1d', 'lag_7d', 'media_7d', 'quincena', 'vispera_festivo', 
                    'lag_14d', 'media_14d', 'std_7d', 'finde_lluvioso', 'mucho_calor', 'mucho_frio', 'clima_ideal']
        
        X_train, y_train = train[features], train['total_visits']
        X_test, y_test = test[features], test['total_visits']

        modelo = xgb.XGBRegressor(
            n_estimators=200, 
            learning_rate=0.05, 
            max_depth=3, 
            random_state=42,
            early_stopping_rounds=20 
        )
        
        modelo.fit(X_train, y_train, eval_set=[(X_train, y_train), (X_test, y_test)], verbose=False)

        preds = np.maximum(0, np.round(modelo.predict(X_test)))
        mae = mean_absolute_error(y_test, preds)
        wmape = np.sum(np.abs(y_test - preds)) / np.sum(y_test) if np.sum(y_test) > 0 else 0

        return {
            "status": "success",
            "metricas": {"accuracy": round((1-wmape)*100, 2), "mae": round(mae, 1), "wmape_pct": round(wmape*100, 2), "arboles_optimos": modelo.best_iteration},
            "grafica": {"fechas": test['fecha'].dt.strftime('%Y-%m-%d').tolist(), "reales": y_test.tolist(), "predichos": preds.tolist()}
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        del modelo
        gc.collect()