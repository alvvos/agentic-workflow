"""
Callbacks de los modales del panel Estado (tab-ejecutivo).
Pattern-matching: un callback gestiona todos los modales de todas las ubicaciones.
"""
from dash import Input, Output, State, MATCH, callback, no_update


@callback(
    Output({"type": "pm-modal", "id": MATCH}, "is_open"),
    [Input({"type": "pm-modal-open",  "id": MATCH}, "n_clicks"),
     Input({"type": "pm-modal-close", "id": MATCH}, "n_clicks")],
    State({"type": "pm-modal", "id": MATCH}, "is_open"),
    prevent_initial_call=True,
)
def toggle_pm_modal(n_open, n_close, is_open):
    from dash import ctx
    if not ctx.triggered:
        return no_update
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        return no_update
    if tid.get("type") == "pm-modal-open" and n_open:
        return True
    if tid.get("type") == "pm-modal-close" and n_close:
        return False
    return no_update
