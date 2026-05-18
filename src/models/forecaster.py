import pandas as pd
import numpy as np
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from datetime import timedelta
from src.data_processing.external import integrar_variables_externas

def entrenar_modelo_volumen(df, variable_objetivo='total_visits'):
    df_sorted = df.sort_values('fecha').reset_index(drop=True)
    df_numerico = df_sorted.select_dtypes(include=[np.number, bool]).copy()
    
    columnas_excluidas = ['total_visits', 'unique_visitors', 'new_visitors', 'dwell_time']
    features = [col for col in df_numerico.columns if col not in columnas_excluidas]
    
    split_index = int(len(df_sorted) * 0.8)
    
    train_df = df_numerico.iloc[:split_index]
    test_df = df_numerico.iloc[split_index:]
    
    print("-" * 30)
    print("Iniciando entrenamiento ml")
    print(f"Total registros: {len(df_sorted)}")
    print(f"Entrenamiento (80%): {len(train_df)} filas")
    print(f"Test (20%): {len(test_df)} filas")
    print(f"Rango entrenamiento: {df_sorted['fecha'].iloc[0].date()} a {df_sorted['fecha'].iloc[split_index-1].date()}")
    print(f"Rango evaluación: {df_sorted['fecha'].iloc[split_index].date()} a {df_sorted['fecha'].iloc[-1].date()}")
    print(f"Variables utilizadas: {features}")
    print("-" * 30)
    
    X_train = train_df[features]
    y_train = train_df[variable_objetivo] if variable_objetivo in train_df.columns else df_sorted.iloc[:split_index][variable_objetivo]
    
    X_test = test_df[features]
    y_test = test_df[variable_objetivo] if variable_objetivo in test_df.columns else df_sorted.iloc[split_index:][variable_objetivo]
    
    modelo = XGBRegressor(n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42)
    modelo.fit(X_train, y_train)
    
    y_pred_test = modelo.predict(X_test)
    y_pred_test = np.where(y_pred_test < 0, 0, y_pred_test)
    
    metricas = evaluar_rendimiento_modelo(y_test.values, y_pred_test)
    
    return modelo, features, metricas

def evaluar_rendimiento_modelo(y_real, y_pred):
    mae = mean_absolute_error(y_real, y_pred)
    rmse = np.sqrt(mean_squared_error(y_real, y_pred))
    
    suma_real = np.sum(y_real)
    if suma_real == 0:
        wmape = 0.0
    else:
        wmape = (np.sum(np.abs(y_real - y_pred)) / suma_real) * 100
    
    metricas = {
        'error_absoluto_medio': round(mae, 2),
        'error_cuadratico_raiz': round(rmse, 2),
        'error_porcentual_medio': round(wmape, 2)
    }
    return metricas

def calcular_anomalias_predictivas(df, modelo, features, variable_objetivo='total_visits'):
    df_resultados = df.copy()
    X = df_resultados[features]
    
    df_resultados['prediccion'] = modelo.predict(X).round(0)
    df_resultados['prediccion'] = np.where(df_resultados['prediccion'] < 0, 0, df_resultados['prediccion'])
    
    df_resultados['residuo'] = df_resultados[variable_objetivo] - df_resultados['prediccion']
    
    prediccion_segura = np.where(df_resultados['prediccion'] == 0, 1, df_resultados['prediccion'])
    df_resultados['porcentaje_desviacion'] = (df_resultados['residuo'] / prediccion_segura) * 100
    
    df_resultados['es_anomalia'] = (abs(df_resultados['porcentaje_desviacion']) > 20).astype(int)
    
    return df_resultados

def predecir_manana(df_ml, modelo, features):
    ultima_fecha = pd.to_datetime(df_ml['fecha'].max())
    manana = ultima_fecha + timedelta(days=1)

    # Calcular clima y festivos para mañana una sola vez por ubicación
    ubicaciones = df_ml['Ubicación'].unique().tolist()
    df_ext_base = pd.DataFrame([{'fecha': manana, 'Ubicación': ubi} for ubi in ubicaciones])
    df_ext_base = integrar_variables_externas(df_ext_base)
    cols_externas = [c for c in df_ext_base.columns if c not in ('fecha', 'Ubicación')]
    ext_lookup = df_ext_base.set_index('Ubicación')[cols_externas].to_dict('index')

    proyecciones = []

    for (loc, zona), grupo in df_ml.groupby(['Ubicación', 'Zona']):
        fila_futura = pd.DataFrame([{
            'fecha': manana,
            'Ubicación': loc,
            'Zona': zona,
            'dia_semana': manana.dayofweek,
            'es_fin_semana': 1 if manana.dayofweek in [5, 6] else 0,
            'mes': manana.month,
            **ext_lookup.get(loc, {})
        }])
        
        grupo_sorted = grupo.sort_values('fecha')
        
        # Construir retardos de la variable objetivo de forma segura
        fila_futura['total_visits_lag_1d'] = grupo_sorted['total_visits'].iloc[-1] if not grupo_sorted.empty else 0
        
        lag_7 = grupo_sorted[grupo_sorted['fecha'] == (manana - timedelta(days=7))]
        fila_futura['total_visits_lag_7d'] = lag_7['total_visits'].values[0] if not lag_7.empty else grupo_sorted['total_visits'].mean()
        
        lag_14 = grupo_sorted[grupo_sorted['fecha'] == (manana - timedelta(days=14))]
        fila_futura['total_visits_lag_14d'] = lag_14['total_visits'].values[0] if not lag_14.empty else grupo_sorted['total_visits'].mean()
        
        lag_28 = grupo_sorted[grupo_sorted['fecha'] == (manana - timedelta(days=28))]
        fila_futura['total_visits_lag_28d'] = lag_28['total_visits'].values[0] if not lag_28.empty else grupo_sorted['total_visits'].mean()
        
        # Media móvil 7 días
        fila_futura['total_visits_media_7d'] = grupo_sorted['total_visits'].rolling(7, min_periods=1).mean().iloc[-1] if len(grupo_sorted) > 0 else 0
        
        # --- BUCLE DE HERENCIA DINÁMICA (SOLUCIÓN AL KEYERROR) ---
        # Si el modelo exige una columna que no está en la fila sintética (como KPIs o unique_visitors),
        # heredamos el último valor conocido de la tienda para mantener la estabilidad del vector.
        for col in features:
            if col not in fila_futura.columns:
                if col in grupo_sorted.columns and not grupo_sorted.empty:
                    fila_futura[col] = grupo_sorted[col].iloc[-1]
                else:
                    fila_futura[col] = 0
        # ---------------------------------------------------------
        
        # Extraemos solo las features matemáticas en el orden exacto y predecimos
        X_futuro = fila_futura[features]
        fila_futura['prediccion'] = modelo.predict(X_futuro).round(0)
        fila_futura['prediccion'] = np.where(fila_futura['prediccion'] < 0, 0, fila_futura['prediccion'])
        
        proyecciones.append(fila_futura)
    
    if not proyecciones:
        return None
        
    return pd.concat(proyecciones, ignore_index=True)