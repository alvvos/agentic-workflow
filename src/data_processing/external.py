import pandas as pd
from src.data_processing.data_radar import obtener_clima_espana, festivos_espana_dict

def codificar_clima_binario(clima_str):
    clima = str(clima_str).lower()
    if 'lluvia' in clima or 'tormenta' in clima or 'chubasco' in clima:
        return 1
    return 0

def integrar_variables_externas(df):
    df_extendido = df.copy()
    df_extendido['fecha'] = pd.to_datetime(df_extendido['fecha'])

    climas_texto = []
    festivos_texto = []
    lluvia_binaria = []
    es_festivo_binario = []

    for f in df_extendido['fecha']:
        fecha_dt = f.date()
        
        _, _, clima = obtener_clima_espana(fecha_dt)
        festivo = festivos_espana_dict.get(fecha_dt, "Laborable")

        climas_texto.append(clima)
        festivos_texto.append(festivo)
        lluvia_binaria.append(codificar_clima_binario(clima))
        es_festivo_binario.append(1 if festivo != "Laborable" else 0)

    df_extendido['clima_texto'] = climas_texto
    df_extendido['festividad_texto'] = festivos_texto
    df_extendido['lluvia_binaria'] = lluvia_binaria
    df_extendido['es_festivo'] = es_festivo_binario

    return df_extendido