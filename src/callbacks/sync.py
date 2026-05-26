import os
import pandas as pd
from datetime import datetime, timedelta
import dash
from dash import Output, Input, State, html
from src.core.config import app
from src.data_ingestion.sincronizador import actualizar_datos_csv


def _acquire_sync_lock(lock_file, max_age=600):
    """Intenta adquirir el lock de sincronización. Devuelve True si se adquiere."""
    if os.path.exists(lock_file):
        age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(lock_file))).total_seconds()
        if age < max_age:
            return False
        os.remove(lock_file)
    open(lock_file, 'w').close()
    return True


def _release_sync_lock(lock_file):
    if os.path.exists(lock_file):
        os.remove(lock_file)


@app.callback(
    Output("btn-sync", "children"),
    Output("btn-sync", "color"),
    Output("btn-sync", "outline"),
    Input("session-id", "data"),
    Input("data-version", "data"),
    Input("interval-staleness", "n_intervals"),
    Input("drop-locs", "value"),
)
def actualizar_alerta_sync(session_id, _data_v, _tick, locs):
    _normal = ([html.I(className="fas fa-sync-alt me-2"), "Sincronizar"], "primary", True)

    if not session_id:
        return _normal

    archivo = os.path.join('src', 'data', f'dataset_{session_id}.csv')
    if not os.path.exists(archivo):
        return (
            [html.I(className="fas fa-exclamation-circle me-2"), "Sin datos — sincronizar"],
            "danger", False,
        )
    try:
        df_tmp = pd.read_csv(archivo, usecols=['fecha', 'location_id'])
        df_tmp['fecha'] = pd.to_datetime(df_tmp['fecha'])

        if locs:
            df_tmp = df_tmp[df_tmp['location_id'].isin(locs)]

        if df_tmp.empty:
            return _normal

        fecha_mas_atrasada = df_tmp.groupby('location_id')['fecha'].max().min().date()
        ayer = datetime.today().date() - timedelta(days=1)
        dias = (ayer - fecha_mas_atrasada).days
        if dias > 1:
            return (
                [html.I(className="fas fa-exclamation-triangle me-2"),
                 f"Sincronizar · {dias}d sin datos"],
                "warning", False,
            )
    except Exception:
        pass
    return _normal


@app.callback(
    Output("modal-sync", "is_open"), Output("sync-trigger", "data"),
    Input("btn-sync", "n_clicks"), prevent_initial_call=True
)
def abrir_modal_carga(n_clicks):
    return True, n_clicks


@app.callback(
    Output("modal-sync", "is_open", allow_duplicate=True), Output("toast-notificacion", "is_open", allow_duplicate=True),
    Output("toast-notificacion", "children", allow_duplicate=True), Output("toast-notificacion", "icon", allow_duplicate=True), Output("toast-notificacion", "header", allow_duplicate=True),
    Output("data-version", "data"),
    Input("sync-trigger", "data"), State("drop-locs", "value"), State("session-id", "data"), prevent_initial_call=True
)
def ejecutar_sincronizacion(trigger, locs, session_id):
    if not trigger:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
    ruta_data = os.path.join('src', 'data')
    archivo_usuario = os.path.join(ruta_data, f'dataset_{session_id}.csv')
    lock_file = os.path.join(ruta_data, f'dataset_{session_id}.lock')
    if not _acquire_sync_lock(lock_file):
        return False, True, "Sincronización ya en progreso, espera un momento.", "warning", "Sincronización en curso", dash.no_update
    try:
        actualizar_datos_csv(locs if locs else [], archivo_usuario)
        return False, True, "Datos sincronizados correctamente.", "success", "Sincronización finalizada", datetime.now().timestamp()
    except Exception as e:
        return False, True, f"Error al descargar datos: {str(e)}", "danger", "Error de sincronización", dash.no_update
    finally:
        _release_sync_lock(lock_file)


@app.callback(
    Output("toast-notificacion", "is_open", allow_duplicate=True), Output("toast-notificacion", "children", allow_duplicate=True),
    Output("toast-notificacion", "icon", allow_duplicate=True), Output("toast-notificacion", "header", allow_duplicate=True),
    Input("btn-flush", "n_clicks"), State("session-id", "data"), prevent_initial_call=True
)
def limpiar_memoria(n, session_id):
    archivo_usuario = os.path.join('src', 'data', f'dataset_{session_id}.csv')
    try:
        if os.path.exists(archivo_usuario):
            os.remove(archivo_usuario)
        return True, "Memoria limpiada con éxito.", "success", "Flush data"
    except Exception as e:
        return True, f"Error al limpiar memoria: {str(e)}", "danger", "Error"
