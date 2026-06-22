from datetime import datetime

import dash_bootstrap_components as dbc
import requests
from dash import Input, Output, html

from src.core.config import app
from src.layout.tabs.tab_pipeline import _EDGES, _NODES, NODE_INFO, _default_detail

_PREFECT_API = "http://127.0.0.1:4200/api"

# Mapeo flow name → node id
_FLOW_TO_NODE = {
    "onboarding-ubicacion": "quality-gate",
    "onboarding-lote": "trigger",
}

_STATE_CLASS = {
    "COMPLETED": "estado-ok",
    "FAILED": "estado-fail",
    "CRASHED": "estado-fail",
    "RUNNING": "estado-running",
    "PENDING": "estado-running",
}


def _get_latest_runs() -> dict[str, dict]:
    """Consulta Prefect API y devuelve {flow_name: {state, end_time}}."""
    try:
        resp = requests.post(
            f"{_PREFECT_API}/flow_runs/filter",
            json={
                "flows": {"name": {"any_": list(_FLOW_TO_NODE.keys())}},
                "sort": "START_TIME_DESC",
                "limit": 20,
            },
            timeout=3,
        )
        runs: dict[str, dict] = {}
        for run in resp.json():
            # El nombre del flow se obtiene del objeto flow asociado; los runs
            # devuelven flow_id, así que filtramos por los que ya conocemos.
            state = run.get("state_type") or run.get("state", {}).get("type", "")
            ts = run.get("end_time") or run.get("start_time") or ""
            flow_key = None
            for fk in _FLOW_TO_NODE:
                if fk in (run.get("flow_name") or ""):
                    flow_key = fk
                    break
            if flow_key and flow_key not in runs:
                runs[flow_key] = {"state": state, "ts": ts}
        return runs
    except Exception:
        return {}


def _fmt_ts(ts: str) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return ts[:16]


@app.callback(
    Output("cytoscape-pipeline", "elements"),
    Input("interval-pipeline", "n_intervals"),
    Input("tabs-panel", "value"),
)
def actualizar_estados_pipeline(_, tab):
    if tab != "tab-pipeline":
        from dash import no_update

        return no_update

    runs = _get_latest_runs()

    # Reconstruir elementos con clases de estado actualizadas
    nodes = []
    for node in _NODES:
        n = {**node, "data": {**node["data"]}}
        base_classes = node.get("classes", "")
        node_id = n["data"]["id"]

        # Buscar si hay un run asociado a este nodo
        estado_class = ""
        for flow_key, node_key in _FLOW_TO_NODE.items():
            if node_key == node_id and flow_key in runs:
                estado_class = _STATE_CLASS.get(runs[flow_key]["state"], "")
                n["data"]["last_run_ts"] = runs[flow_key]["ts"]
                n["data"]["last_run_state"] = runs[flow_key]["state"]
                break

        n["classes"] = f"{base_classes} {estado_class}".strip()
        nodes.append(n)

    return nodes + _EDGES


@app.callback(
    Output("pipeline-node-detail", "children"),
    Input("cytoscape-pipeline", "tapNodeData"),
)
def mostrar_detalle_nodo(node_data):
    if not node_data:
        return _default_detail()

    node_id = node_data.get("id", "")
    info = NODE_INFO.get(node_id)
    if not info:
        return _default_detail()

    estado = node_data.get("last_run_state")
    ts = _fmt_ts(node_data.get("last_run_ts", ""))

    if info["pendiente"]:
        badge = dbc.Badge("Pendiente", color="secondary", className="mb-2")
    elif estado == "COMPLETED":
        badge = dbc.Badge("OK", color="success", className="mb-2")
    elif estado in ("FAILED", "CRASHED"):
        badge = dbc.Badge("Fallido", color="danger", className="mb-2")
    elif estado in ("RUNNING", "PENDING"):
        badge = dbc.Badge("Ejecutando", color="warning", className="mb-2")
    else:
        badge = dbc.Badge("Implementado", color="primary", className="mb-2")

    return dbc.Card(
        [
            dbc.CardBody(
                [
                    html.H6(info["titulo"], className="fw-bold text-dark mb-1"),
                    badge,
                    html.P(info["desc"], className="small text-muted mb-2"),
                    html.Hr(className="my-2"),
                    html.Div(
                        [
                            html.I(className="fas fa-file-code me-1 text-muted"),
                            html.Span(info["archivo"], className="small text-muted font-monospace"),
                        ],
                        className="mb-2",
                    ),
                    *(
                        []
                        if not estado
                        else [
                            html.Div(
                                [
                                    html.I(className="fas fa-clock me-1 text-muted"),
                                    html.Span(f"Último run: {ts}", className="small text-muted"),
                                ]
                            )
                        ]
                    ),
                ]
            )
        ],
        className="border-0 shadow-sm rounded-4 mt-3",
    )
