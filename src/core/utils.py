from datetime import datetime, timedelta

import pandas as pd


def filtrar_dataframe_fechas(df, tipo_fecha, start_rango, end_rango, dia_unico):
    hoy = datetime.today().date()
    if tipo_fecha == "ayer":
        start = end = pd.to_datetime(hoy - timedelta(days=1))
    elif tipo_fecha == "7d_rel":
        start, end = pd.to_datetime(hoy - timedelta(days=7)), pd.to_datetime(
            hoy - timedelta(days=1)
        )
    elif tipo_fecha == "28d_rel":
        start, end = pd.to_datetime(hoy - timedelta(days=28)), pd.to_datetime(
            hoy - timedelta(days=1)
        )
    elif tipo_fecha == "dia" and dia_unico:
        start = end = pd.to_datetime(dia_unico)
    elif tipo_fecha == "rango" and start_rango and end_rango:
        start, end = pd.to_datetime(start_rango), pd.to_datetime(end_rango)
    else:
        return None, "Rango temporal inválido."

    df_filt = df[
        (df["fecha"] >= start)
        & (df["fecha"] <= end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
    ].copy()
    if df_filt.empty:
        return None, "No hay datos en las fechas seleccionadas."
    return df_filt, start, end
