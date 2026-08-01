from datetime import datetime, timedelta

import dash
import pandas as pd
from dash import Input, Output, State, dcc

from src.core.config import app
from src.core.data_master import mapa_tiendas, mapa_zonas
from src.db.queries import get_df_visitas


@app.callback(
    Output("download-auditoria", "data"),
    Input("btn-dl-auditoria", "n_clicks"),
    State("drop-locs", "value"),
    State("tipo-fecha", "value"),
    State("date-rango", "start_date"),
    State("date-rango", "end_date"),
    State("date-dia", "date"),
    State("radar-drop-zonas", "value"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def descargar_auditoria_excel(n, locs, t_f, sd, ed, dia, zones_bi, session_id):
    if not n or not locs:
        return dash.no_update
    df = get_df_visitas(locs)
    if df.empty:
        return dash.no_update
    df["Ubicación"] = df["location_id"].map(mapa_tiendas).fillna("Desconocida")
    df["Zona"] = (
        df["zona_id"].map(mapa_zonas).fillna("SinNombre")
        if "zona_id" in df.columns
        else "SinNombre"
    )
    hoy = datetime.today().date()
    start = end = pd.to_datetime(hoy - timedelta(days=1))
    if t_f == "7d_rel":
        start, end = pd.to_datetime(hoy - timedelta(days=7)), pd.to_datetime(
            hoy - timedelta(days=1)
        )
    elif t_f == "28d_rel":
        start, end = pd.to_datetime(hoy - timedelta(days=28)), pd.to_datetime(
            hoy - timedelta(days=1)
        )
    elif t_f == "dia" and dia:
        start = end = pd.to_datetime(dia)
    elif t_f == "rango" and sd and ed:
        start, end = pd.to_datetime(sd), pd.to_datetime(ed)
    df_actual = df[
        (df["fecha"] >= start)
        & (df["fecha"] <= end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
    ].copy()
    if zones_bi:
        df_actual = df_actual[df_actual["Zona"].isin(zones_bi)]
    if df_actual.empty:
        return dash.no_update
    cols = [
        c
        for c in [
            "fecha",
            "Ubicación",
            "Zona",
            "total_visits",
            "unique_visitors",
            "new_visitors",
            "dwell_time",
        ]
        if c in df_actual.columns
    ]
    df_exp = df_actual[cols].copy()
    df_exp["fecha"] = df_exp["fecha"].dt.strftime("%Y-%m-%d")
    if "dwell_time" in df_exp.columns:
        df_exp["dwell_time"] = (df_exp["dwell_time"] / 60).round(1)
        df_exp.rename(columns={"dwell_time": "estancia_min"}, inplace=True)
    df_exp.sort_values(["fecha", "Ubicación", "Zona"], inplace=True)
    return dcc.send_string(
        df_exp.to_csv(index=False),
        f"auditoria_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv",
    )
