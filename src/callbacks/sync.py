import os
import json
import threading
import pandas as pd
from datetime import datetime, timedelta
import dash
from dash import Output, Input, State, html
import dash_bootstrap_components as dbc
from src.core.config import app
from src.data_ingestion.sincronizador import actualizar_datos_csv

# ── Hilos activos en este worker (cancel Event local) ───────────────────────
_sync_threads: dict = {}

_RUTA_DATA = os.path.join('src', 'data')


def _status_path(session_id):
    return os.path.join(_RUTA_DATA, f'dataset_{session_id}.status.json')


def _cancel_path(session_id):
    return os.path.join(_RUTA_DATA, f'dataset_{session_id}.cancel')


def _write_status(session_id, **kwargs):
    try:
        with open(_status_path(session_id), 'w') as f:
            json.dump(kwargs, f)
    except Exception:
        pass


def _read_status(session_id):
    try:
        with open(_status_path(session_id)) as f:
            return json.load(f)
    except Exception:
        return None


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
    cancel_event = _sync_threads.get(session_id)
    cancel_file = _cancel_path(session_id)

    def progress_cb(current, total):
        _write_status(session_id, status="running", current=current, total=total)
        # Señal de cancelación cross-worker: fichero en disco
        if cancel_event and (os.path.exists(cancel_file) or cancel_event.is_set()):
            if cancel_event:
                cancel_event.set()

    try:
        actualizar_datos_csv(
            locs if locs else [],
            archivo_usuario,
            stop_event=cancel_event,
            progress_cb=progress_cb,
        )
        final = "cancelled" if (cancel_event and cancel_event.is_set()) else "done"
        _write_status(session_id, status=final, current=0, total=0)
    except Exception as e:
        _write_status(session_id, status="error", current=0, total=0, error=str(e))
    finally:
        _release_sync_lock(lock_file)
        _sync_threads.pop(session_id, None)
        try:
            os.remove(cancel_file)
        except FileNotFoundError:
            pass


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
                     f"Sincronizar · {dias}d sin datos"], "primary", False)
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
    Output("sync-progress-bar", "value"),
    Input("sync-trigger", "data"),
    State("drop-locs", "value"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def ejecutar_sincronizacion(trigger, locs, session_id):
    if not trigger:
        return True, 0

    lock_file = os.path.join(_RUTA_DATA, f'dataset_{session_id}.lock')
    archivo_usuario = os.path.join(_RUTA_DATA, f'dataset_{session_id}.csv')

    if not _acquire_sync_lock(lock_file):
        return False, dash.no_update  # ya hay sync en curso, seguir polling

    cancel_event = threading.Event()
    _sync_threads[session_id] = cancel_event
    _write_status(session_id, status="running", current=0, total=0)

    threading.Thread(
        target=_run_sync,
        args=(session_id, locs, archivo_usuario, lock_file),
        daemon=True,
    ).start()
    return False, 0  # activa el interval de polling


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
    Output("sync-progress-bar", "value", allow_duplicate=True),
    Input("interval-sync-poll", "n_intervals"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def poll_sync_progress(_, session_id):
    _no = dash.no_update
    data = _read_status(session_id)

    if data is None:
        return _no, _no, _no, _no, _no, _no, True, "", 0

    status = data.get("status", "running")
    current = data.get("current", 0)
    total = data.get("total", 0)
    pct = int(current / total * 100) if total > 0 else 0
    progress_text = f"Ubicación {current} de {total}…" if total > 0 else "Iniciando…"

    if status == "running":
        return True, _no, _no, _no, _no, _no, False, progress_text, pct

    # Terminado — borrar fichero de estado
    try:
        os.remove(_status_path(session_id))
    except FileNotFoundError:
        pass

    if status == "done":
        return (False, True, "Datos sincronizados correctamente.",
                "success", "Sincronización finalizada",
                datetime.now().timestamp(), True, "", 100)
    if status == "cancelled":
        return (False, True, "Sincronización cancelada.",
                "warning", "Cancelado", _no, True, "", 0)
    return (False, True, f"Error: {data.get('error', 'desconocido')}",
            "danger", "Error de sincronización", _no, True, "", 0)


# ── Cancelar sincronización ──────────────────────────────────────────────────

@app.callback(
    Output("sync-progress-text", "children", allow_duplicate=True),
    Input("btn-cancel-sync", "n_clicks"),
    State("session-id", "data"),
    prevent_initial_call=True,
)
def cancelar_sincronizacion(_, session_id):
    # Señal cross-worker: fichero en disco
    cancel_file = _cancel_path(session_id)
    open(cancel_file, 'w').close()
    # Señal in-process si el hilo está en este worker
    ev = _sync_threads.get(session_id)
    if ev:
        ev.set()
    return "Cancelando… finalizando ubicación actual."


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
