import pandas as pd
import numpy as np
from src.data_processing.external import integrar_variables_externas

def rellenar_huecos_temporales(df):
    df['fecha'] = pd.to_datetime(df['fecha'])
    df_completo = pd.DataFrame()
    
    for (loc, zona), grupo in df.groupby(['Ubicación', 'Zona']):
        rango_fechas = pd.date_range(start=grupo['fecha'].min(), end=grupo['fecha'].max(), freq='D')
        grupo_reindexado = grupo.set_index('fecha').reindex(rango_fechas)
        
        grupo_reindexado['Ubicación'] = loc
        grupo_reindexado['Zona'] = zona
        
        for col in ['total_visits', 'unique_visitors', 'new_visitors']:
            if col in grupo_reindexado.columns:
                grupo_reindexado[col] = grupo_reindexado[col].interpolate(method='linear').fillna(0)
        
        if 'dwell_time' in grupo_reindexado.columns:
            grupo_reindexado['dwell_time'] = grupo_reindexado['dwell_time'].fillna(grupo_reindexado['dwell_time'].mean())
            
        grupo_reindexado = grupo_reindexado.reset_index().rename(columns={'index': 'fecha'})
        df_completo = pd.concat([df_completo, grupo_reindexado], ignore_index=True)
        
    return df_completo

def tratar_outliers(df, columnas=['total_visits', 'unique_visitors'], ventana=7, umbral_z=3):
    df_limpio = df.copy()
    
    for col in columnas:
        if col not in df_limpio.columns:
            continue
            
        for (loc, zona), indices in df_limpio.groupby(['Ubicación', 'Zona']).groups.items():
            serie = df_limpio.loc[indices, col]
            media_movil = serie.rolling(window=ventana, min_periods=1, center=True).mean()
            std_movil = serie.rolling(window=ventana, min_periods=1, center=True).std().fillna(0)
            
            limite_superior = media_movil + (umbral_z * std_movil)
            limite_inferior = media_movil - (umbral_z * std_movil)
            
            es_outlier_sup = serie > limite_superior
            es_outlier_inf = serie < limite_inferior
            
            df_limpio.loc[indices[es_outlier_sup], col] = limite_superior[es_outlier_sup]
            df_limpio.loc[indices[es_outlier_inf], col] = limite_inferior[es_outlier_inf]
            
    return df_limpio

def enriquecer_dataset_ml(df):
    df_procesado = rellenar_huecos_temporales(df)
    
    df_procesado = tratar_outliers(df_procesado)
    
    df_procesado = integrar_variables_externas(df_procesado)
    
    df_procesado['dia_semana'] = df_procesado['fecha'].dt.dayofweek
    df_procesado['es_fin_semana'] = df_procesado['dia_semana'].isin([5, 6]).astype(int)
    df_procesado['mes'] = df_procesado['fecha'].dt.month
    
    for col in ['total_visits', 'unique_visitors']:
        if col in df_procesado.columns:
            df_procesado[f'{col}_media_7d'] = df_procesado.groupby(['Ubicación', 'Zona'])[col].transform(lambda x: x.rolling(7, min_periods=1).mean())
            df_procesado[f'{col}_lag_1d'] = df_procesado.groupby(['Ubicación', 'Zona'])[col].shift(1)
            df_procesado[f'{col}_lag_7d'] = df_procesado.groupby(['Ubicación', 'Zona'])[col].shift(7)
            df_procesado[f'{col}_lag_14d'] = df_procesado.groupby(['Ubicación', 'Zona'])[col].shift(14)
            df_procesado[f'{col}_lag_28d'] = df_procesado.groupby(['Ubicación', 'Zona'])[col].shift(28)
            
    df_procesado = df_procesado.dropna().reset_index(drop=True)
            
    return df_procesado