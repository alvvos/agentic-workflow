import pandas as pd
import holidays
from src.data_processing.data_radar import obtener_info_ubicacion, obtener_clima_historico

def integrar_variables_externas(df):
    df_extendido = df.copy()
    df_extendido['fecha'] = pd.to_datetime(df_extendido['fecha'])
    df_extendido['fecha_dt'] = df_extendido['fecha'].dt.date
    df_extendido['fecha_str'] = df_extendido['fecha_dt'].astype(str)

    dfs_procesados = []

    for ubi in df_extendido['Ubicación'].unique():
        df_ubi = df_extendido[df_extendido['Ubicación'] == ubi].copy()
        lat, lon, region_code = obtener_info_ubicacion(ubi)
        
        años_presentes = list(df_ubi['fecha'].dt.year.unique())
        try:
            festivos_locales = holidays.Spain(subdiv=region_code, years=años_presentes)
        except:
            festivos_locales = holidays.Spain(years=años_presentes)

        fecha_min_str = df_ubi['fecha_str'].min()
        fecha_max_str = df_ubi['fecha_str'].max()
        clima_datos = obtener_clima_historico(lat, lon, fecha_min_str, fecha_max_str)

        df_ubi['festividad_texto'] = df_ubi['fecha_dt'].apply(lambda x: festivos_locales.get(x, "Laborable"))
        df_ubi['es_festivo'] = df_ubi['fecha_dt'].apply(lambda x: 1 if x in festivos_locales else 0)

        df_ubi['tmax'] = df_ubi['fecha_str'].apply(lambda x: clima_datos.get(x, {}).get('tmax') if clima_datos.get(x, {}).get('tmax') is not None else 22.0)
        df_ubi['tmin'] = df_ubi['fecha_str'].apply(lambda x: clima_datos.get(x, {}).get('tmin') if clima_datos.get(x, {}).get('tmin') is not None else 15.0)
        df_ubi['precipitacion'] = df_ubi['fecha_str'].apply(lambda x: clima_datos.get(x, {}).get('precip') if clima_datos.get(x, {}).get('precip') is not None else 0.0)

        df_ubi['lluvia_binaria'] = (df_ubi['precipitacion'] > 0).astype(int)

        def categorizar_clima(row):
            if row['precipitacion'] > 1.0:
                return f"Lluvia ({row['precipitacion']}mm)"
            elif row['tmax'] >= 25:
                return "Soleado/Calor"
            elif row['tmax'] < 12:
                return "Frío"
            return "Poco nuboso"

        df_ubi['clima_texto'] = df_ubi.apply(categorizar_clima, axis=1)
        dfs_procesados.append(df_ubi)

    if dfs_procesados:
        df_final = pd.concat(dfs_procesados, ignore_index=True)
        df_final.drop(columns=['fecha_dt', 'fecha_str'], inplace=True)
        return df_final

    return df_extendido