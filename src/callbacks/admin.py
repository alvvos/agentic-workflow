import json

import dash_bootstrap_components as dbc
import flask
from dash import ALL, Input, Output, State, callback_context, dcc, html, no_update
from werkzeug.security import generate_password_hash

from src.core.config import MODO_DESARROLLO, app
from src.db.store import get_conn

_ROLE_LABELS = {"admin": "Administrador", "user": "Usuario"}
_ROLE_COLORS = {"admin": "danger", "user": "primary"}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_users() -> dict:
    rows = (
        get_conn()
        .execute("SELECT usuario_id, password_hash, role FROM usuarios ORDER BY usuario_id")
        .fetchall()
    )
    return {r[0]: {"password": r[1], "role": r[2] or "user"} for r in rows}


def _upsert_user(username: str, password_hash: str, role: str) -> None:
    get_conn().execute(
        """
        INSERT INTO usuarios (usuario_id, password_hash, role)
        VALUES (?, ?, ?)
        ON CONFLICT (usuario_id) DO UPDATE SET password_hash = excluded.password_hash, role = excluded.role
    """,
        [username, password_hash, role],
    )


def _delete_user(username: str) -> None:
    get_conn().execute("DELETE FROM usuarios WHERE usuario_id = ?", [username])


def _update_role(username: str, new_role: str) -> None:
    get_conn().execute("UPDATE usuarios SET role = ? WHERE usuario_id = ?", [new_role, username])


def _get_user_org_access(user_id: str) -> list[str]:
    rows = (
        get_conn()
        .execute(
            "SELECT org_id FROM accesos_usuario WHERE usuario_id = ? ORDER BY org_id", [user_id]
        )
        .fetchall()
    )
    return [r[0] for r in rows]


def _set_user_org_access(user_id: str, org_uuids: list[str]) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM accesos_usuario WHERE usuario_id = ?", [user_id])
    if org_uuids:
        conn.executemany(
            "INSERT INTO accesos_usuario (usuario_id, org_id) VALUES (?, ?)",
            [(user_id, uuid) for uuid in org_uuids],
        )


def _normalize(entry) -> dict:
    if isinstance(entry, str):
        return {"password": entry, "role": "user"}
    return entry


def _current_user() -> str:
    if MODO_DESARROLLO:
        return "local_dev"
    return flask.session.get("user", "")


def _load_orgs() -> list:
    conn = get_conn()
    orgs_rows = conn.execute("SELECT org_id, nombre FROM organizaciones ORDER BY nombre").fetchall()
    locs_rows = conn.execute(
        "SELECT ubicacion_id, org_id, nombre, lat, lon, ciudad, provincia "
        "FROM ubicaciones WHERE activa = TRUE ORDER BY nombre"
    ).fetchall()
    zones_rows = conn.execute(
        "SELECT zona_id, ubicacion_id, nombre FROM zonas ORDER BY nombre"
    ).fetchall()

    zones_by_loc: dict = {}
    for z in zones_rows:
        zones_by_loc.setdefault(z[1], []).append({"uuid": z[0], "zoneName": z[2]})

    locs_by_org: dict = {}
    for loc in locs_rows:
        locs_by_org.setdefault(loc[1], []).append(
            {
                "uuid": loc[0],
                "name": loc[2],
                "lat": loc[3],
                "lon": loc[4],
                "city": loc[5],
                "province": loc[6],
                "zones": zones_by_loc.get(loc[0], []),
            }
        )

    return [{"uuid": o[0], "name": o[1], "locations": locs_by_org.get(o[0], [])} for o in orgs_rows]


# ── Zone hierarchy modal ──────────────────────────────────────────────────────


