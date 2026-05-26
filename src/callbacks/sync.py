import os
import threading
import pandas as pd
from datetime import datetime, timedelta
import dash
from dash import Output, Input, State, html
from src.core.config import app
from src.data_ingestion.sincronizador import actualizar_datos_csv

# ── Estado de sincronizaciones en curso ─────────────────────────────────────
# session_id → {"cancel": Event, "status": str, "progress": str, "error": str|None}
_sync_jobs: dict = {}


def _acquire_sync_lock(lock_file, max_age=600):
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


def _run_sync(session_id, locs, archivo_usuario, lock_file):
    job = _sync_jobs[session_id]

    def progress_cb(current, total):
        job["progress"] = f"Ubicación {current} de {total}…"

    try:
        actualizar_datos_csv(
            locs if locs else [],
            archivo_usuario,
            stop_event=job["cancel"],
            progress_cb=progress_cb,
        )
        job["status"] = "cancelled" if job["cancel"].is_set() else "done"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
    finally:
        _release_sync_lock(lock_file)


# ── Alerta de datos obsoletos ────────────────────────────────────────────────

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
        return ([html.I(className="fas fa-exclamation-circle me-2"), "Sin datos — sincronizar"],
                "danger", False)
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
            return ([html.I(className="fas fa-exclamation-triangle me-2"),
                     f"Sincronizar · {dias}d sin datos"], "warning", False)
    except Exception:
        pass
    return _normal


# ── Abrir modal ──────────────────────────────────────────────────────────────

@app.callback(
    Output("modal-sync", "is_open"),
    Output("sync-trigger", "data"),
    Input("btn-sync", "n_clicks"),
    prevent_initial_call=True,
)
def abrir_modal_carga(n_clicks):
    return True, n_clicks


# ── Lanzar sync en hilo background ──────────────────────────────────────────

@app.callback(
    Output("interval-sync-poll", "disabled"),
    Input("sync-trigger", "data"),
    State("drop-locs", "value"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def ejecutar_sincronizacion(trigger, locs, session_id):
    if not trigger:
        return True
    ruta_data = os.path.join('src', 'data')
    archivo_usuario = os.path.join(ruta_data, f'dataset_{session_id}.csv')
    lock_file = os.path.join(ruta_data, f'dataset_{session_id}.lock')

    if not _acquire_sync_lock(lock_file):
        return False  # ya hay sync en curso, sigue el polling

    cancel_event = threading.Event()
    _sync_jobs[session_id] = {
        "cancel": cancel_event,
        "status": "running",
        "progress": "Iniciando…",
        "error": None,
    }
    threading.Thread(
        target=_run_sync,
        args=(session_id, locs, archivo_usuario, lock_file),
        daemon=True,
    ).start()
    return False  # activa el interval de polling


# ── Polling de progreso ──────────────────────────────────────────────────────

@app.callback(
    Output("modal-sync", "is_open", allow_duplicate=True),
    Output("toast-notificacion", "is_open", allow_duplicate=True),
    Output("toast-notificacion", "children", allow_duplicate=True),
    Output("toast-notificacion", "icon", allow_duplicate=True),
    Output("toast-notificacion", "header", allow_duplicate=True),
    Output("data-version", "data"),
    Output("interval-sync-poll", "disabled", allow_duplicate=True),
    Output("sync-progress-text", "children"),
    Input("interval-sync-poll", "n_intervals"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def poll_sync_progress(_, session_id):
    _no = dash.no_update
    job = _sync_jobs.get(session_id)
    if not job:
        return _no, _no, _no, _no, _no, _no, True, ""

    status = job["status"]
    progress = job.get("progress", "")

    if status == "running":
        return True, _no, _no, _no, _no, _no, False, progress

    # Terminado — limpiamos y cerramos
    _sync_jobs.pop(session_id, None)

    if status == "done":
        return (False, True, "Datos sincronizados correctamente.",
                "success", "Sincronización finalizada",
                datetime.now().timestamp(), True, "")
    if status == "cancelled":
        return (False, True, "Sincronización cancelada.",
                "warning", "Cancelado", _no, True, "")
    # error
    return (False, True, f"Error: {job.get('error', 'desconocido')}",
            "danger", "Error de sincronización", _no, True, "")


# ── Cancelar sincronización ──────────────────────────────────────────────────

@app.callback(
    Output("sync-progress-text", "children", allow_duplicate=True),
    Input("btn-cancel-sync", "n_clicks"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def cancelar_sincronizacion(_, session_id):
    job = _sync_jobs.get(session_id)
    if job and job["status"] == "running":
        job["cancel"].set()
        job["status"] = "cancelling"
        return "Cancelando… finalizando ubicación actual."
    return dash.no_update


# ── Flush de datos ───────────────────────────────────────────────────────────

@app.callback(
    Output("toast-notificacion", "is_open", allow_duplicate=True),
    Output("toast-notificacion", "children", allow_duplicate=True),
    Output("toast-notificacion", "icon", allow_duplicate=True),
    Output("toast-notificacion", "header", allow_duplicate=True),
    Input("btn-flush", "n_clicks"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def limpiar_memoria(n, session_id):
    archivo_usuario = os.path.join('src', 'data', f'dataset_{session_id}.csv')
    try:
        if os.path.exists(archivo_usuario):
            os.remove(archivo_usuario)
        return True, "Memoria limpiada con éxito.", "success", "Flush data"
    except Exception as e:
        return True, f"Error al limpiar memoria: {str(e)}", "danger", "Error"
