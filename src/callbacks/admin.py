import json
from pathlib import Path

import flask
from dash import Output, Input, State, callback_context, html, no_update, ALL
import dash_bootstrap_components as dbc
from werkzeug.security import generate_password_hash

from src.core.config import app, MODO_DESARROLLO

_USERS_FILE = Path(__file__).parent.parent.parent / "users.json"
_UBIC_PATH  = Path(__file__).parent.parent / "data" / "todas_las_ubicaciones.json"

_ROLE_LABELS = {"admin": "Administrador", "user": "Usuario"}
_ROLE_COLORS = {"admin": "danger", "user": "primary"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_users() -> dict:
    if not _USERS_FILE.exists():
        return {}
    with open(_USERS_FILE) as f:
        return json.load(f)


def _save_users(users: dict) -> None:
    with open(_USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


def _normalize(entry) -> dict:
    if isinstance(entry, str):
        return {"password": entry, "role": "user"}
    return entry


def _current_user() -> str:
    if MODO_DESARROLLO:
        return "local_dev"
    return flask.session.get("user", "")


def _load_orgs() -> list:
    if not _UBIC_PATH.exists():
        return []
    with open(_UBIC_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_orgs(orgs: list) -> None:
    with open(_UBIC_PATH, "w", encoding="utf-8") as f:
        json.dump(orgs, f, ensure_ascii=False, indent=2)


# ── Render helpers ────────────────────────────────────────────────────────────

def _render_users_table(users: dict) -> html.Div:
    if not users:
        return html.Div(
            dbc.Alert([html.I(className="fas fa-info-circle me-2"), "No hay usuarios registrados."],
                      color="info", className="rounded-3 border-0 m-3"),
        )

    rows = []
    for username, raw in sorted(users.items()):
        entry = _normalize(raw)
        role  = entry.get("role", "user")
        me    = username == _current_user()
        rows.append(
            html.Tr([
                html.Td([
                    html.Span(
                        username[0].upper(),
                        className="badge rounded-circle bg-primary me-2 fw-bold",
                        style={"width": "28px", "height": "28px", "lineHeight": "20px",
                               "fontSize": "0.75rem", "display": "inline-flex",
                               "alignItems": "center", "justifyContent": "center"},
                    ),
                    html.Span(username, className="fw-bold"),
                    html.Span(" (tú)", className="text-muted small ms-1 fst-italic") if me else None,
                ], className="align-middle py-3 px-4"),
                html.Td(
                    dbc.Badge(
                        [html.I(className=f"fas {'fa-shield-alt' if role == 'admin' else 'fa-user'} me-1"),
                         _ROLE_LABELS.get(role, role)],
                        color=_ROLE_COLORS.get(role, "secondary"),
                        className="rounded-pill px-3 py-2",
                    ),
                    className="align-middle",
                ),
                html.Td(
                    dbc.ButtonGroup([
                        dbc.Button(
                            [html.I(className=f"fas {'fa-user-shield' if role == 'user' else 'fa-user'} me-1"),
                             "→ Admin" if role == "user" else "→ Usuario"],
                            id={"type": "admin-del-btn", "index": f"role:{username}"},
                            size="sm",
                            color="warning" if role == "user" else "secondary",
                            outline=True,
                            className="rounded-start-pill fw-bold",
                            disabled=me,
                        ),
                        dbc.Button(
                            html.I(className="fas fa-trash-alt"),
                            id={"type": "admin-del-btn", "index": f"user:{username}"},
                            size="sm",
                            color="danger",
                            outline=True,
                            className="rounded-end-pill",
                            disabled=me,
                        ),
                    ]),
                    className="align-middle text-end pe-4",
                ),
            ], className="border-bottom")
        )

    return dbc.Table(
        [
            html.Thead(
                html.Tr([
                    html.Th("Usuario", className="px-4 py-3 text-muted small text-uppercase fw-bold"),
                    html.Th("Rol",     className="py-3 text-muted small text-uppercase fw-bold"),
                    html.Th("Acciones", className="py-3 pe-4 text-end text-muted small text-uppercase fw-bold"),
                ]),
                className="bg-light",
            ),
            html.Tbody(rows),
        ],
        bordered=False, hover=True, responsive=True, className="mb-0 align-middle",
    )


def _loc_row(loc: dict) -> html.Tr:
    zones  = loc.get("zones", [])
    lat    = loc.get("lat") or loc.get("latitude")
    lon    = loc.get("lon") or loc.get("longitude")
    city   = loc.get("city") or loc.get("province") or ("" if not lat else f"{lat:.3f}, {lon:.3f}")
    return html.Tr([
        html.Td([
            html.I(className="fas fa-store me-2 text-primary"),
            html.Span(loc.get("name", "—"), className="fw-semibold"),
        ], className="align-middle py-3 px-4"),
        html.Td(
            html.Span(city, className="text-muted small"),
            className="align-middle",
        ),
        html.Td(
            html.Span(loc["uuid"][:8] + "…", className="font-monospace text-muted small"),
            className="align-middle d-none d-md-table-cell",
        ),
        html.Td(
            dbc.Badge(
                [html.I(className="fas fa-layer-group me-1"), f"{len(zones)} zona{'s' if len(zones) != 1 else ''}"],
                color="info", pill=True,
            ),
            className="align-middle",
        ),
        html.Td(
            dbc.Button(
                html.I(className="fas fa-trash-alt"),
                id={"type": "admin-del-btn", "index": f"loc:{loc['uuid']}"},
                size="sm", color="danger", outline=True, className="rounded-pill",
            ),
            className="align-middle text-end pe-4",
        ),
    ], className="border-bottom")


def _render_locs_tree(orgs: list) -> html.Div:
    n_locs  = sum(len(o.get("locations", [])) for o in orgs)
    n_zones = sum(len(l.get("zones", [])) for o in orgs for l in o.get("locations", []))

    # ── Resumen en strip ─────────────────────────────────────────────────────
    stats_strip = html.Div(
        dbc.Row([
            dbc.Col(_stat_pill(len(orgs), "Organizaciones", "fa-building", "text-primary"), xs=4),
            dbc.Col(_stat_pill(n_locs,    "Ubicaciones",    "fa-store",    "text-success"), xs=4),
            dbc.Col(_stat_pill(n_zones,   "Zonas",          "fa-layer-group", "text-info"), xs=4),
        ], className="g-0"),
        className="p-3 bg-light rounded-4 border-start border-primary border-4 shadow-sm mb-4",
    )

    # ── Una card por organización ─────────────────────────────────────────────
    org_cards = []
    for org in orgs:
        locs     = org.get("locations", [])
        org_uuid = org.get("uuid", org.get("name", "?"))
        n        = len(locs)

        loc_table = dbc.Table(
            [
                html.Thead(
                    html.Tr([
                        html.Th("Nombre",    className="px-4 py-2 text-muted small text-uppercase fw-bold"),
                        html.Th("Ciudad",    className="py-2 text-muted small text-uppercase fw-bold"),
                        html.Th("UUID",      className="py-2 text-muted small text-uppercase fw-bold d-none d-md-table-cell"),
                        html.Th("Zonas",     className="py-2 text-muted small text-uppercase fw-bold"),
                        html.Th("",          className="pe-4"),
                    ]),
                    className="bg-light",
                ),
                html.Tbody(
                    [_loc_row(loc) for loc in locs] if locs else [
                        html.Tr(html.Td(
                            html.Span([html.I(className="fas fa-inbox me-2"), "Sin ubicaciones"],
                                      className="text-muted fst-italic small"),
                            colSpan=5, className="text-center py-4",
                        ))
                    ]
                ),
            ],
            bordered=False, hover=bool(locs), responsive=True, className="mb-0 align-middle",
        )

        org_cards.append(
            dbc.Card([
                dbc.CardHeader(
                    dbc.Row([
                        dbc.Col([
                            html.I(className="fas fa-building me-2 text-primary"),
                            html.Span(org.get("name", "—"), className="fw-bold me-2"),
                            dbc.Badge(
                                f"{n} ubicación{'es' if n != 1 else ''}",
                                color="secondary", pill=True, className="ms-1",
                            ),
                        ], className="d-flex align-items-center"),
                        dbc.Col(
                            dbc.Button(
                                [html.I(className="fas fa-trash-alt me-1"), "Eliminar org"],
                                id={"type": "admin-del-btn", "index": f"org:{org_uuid}"},
                                size="sm", color="danger", outline=True,
                                className="rounded-pill fw-bold",
                            ),
                            className="text-end",
                        ),
                    ], className="align-items-center g-0"),
                    className="bg-white border-bottom py-2 px-4",
                ),
                dbc.CardBody(loc_table, className="p-0"),
            ], className="border-0 shadow-sm rounded-4 mb-3 overflow-hidden")
        )

    return html.Div([stats_strip, *org_cards])


def _stat_pill(value, label, icon, color_cls) -> html.Div:
    return html.Div([
        html.Div([
            html.I(className=f"fas {icon} me-2 {color_cls}"),
            html.Span(str(value), className=f"fw-bold {color_cls} me-1"),
            html.Span(label, className="text-muted small"),
        ], className="d-flex align-items-center justify-content-center"),
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@app.callback(
    Output("admin-users-table-container", "children"),
    Input("admin-crud-signal", "data"),
    Input("admin-sub-tabs", "active_tab"),
)
def refresh_users_table(_, active_tab):
    if active_tab != "admin-tab-users":
        return no_update
    return _render_users_table(_load_users())


@app.callback(
    Output("admin-locs-container", "children"),
    Input("admin-sub-tabs", "active_tab"),
    Input("admin-crud-signal", "data"),
)
def refresh_locs_tree(active_tab, _):
    if active_tab != "admin-tab-locs":
        return no_update
    orgs = _load_orgs()
    if not orgs:
        return dbc.Alert("No se encontró el árbol de ubicaciones.", color="warning",
                         className="rounded-3 border-0")
    return _render_locs_tree(orgs)


@app.callback(
    Output("admin-crud-signal", "data"),
    Output("admin-users-feedback", "children"),
    Output("admin-users-feedback", "is_open"),
    Output("admin-users-feedback", "color"),
    Output("admin-new-username", "value"),
    Output("admin-new-password", "value"),
    Input("admin-add-user-btn", "n_clicks"),
    State("admin-new-username", "value"),
    State("admin-new-password", "value"),
    State("admin-new-role", "value"),
    State("admin-crud-signal", "data"),
    prevent_initial_call=True,
)
def add_user(_, username, password, role, signal):
    username = (username or "").strip()
    password = (password or "").strip()

    if not username or not password:
        return no_update, "Introduce usuario y contraseña.", True, "danger", no_update, no_update
    if len(username) < 3:
        return no_update, "El usuario debe tener al menos 3 caracteres.", True, "danger", no_update, no_update

    users  = _load_users()
    action = "actualizado" if username in users else "creado"
    users[username] = {"password": generate_password_hash(password), "role": role or "user"}
    _save_users(users)
    return (signal or 0) + 1, f"Usuario '{username}' {action}.", True, "success", "", ""


# ── Modal de borrado unificado ────────────────────────────────────────────────
# El índice del botón codifica el tipo: "user:name" | "loc:uuid" | "org:uuid" | "role:name"

@app.callback(
    Output("admin-pending-delete", "data"),
    Output("admin-delete-modal", "is_open"),
    Output("admin-delete-modal-body", "children"),
    Input({"type": "admin-del-btn", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def open_delete_modal(n_clicks_list):
    ctx = callback_context
    if not ctx.triggered or all((n or 0) == 0 for n in n_clicks_list):
        return no_update, no_update, no_update

    raw_id = ctx.triggered[0]["prop_id"]
    try:
        index = json.loads(raw_id.split(".")[0])["index"]
    except Exception:
        return no_update, no_update, no_update

    kind, _, identifier = index.partition(":")

    # Cambio de rol — no es borrado, no abre modal
    if kind == "role":
        return no_update, no_update, no_update

    if kind == "user":
        body = html.P([
            "¿Eliminar al usuario ",
            html.Strong(identifier, className="text-danger"), "?",
            html.Br(),
            html.Span("Esta acción no se puede deshacer.", className="text-muted small"),
        ])
    elif kind == "loc":
        # Resolver nombre de la ubicación
        orgs   = _load_orgs()
        nombre = next(
            (l.get("name", identifier[:8]) for o in orgs for l in o.get("locations", [])
             if l["uuid"] == identifier),
            identifier[:8] + "…",
        )
        body = html.P([
            "¿Eliminar la ubicación ",
            html.Strong(nombre, className="text-danger"), "?",
            html.Br(),
            html.Span("Se eliminará del árbol pero no afecta al historial de datos.",
                      className="text-muted small"),
        ])
    elif kind == "org":
        orgs   = _load_orgs()
        org    = next((o for o in orgs if o.get("uuid") == identifier), None)
        nombre = org.get("name", identifier) if org else identifier
        n_locs = len(org.get("locations", [])) if org else 0
        body = html.Div([
            html.P([
                "¿Eliminar la organización ",
                html.Strong(nombre, className="text-danger"),
                " y todas sus ubicaciones?",
            ]),
            dbc.Alert(
                [html.I(className="fas fa-exclamation-triangle me-2"),
                 f"Se eliminarán {n_locs} ubicación{'es' if n_locs != 1 else ''} asociadas."],
                color="warning", className="rounded-3 border-0 py-2 mb-0",
            ),
        ])
    else:
        return no_update, no_update, no_update

    return index, True, body


@app.callback(
    Output("admin-crud-signal", "data", allow_duplicate=True),
    Output("admin-users-feedback", "children", allow_duplicate=True),
    Output("admin-users-feedback", "is_open", allow_duplicate=True),
    Output("admin-users-feedback", "color", allow_duplicate=True),
    Output("admin-locs-feedback", "children"),
    Output("admin-locs-feedback", "is_open"),
    Output("admin-locs-feedback", "color"),
    Output("admin-delete-modal", "is_open", allow_duplicate=True),
    Input("admin-confirm-delete-btn", "n_clicks"),
    Input("admin-cancel-delete-btn", "n_clicks"),
    State("admin-pending-delete", "data"),
    State("admin-crud-signal", "data"),
    prevent_initial_call=True,
)
def handle_delete_modal(_, __, pending, signal):
    ctx     = callback_context
    trigger = (ctx.triggered or [{}])[0].get("prop_id", "")

    _u = (no_update, False, no_update)   # user feedback unchanged
    _l = (no_update, False, no_update)   # loc feedback unchanged

    if "cancel" in trigger or not pending:
        return no_update, *_u, *_l, False

    kind, _, identifier = str(pending).partition(":")

    if kind == "user":
        users = _load_users()
        if identifier not in users:
            return no_update, f"Usuario '{identifier}' no encontrado.", True, "warning", *_l, False
        del users[identifier]
        _save_users(users)
        return (signal or 0) + 1, f"Usuario '{identifier}' eliminado.", True, "success", *_l, False

    if kind == "loc":
        orgs = _load_orgs()
        nombre = None
        for org in orgs:
            locs = org.get("locations", [])
            hit  = next((l for l in locs if l["uuid"] == identifier), None)
            if hit:
                nombre = hit.get("name", identifier[:8])
                org["locations"] = [l for l in locs if l["uuid"] != identifier]
                break
        if not nombre:
            return no_update, *_u, f"Ubicación no encontrada.", True, "warning", False
        _save_orgs(orgs)
        return (signal or 0) + 1, *_u, f"Ubicación '{nombre}' eliminada.", True, "success", False

    if kind == "org":
        orgs    = _load_orgs()
        target  = next((o for o in orgs if o.get("uuid") == identifier), None)
        if not target:
            return no_update, *_u, "Organización no encontrada.", True, "warning", False
        nombre  = target.get("name", identifier)
        new_orgs = [o for o in orgs if o.get("uuid") != identifier]
        _save_orgs(new_orgs)
        return (signal or 0) + 1, *_u, f"Organización '{nombre}' eliminada.", True, "success", False

    return no_update, *_u, *_l, False


@app.callback(
    Output("admin-crud-signal", "data", allow_duplicate=True),
    Output("admin-users-feedback", "children", allow_duplicate=True),
    Output("admin-users-feedback", "is_open", allow_duplicate=True),
    Output("admin-users-feedback", "color", allow_duplicate=True),
    Input({"type": "admin-del-btn", "index": ALL}, "n_clicks"),
    State("admin-crud-signal", "data"),
    prevent_initial_call=True,
)
def toggle_role(n_clicks_list, signal):
    ctx = callback_context
    if not ctx.triggered or all((n or 0) == 0 for n in n_clicks_list):
        return no_update, no_update, no_update, no_update

    raw_id = ctx.triggered[0]["prop_id"]
    try:
        index = json.loads(raw_id.split(".")[0])["index"]
    except Exception:
        return no_update, no_update, no_update, no_update

    kind, _, username = index.partition(":")
    if kind != "role":
        return no_update, no_update, no_update, no_update

    users = _load_users()
    if username not in users:
        return no_update, f"Usuario '{username}' no encontrado.", True, "warning"

    entry    = _normalize(users[username])
    new_role = "admin" if entry.get("role", "user") == "user" else "user"
    entry["role"]  = new_role
    users[username] = entry
    _save_users(users)
    label = _ROLE_LABELS.get(new_role, new_role)
    return (signal or 0) + 1, f"'{username}' ahora es {label}.", True, "success"