def _zone_modal_body(loc_uuid: str):
    conn = get_conn()
    zones = conn.execute(
        "SELECT zona_id, nombre, zone_type, parent_zona_id, hidden"
        " FROM zonas WHERE ubicacion_id = ? ORDER BY nombre",
        [loc_uuid],
    ).fetchall()

    if not zones:
        return dbc.Alert(
            [
                html.I(className="fas fa-info-circle me-2"),
                "Esta ubicación no tiene zonas registradas.",
            ],
            color="info",
            className="rounded-3 border-0",
        )

    # Build parent→children map; treat unknown parents as roots
    by_uuid = {z[0]: z for z in zones}
    children_of = {z[0]: [] for z in zones}
    roots = []
    for z in zones:
        zone_uuid, _, _, parent_uuid, _ = z
        if parent_uuid and parent_uuid in by_uuid:
            children_of[parent_uuid].append(zone_uuid)
        else:
            roots.append(zone_uuid)

    all_opts = [{"label": z[1], "value": z[0]} for z in zones]

    def _rows(uuid: str, depth: int = 0) -> list:
        zone_uuid, nombre, zone_type, parent_uuid, hidden = by_uuid[uuid]
        visible = not bool(hidden)
        is_leaf = not children_of[uuid]

        opts = [{"label": "Sin padre", "value": ""}] + [
            o for o in all_opts if o["value"] != zone_uuid
        ]
        type_badge = (
            dbc.Badge(zone_type, color="info", pill=True, className="fw-normal")
            if zone_type
            else html.Span("—", className="text-muted small")
        )
        icon = "fa-circle fa-xs text-muted" if is_leaf else "fa-layer-group text-primary"
        name_cell = html.Div(
            [
                html.I(className=f"fas {icon} me-2"),
                html.Span(nombre, className="fw-semibold"),
                *(
                    [
                        dbc.Badge(
                            "hoja",
                            color="success",
                            pill=True,
                            className="fw-normal ms-2 opacity-75",
                        )
                    ]
                    if is_leaf
                    else []
                ),
            ],
            style={"paddingLeft": f"{depth * 22}px"},
        )
        result = [
            html.Tr(
                [
                    html.Td(name_cell, className="align-middle py-2 px-3"),
                    html.Td(type_badge, className="align-middle"),
                    html.Td(
                        dcc.Dropdown(
                            id={"type": "zone-parent-select", "index": zone_uuid},
                            options=opts,
                            value=parent_uuid or "",
                            clearable=False,
                            className="shadow-sm",
                            style={"minWidth": "180px"},
                        ),
                        className="align-middle",
                    ),
                    html.Td(
                        dbc.Switch(
                            id={"type": "zone-visible-toggle", "index": zone_uuid},
                            value=visible,
                            label="Visible" if visible else "Oculta",
                            className="mb-0",
                        ),
                        className="align-middle text-center",
                    ),
                ]
            )
        ]
        for child_uuid in children_of[uuid]:
            result.extend(_rows(child_uuid, depth + 1))
        return result

    rows = []
    for root_uuid in roots:
        rows.extend(_rows(root_uuid))

    return dbc.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th(
                            "Zona", className="px-3 py-2 text-muted small text-uppercase fw-bold"
                        ),
                        html.Th("Tipo", className="py-2 text-muted small text-uppercase fw-bold"),
                        html.Th(
                            "Zona padre", className="py-2 text-muted small text-uppercase fw-bold"
                        ),
                        html.Th(
                            "Display",
                            className="py-2 text-center text-muted small text-uppercase fw-bold",
                        ),
                    ]
                ),
                className="bg-light",
            ),
            html.Tbody(rows),
        ],
        bordered=False,
        hover=True,
        responsive=True,
        className="mb-0",
    )


# ── Render helpers ────────────────────────────────────────────────────────────


