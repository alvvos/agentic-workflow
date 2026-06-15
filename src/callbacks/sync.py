import threading
from datetime import datetime, timedelta
import dash
from dash import Output, Input, State, html
from src.core.config import app
from src.data_ingestion.sincronizador import actualizar_datos

# ── Estado en memoria (single-worker gunicorn) ───────────────────────────────
_sync_threads: dict = {}   # session_id → threading.Event (cancel)
_sync_status:  dict = {}   # session_id → {status, current, total, error}
_sync_lock = threading.Lock()


def _write_status(session_id, **kwargs):
    _sync_status[session_id] = kwargs


def _read_status(session_id):
    return _sync_status.get(session_id)


def _run_sync(session_id, locs):
    cancel_event = _sync_threads.get(session_id)

    def progress_cb(current, total):
        _write_status(session_id, status="running", current=current, total=total)
        if cancel_event and cancel_event.is_set():
            pass  # sincronizador revisa stop_event en cada iteración

    try:
        actualizar_datos(
            locs if locs else None,
            stop_event=cancel_event,
            progress_cb=progress_cb,
        )
        final = "cancelled" if (cancel_event and cancel_event.is_set()) else "done"
        _write_status(session_id, status=final, current=0, total=0)
    except Exception as e:
        _write_status(session_id, status="error", current=0, total=0, error=str(e))
    finally:
        with _sync_lock:
            _sync_threads.pop(session_id, None)


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
    if not locs:
        return _normal
    try:
        from src.db.queries import get_ultima_fecha_por_location
        ultima_por_loc = get_ultima_fecha_por_location()
        if not ultima_por_loc:
            return ([html.I(className="fas fa-exclamation-circle me-2"), "Sin datos — sincronizar"],
                    "danger", False)
        fechas_locs = [ultima_por_loc[l] for l in (locs or []) if l in ultima_por_loc]
        if not fechas_locs:
            return ([html.I(className="fas fa-exclamation-circle me-2"), "Sin datos — sincronizar"],
                    "danger", False)
        fecha_mas_atrasada = min(pd.to_datetime(f).date() for f in fechas_locs)
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

    with _sync_lock:
        if session_id in _sync_threads:
            return False, dash.no_update  # ya en curso

        cancel_event = threading.Event()
        _sync_threads[session_id] = cancel_event

    _write_status(session_id, status="running", current=0, total=0)

    threading.Thread(
        target=_run_sync,
        args=(session_id, locs),
        daemon=True,
    ).start()
    return False, 0


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

    _sync_status.pop(session_id, None)

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
    ev = _sync_threads.get(session_id)
    if ev:
        ev.set()
    return "Cancelando… finalizando ubicación actual."



import pandas as pd  # noqa: E402 — needed by actualizar_alerta_sync