def _render_users_table(users: dict) -> html.Div:
    if not users:
        return html.Div(
            dbc.Alert(
                [html.I(className="fas fa-info-circle me-2"), "No hay usuarios registrados."],
                color="info",
                className="rounded-3 border-0 m-3",
            ),
        )

    rows = []
    for username, raw in sorted(users.items()):
        entry = _normalize(raw)
        role = entry.get("role", "user")
        me = username == _current_user()
        rows.append(
            html.Tr(
                [
                    html.Td(
                        [
                            html.Span(
                                username[0].upper(),
                                className="badge rounded-circle bg-primary me-2 fw-bold",
                                style={
                                    "width": "28px",
                                    "height": "28px",
                                    "lineHeight": "20px",
                                    "fontSize": "0.75rem",
                                    "display": "inline-flex",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                },
                            ),
                            html.Span(username, className="fw-bold"),
                            *(
                                [html.Span(" (tú)", className="text-muted small ms-1 fst-italic")]
                                if me
                                else []
                            ),
                        ],
                        className="align-middle py-3 px-4",
                    ),
                    html.Td(
                        dbc.Badge(
                            [
                                html.I(
                                    className=f"fas {'fa-shield-alt' if role == 'admin' else 'fa-user'} me-1"
                                ),
                                _ROLE_LABELS.get(role, role),
                            ],
                            color=_ROLE_COLORS.get(role, "secondary"),
                            className="rounded-pill px-3 py-2",
                        ),
                        className="align-middle",
                    ),
                    html.Td(
                        dbc.ButtonGroup(
                            [
                                dbc.Button(
                                    [html.I(className="fas fa-key me-1"), "Acceso"],
                                    id={"type": "admin-access-btn", "index": username},
                                    size="sm",
                                    color="info",
                                    outline=True,
                                    className="rounded-start-3 fw-bold",
                                    disabled=role == "admin",
                                    title=(
                                        "Gestionar acceso a organizaciones"
                                        if role != "admin"
                                        else "Los administradores tienen acceso total"
                                    ),
                                ),
                                dbc.Button(
                                    [
                                        html.I(
                                            className=f"fas {'fa-user-shield' if role == 'user' else 'fa-user'} me-1"
                                        ),
                                        "→ Admin" if role == "user" else "→ Usuario",
                                    ],
                                    id={"type": "admin-del-btn", "index": f"role:{username}"},
                                    size="sm",
                                    color="warning" if role == "user" else "secondary",
                                    outline=True,
                                    className="fw-bold",
                                    disabled=me,
                                ),
                                dbc.Button(
                                    html.I(className="fas fa-trash-alt"),
                                    id={"type": "admin-del-btn", "index": f"user:{username}"},
                                    size="sm",
                                    color="danger",
                                    outline=True,
                                    className="rounded-end-3",
                                    disabled=me,
                                ),
                            ]
                        ),
                        className="align-middle text-end pe-4",
                    ),
                ],
                className="border-bottom",
            )
        )

    return dbc.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th(
                            "Usuario", className="px-4 py-3 text-muted small text-uppercase fw-bold"
                        ),
                        html.Th("Rol", className="py-3 text-muted small text-uppercase fw-bold"),
                        html.Th(
                            "Acciones",
                            className="py-3 pe-4 text-end text-muted small text-uppercase fw-bold",
                        ),
                    ]
                ),
                className="bg-light",
            ),
            html.Tbody(rows),
        ],
        bordered=False,
        hover=True,
        responsive=True,
        className="mb-0 align-middle",
    )


def _loc_row(loc: dict) -> html.Tr:
    zones = loc.get("zones", [])
    lat = loc.get("lat") or loc.get("latitude")
    lon = loc.get("lon") or loc.get("longitude")
    city = loc.get("city") or loc.get("province") or ("" if not lat else f"{lat:.3f}, {lon:.3f}")
    return html.Tr(
        [
            html.Td(
                [
                    html.I(className="fas fa-store me-2 text-primary"),
                    html.Span(loc.get("name", "—"), className="fw-semibold"),
                ],
                className="align-middle py-3 px-4",
            ),
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
                    [
                        html.I(className="fas fa-layer-group me-1"),
                        f"{len(zones)} zona{'s' if len(zones) != 1 else ''}",
                    ],
                    color="info",
                    pill=True,
                ),
                className="align-middle",
            ),
            html.Td(
                dbc.ButtonGroup(
                    [
                        dbc.Button(
                            [html.I(className="fas fa-sitemap me-1"), "Zonas"],
                            id={"type": "admin-edit-zones-btn", "index": loc["uuid"]},
                            size="sm",
                            color="primary",
                            outline=True,
                            className="rounded-start-3 fw-bold",
                        ),
                        dbc.Button(
                            html.I(className="fas fa-trash-alt"),
                            id={"type": "admin-del-btn", "index": f"loc:{loc['uuid']}"},
                            size="sm",
                            color="danger",
                            outline=True,
                            className="rounded-end-3",
                        ),
                    ]
                ),
                className="align-middle text-end pe-4",
            ),
        ],
        className="border-bottom",
    )


def _render_locs_tree(orgs: list) -> html.Div:
    n_locs = sum(len(o.get("locations", [])) for o in orgs)
    n_zones = sum(len(loc.get("zones", [])) for o in orgs for loc in o.get("locations", []))

    # ── Resumen en strip ─────────────────────────────────────────────────────
    stats_strip = html.Div(
        dbc.Row(
            [
                dbc.Col(
                    _stat_pill(len(orgs), "Organizaciones", "fa-building", "text-primary"), xs=4
                ),
                dbc.Col(_stat_pill(n_locs, "Ubicaciones", "fa-store", "text-success"), xs=4),
                dbc.Col(_stat_pill(n_zones, "Zonas", "fa-layer-group", "text-info"), xs=4),
            ],
            className="g-0",
        ),
        className="p-3 bg-light rounded-4 border-start border-primary border-4 shadow-sm mb-4",
    )

    # ── Una card por organización ─────────────────────────────────────────────
    org_cards = []
    for org in orgs:
        locs = org.get("locations", [])
        org_uuid = org.get("uuid", org.get("name", "?"))
        n = len(locs)

        loc_table = dbc.Table(
            [
                html.Thead(
                    html.Tr(
                        [
                            html.Th(
                                "Nombre",
                                className="px-4 py-2 text-muted small text-uppercase fw-bold",
                            ),
                            html.Th(
                                "Ciudad", className="py-2 text-muted small text-uppercase fw-bold"
                            ),
                            html.Th(
                                "UUID",
                                className="py-2 text-muted small text-uppercase fw-bold d-none d-md-table-cell",
                            ),
                            html.Th(
                                "Zonas", className="py-2 text-muted small text-uppercase fw-bold"
                            ),
                            html.Th(
                                "Acciones",
                                className="py-2 pe-4 text-end text-muted small text-uppercase fw-bold",
                            ),
                        ]
                    ),
                    className="bg-light",
                ),
                html.Tbody(
                    [_loc_row(loc) for loc in locs]
                    if locs
                    else [
                        html.Tr(
                            html.Td(
                                html.Span(
                                    [html.I(className="fas fa-inbox me-2"), "Sin ubicaciones"],
                                    className="text-muted fst-italic small",
                                ),
                                colSpan=5,
                                className="text-center py-4",
                            )
                        )
                    ]
                ),
            ],
            bordered=False,
            hover=bool(locs),
            responsive=True,
            className="mb-0 align-middle",
        )

        org_cards.append(
            dbc.Card(
                [
                    dbc.CardHeader(
                        dbc.Row(
                            [
                                dbc.Col(
                                    [
                                        html.I(className="fas fa-building me-2 text-primary"),
                                        html.Span(org.get("name", "—"), className="fw-bold me-2"),
                                        dbc.Badge(
                                            f"{n} ubicación{'es' if n != 1 else ''}",
                                            color="secondary",
                                            pill=True,
                                            className="ms-1",
                                        ),
                                    ],
                                    className="d-flex align-items-center",
                                ),
                                dbc.Col(
                                    dbc.Button(
                                        [html.I(className="fas fa-trash-alt me-1"), "Eliminar org"],
                                        id={"type": "admin-del-btn", "index": f"org:{org_uuid}"},
                                        size="sm",
                                        color="danger",
                                        outline=True,
                                        className="rounded-3 fw-bold",
                                    ),
                                    className="text-end",
                                ),
                            ],
                            className="align-items-center g-0",
                        ),
                        className="bg-white border-bottom py-2 px-4",
                    ),
                    dbc.CardBody(loc_table, className="p-0"),
                ],
                className="border-0 shadow-sm rounded-4 mb-3 overflow-hidden",
            )
        )

    return html.Div([stats_strip, *org_cards])


def _stat_pill(value, label, icon, color_cls) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.I(className=f"fas {icon} me-2 {color_cls}"),
                    html.Span(str(value), className=f"fw-bold {color_cls} me-1"),
                    html.Span(label, className="text-muted small"),
                ],
                className="d-flex align-items-center justify-content-center",
            ),
        ]
    )


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
    Input("data-version", "data"),
)
def refresh_locs_tree(active_tab, _signal, _version):
    if active_tab != "admin-tab-locs":
        return no_update
    orgs = _load_orgs()
    if not orgs:
        return dbc.Alert(
            "No se encontró el árbol de ubicaciones.",
            color="warning",
            className="rounded-3 border-0",
        )
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
        return (
            no_update,
            "El usuario debe tener al menos 3 caracteres.",
            True,
            "danger",
            no_update,
            no_update,
        )

    exists = username in _load_users()
    action = "actualizado" if exists else "creado"
    _upsert_user(username, generate_password_hash(password), role or "user")
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
        body = html.P(
            [
                "¿Eliminar al usuario ",
                html.Strong(identifier, className="text-danger"),
                "?",
                html.Br(),
                html.Span("Esta acción no se puede deshacer.", className="text-muted small"),
            ]
        )
    elif kind == "loc":
        # Resolver nombre de la ubicación
        orgs = _load_orgs()
        nombre = next(
            (
                loc.get("name", identifier[:8])
                for o in orgs
                for loc in o.get("locations", [])
                if loc["uuid"] == identifier
            ),
            identifier[:8] + "…",
        )
        body = html.P(
            [
                "¿Eliminar la ubicación ",
                html.Strong(nombre, className="text-danger"),
                "?",
                html.Br(),
                html.Span(
                    "Se eliminará del árbol pero no afecta al historial de datos.",
                    className="text-muted small",
                ),
            ]
        )
    elif kind == "org":
        orgs = _load_orgs()
        org = next((o for o in orgs if o.get("uuid") == identifier), None)
        nombre = org.get("name", identifier) if org else identifier
        n_locs = len(org.get("locations", [])) if org else 0
        body = html.Div(
            [
                html.P(
                    [
                        "¿Eliminar la organización ",
                        html.Strong(nombre, className="text-danger"),
                        " y todas sus ubicaciones?",
                    ]
                ),
                dbc.Alert(
                    [
                        html.I(className="fas fa-exclamation-triangle me-2"),
                        f"Se eliminarán {n_locs} ubicación{'es' if n_locs != 1 else ''} asociadas.",
                    ],
                    color="warning",
                    className="rounded-3 border-0 py-2 mb-0",
                ),
            ]
        )
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
    ctx = callback_context
    trigger = (ctx.triggered or [{}])[0].get("prop_id", "")

    _u = (no_update, False, no_update)  # user feedback unchanged
    _l = (no_update, False, no_update)  # loc feedback unchanged

    if "cancel" in trigger or not pending:
        return no_update, *_u, *_l, False

    kind, _, identifier = str(pending).partition(":")

    if kind == "user":
        if identifier not in _load_users():
            return no_update, f"Usuario '{identifier}' no encontrado.", True, "warning", *_l, False
        _delete_user(identifier)
        return (signal or 0) + 1, f"Usuario '{identifier}' eliminado.", True, "success", *_l, False

    if kind == "loc":
        conn = get_conn()
        row = conn.execute(
            "SELECT nombre FROM ubicaciones WHERE ubicacion_id = ?", [identifier]
        ).fetchone()
        if not row:
            return no_update, *_u, "Ubicación no encontrada.", True, "warning", False
        nombre = row[0]
        conn.execute("DELETE FROM ubicaciones WHERE ubicacion_id = ?", [identifier])
        return (signal or 0) + 1, *_u, f"Ubicación '{nombre}' eliminada.", True, "success", False

    if kind == "org":
        conn = get_conn()
        row = conn.execute(
            "SELECT nombre FROM organizaciones WHERE org_id = ?", [identifier]
        ).fetchone()
        if not row:
            return no_update, *_u, "Organización no encontrada.", True, "warning", False
        nombre = row[0]
        conn.execute("DELETE FROM organizaciones WHERE org_id = ?", [identifier])
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

    current_role = _normalize(users[username]).get("role", "user")
    new_role = "admin" if current_role == "user" else "user"
    _update_role(username, new_role)
    label = _ROLE_LABELS.get(new_role, new_role)
    return (signal or 0) + 1, f"'{username}' ahora es {label}.", True, "success"


# ── Modal jerarquía de zonas ──────────────────────────────────────────────────


@app.callback(
    Output("admin-zone-modal", "is_open"),
    Output("admin-zone-modal-title", "children"),
    Output("admin-zone-modal-body", "children"),
    Output("admin-zone-edit-loc", "data"),
    Input({"type": "admin-edit-zones-btn", "index": ALL}, "n_clicks"),
    Input("admin-zone-modal-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def open_zone_modal(edit_clicks, _cancel):
    ctx = callback_context
    trigger = (ctx.triggered or [{}])[0].get("prop_id", "")

    if "admin-zone-modal-cancel" in trigger:
        return False, no_update, no_update, no_update

    if all((n or 0) == 0 for n in edit_clicks):
        return no_update, no_update, no_update, no_update

    try:
        loc_uuid = json.loads(trigger.split(".")[0])["index"]
    except Exception:
        return no_update, no_update, no_update, no_update

    row = (
        get_conn()
        .execute("SELECT nombre FROM ubicaciones WHERE ubicacion_id = ?", [loc_uuid])
        .fetchone()
    )
    nombre_loc = row[0] if row else loc_uuid[:8] + "…"

    return True, f"Jerarquía de zonas — {nombre_loc}", _zone_modal_body(loc_uuid), loc_uuid


# ── Modal acceso a organizaciones ────────────────────────────────────────────


@app.callback(
    Output("admin-access-modal", "is_open"),
    Output("admin-access-modal-title", "children"),
    Output("admin-access-modal-info", "children"),
    Output("admin-access-checklist", "options"),
    Output("admin-access-checklist", "value"),
    Output("admin-access-modal-user", "data"),
    Input({"type": "admin-access-btn", "index": ALL}, "n_clicks"),
    Input("admin-access-modal-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def open_access_modal(access_clicks, _cancel):
    from src.core import data_master as dm

    ctx = callback_context
    trigger = (ctx.triggered or [{}])[0].get("prop_id", "")

    if "admin-access-modal-cancel" in trigger:
        return False, no_update, no_update, no_update, no_update, no_update

    if all((n or 0) == 0 for n in access_clicks):
        return no_update, no_update, no_update, no_update, no_update, no_update

    try:
        username = json.loads(trigger.split(".")[0])["index"]
    except Exception:
        return no_update, no_update, no_update, no_update, no_update, no_update

    dm.reload_if_changed()
    current = _get_user_org_access(username)
    options = [{"label": o["label"], "value": o["value"]} for o in dm.opciones_orgs]
    info = [
        html.I(className="fas fa-info-circle me-2 text-info"),
        f"Organizaciones accesibles para '{username}'. Sin selección, el usuario no verá datos.",
    ]
    return True, f"Acceso a organizaciones — {username}", info, options, current, username


@app.callback(
    Output("admin-access-modal", "is_open", allow_duplicate=True),
    Output("admin-users-feedback", "children", allow_duplicate=True),
    Output("admin-users-feedback", "is_open", allow_duplicate=True),
    Output("admin-users-feedback", "color", allow_duplicate=True),
    Output("admin-crud-signal", "data", allow_duplicate=True),
    Input("admin-access-modal-save", "n_clicks"),
    State("admin-access-checklist", "value"),
    State("admin-access-modal-user", "data"),
    State("admin-crud-signal", "data"),
    prevent_initial_call=True,
)
def save_access_modal(n_clicks, selected_orgs, user_id, signal):
    if not n_clicks or not user_id:
        return no_update, no_update, no_update, no_update, no_update
    _set_user_org_access(user_id, selected_orgs or [])
    n = len(selected_orgs or [])
    msg = f"Acceso de '{user_id}' actualizado — {n} organización{'es' if n != 1 else ''}."
    return False, msg, True, "success", (signal or 0) + 1


@app.callback(
    Output("admin-zone-modal", "is_open", allow_duplicate=True),
    Output("admin-locs-feedback", "children", allow_duplicate=True),
    Output("admin-locs-feedback", "is_open", allow_duplicate=True),
    Output("admin-locs-feedback", "color", allow_duplicate=True),
    Output("admin-crud-signal", "data", allow_duplicate=True),
    Input("admin-zone-modal-save", "n_clicks"),
    State({"type": "zone-parent-select", "index": ALL}, "value"),
    State({"type": "zone-parent-select", "index": ALL}, "id"),
    State({"type": "zone-visible-toggle", "index": ALL}, "value"),
    State("admin-crud-signal", "data"),
    prevent_initial_call=True,
)
def save_zone_hierarchy(n_clicks, parent_values, zone_ids, visible_values, signal):
    if not n_clicks or not zone_ids:
        return no_update, no_update, no_update, no_update, no_update

    conn = get_conn()
    uuid_to_parent: dict[str, str | None] = {}
    for id_dict, parent_val, visible in zip(zone_ids, parent_values, visible_values):
        zone_uuid = id_dict["index"]
        parent_uuid = parent_val if parent_val else None
        hidden = not bool(visible)
        uuid_to_parent[zone_uuid] = parent_uuid
        conn.execute(
            "UPDATE zonas SET parent_zona_id = ?, hidden = ? WHERE zona_id = ?",
            [parent_uuid, hidden, zone_uuid],
        )

    n = len(zone_ids)
    return (
        False,
        f"Jerarquía publicada — {n} zona{'s' if n != 1 else ''} actualizadas.",
        True,
        "success",
        (signal or 0) + 1,
    )


@app.callback(
    Output("modal-admin-panel", "is_open"),
    Input("btn-admin-panel", "n_clicks"),
    State("modal-admin-panel", "is_open"),
    prevent_initial_call=True,
)
def toggle_admin_panel(n, is_open):
    return not is_open
