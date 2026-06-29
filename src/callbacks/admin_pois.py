"""
Callbacks de gestión de POIs (admin tab → sub-pestaña POIs).
"""

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, html, no_update

from src.core.config import app
from src.db.queries import get_pois_for_location, upsert_poi
from src.db.store import get_conn

_CAT_LABELS = {
    "metro": "Metro / Transporte",
    "tourist_poi": "Polo turístico",
    "event_venue": "Sala de eventos",
    "competitor": "Competidor",
    "otro": "Otro",
}
_CAT_ICONS = {
    "metro": "fas fa-subway text-primary",
    "tourist_poi": "fas fa-landmark text-warning",
    "event_venue": "fas fa-theater-masks text-purple",
    "competitor": "fas fa-store text-danger",
    "otro": "fas fa-map-pin text-muted",
}
_CAT_COLORS = {
    "metro": "primary",
    "tourist_poi": "warning",
    "event_venue": "info",
    "competitor": "danger",
    "otro": "secondary",
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_loc_options() -> list[dict]:
    rows = (
        get_conn()
        .execute(
            "SELECT location_uuid, nombre FROM dim_ubicaciones WHERE activa = TRUE ORDER BY nombre"
        )
        .fetchall()
    )
    return [{"label": r[1], "value": r[0]} for r in rows]


def _render_table(location_uuid: str) -> html.Div:
    pois = get_pois_for_location(location_uuid)
    if not pois:
        return html.Div(
            html.P(
                "No hay POIs registrados para esta ubicación.", className="text-muted small p-4"
            ),
        )

    rows = []
    for poi in pois:
        cat = poi["categoria"]
        rows.append(
            html.Tr(
                [
                    html.Td(
                        html.Span(
                            [
                                html.I(
                                    className=f"{_CAT_ICONS.get(cat, 'fas fa-map-pin text-muted')} me-2"
                                ),
                                poi["nombre"],
                            ]
                        ),
                        className="align-middle fw-bold small",
                    ),
                    html.Td(
                        dbc.Badge(
                            _CAT_LABELS.get(cat, cat),
                            color=_CAT_COLORS.get(cat, "secondary"),
                            pill=True,
                            className="small",
                        ),
                        className="align-middle",
                    ),
                    html.Td(
                        f"{poi['lat']:.4f}, {poi['lon']:.4f}",
                        className="align-middle text-muted small font-monospace",
                    ),
                    html.Td(
                        html.Span(f"{poi['valor_relativo']:.2f}", className="text-muted small"),
                        className="align-middle text-center",
                    ),
                    html.Td(
                        html.Span(poi["detalle"] or "—", className="text-muted small"),
                        className="align-middle",
                        style={
                            "maxWidth": "220px",
                            "overflow": "hidden",
                            "textOverflow": "ellipsis",
                            "whiteSpace": "nowrap",
                        },
                    ),
                    html.Td(
                        html.Span(
                            poi["fuente"] if "fuente" in poi else "manual",
                            className="text-muted small",
                        ),
                        className="align-middle text-center",
                    ),
                    html.Td(
                        dbc.ButtonGroup(
                            [
                                dbc.Button(
                                    html.I(className="fas fa-pencil-alt"),
                                    id={"type": "admin-poi-edit-btn", "index": poi["nombre"]},
                                    color="light",
                                    size="sm",
                                    className="rounded-start-2",
                                    title="Editar",
                                ),
                                dbc.Button(
                                    html.I(className="fas fa-trash-alt"),
                                    id={
                                        "type": "admin-poi-del-btn",
                                        "index": f"{location_uuid}|{poi['nombre']}|{cat}",
                                    },
                                    color="light",
                                    size="sm",
                                    className="rounded-end-2 text-danger",
                                    title="Eliminar",
                                ),
                            ]
                        ),
                        className="align-middle text-end pe-3",
                    ),
                ]
            )
        )

    return html.Div(
        dbc.Table(
            [
                html.Thead(
                    html.Tr(
                        [
                            html.Th("Nombre", className="small text-muted fw-bold"),
                            html.Th("Categoría", className="small text-muted fw-bold"),
                            html.Th("Coordenadas", className="small text-muted fw-bold"),
                            html.Th("Rel.", className="small text-muted fw-bold text-center"),
                            html.Th("Detalle", className="small text-muted fw-bold"),
                            html.Th("Fuente", className="small text-muted fw-bold text-center"),
                            html.Th("", className="small"),
                        ]
                    ),
                    className="bg-light",
                ),
                html.Tbody(rows),
            ],
            hover=True,
            responsive=True,
            className="mb-0 small",
        )
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────


@app.callback(
    Output("admin-pois-loc-select", "options"),
    Input("admin-sub-tabs", "active_tab"),
)
def _cargar_opciones_locs(active_tab):
    if active_tab != "admin-tab-pois":
        return no_update
    return _get_loc_options()


@app.callback(
    Output("admin-pois-table", "children"),
    Output("admin-pois-feedback", "children", allow_duplicate=True),
    Output("admin-pois-feedback", "color", allow_duplicate=True),
    Output("admin-pois-feedback", "is_open", allow_duplicate=True),
    Input("admin-pois-loc-select", "value"),
    Input({"type": "admin-poi-del-btn", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _actualizar_tabla(location_uuid, del_clicks):
    ctx = dash.callback_context
    triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""

    if "admin-poi-del-btn" in triggered and any(del_clicks):
        key = ctx.triggered[0]["prop_id"].split('"index":"')[1].rstrip('"}')
        parts = key.split("|")
        if len(parts) == 3:
            loc_uuid, nombre, categoria = parts
            try:
                get_conn().execute(
                    "UPDATE location_pois SET activo = FALSE "
                    "WHERE location_uuid = ? AND nombre = ? AND categoria = ?",
                    [loc_uuid, nombre, categoria],
                )
                feedback = f"POI '{nombre}' eliminado."
                location_uuid = loc_uuid
            except Exception as e:
                return no_update, f"Error al eliminar: {e}", "danger", True

        if not location_uuid:
            return html.Div(), feedback, "success", True
        return _render_table(location_uuid), feedback, "success", True

    if not location_uuid:
        return (
            html.Div(
                html.P(
                    "Selecciona una ubicación para ver sus POIs.", className="text-muted small p-4"
                )
            ),
            no_update,
            no_update,
            no_update,
        )

    return _render_table(location_uuid), no_update, no_update, no_update


@app.callback(
    Output("admin-poi-modal", "is_open"),
    Output("admin-poi-modal-title", "children"),
    Output("admin-poi-nombre", "value"),
    Output("admin-poi-categoria", "value"),
    Output("admin-poi-lat", "value"),
    Output("admin-poi-lon", "value"),
    Output("admin-poi-valor", "value"),
    Output("admin-poi-detalle", "value"),
    Output("admin-poi-radio", "value"),
    Input("admin-poi-add-btn", "n_clicks"),
    Input("admin-poi-modal-cancel", "n_clicks"),
    Input("admin-poi-modal-save", "n_clicks"),
    prevent_initial_call=True,
)
def _toggle_poi_modal(n_add, n_cancel, n_save):
    triggered = dash.callback_context.triggered[0]["prop_id"]
    if "admin-poi-add-btn" in triggered:
        return True, "Añadir POI", "", "metro", None, None, 0.5, "", None
    return (
        False,
        no_update,
        no_update,
        no_update,
        no_update,
        no_update,
        no_update,
        no_update,
        no_update,
    )


@app.callback(
    Output("admin-pois-feedback", "children"),
    Output("admin-pois-feedback", "color"),
    Output("admin-pois-feedback", "is_open"),
    Output("admin-pois-table", "children", allow_duplicate=True),
    Input("admin-poi-modal-save", "n_clicks"),
    State("admin-pois-loc-select", "value"),
    State("admin-poi-nombre", "value"),
    State("admin-poi-categoria", "value"),
    State("admin-poi-lat", "value"),
    State("admin-poi-lon", "value"),
    State("admin-poi-valor", "value"),
    State("admin-poi-detalle", "value"),
    State("admin-poi-radio", "value"),
    prevent_initial_call=True,
)
def _guardar_poi(n, location_uuid, nombre, categoria, lat, lon, valor, detalle, radio):
    if not n:
        return no_update, no_update, no_update, no_update
    if not location_uuid:
        return "Selecciona una ubicación primero.", "warning", True, no_update
    if not nombre or lat is None or lon is None:
        return "Nombre, latitud y longitud son obligatorios.", "warning", True, no_update

    org_row = (
        get_conn()
        .execute("SELECT org_uuid FROM dim_ubicaciones WHERE location_uuid = ?", [location_uuid])
        .fetchone()
    )
    if not org_row:
        return "Ubicación no encontrada.", "danger", True, no_update

    try:
        upsert_poi(
            location_uuid=location_uuid,
            org_uuid=org_row[0],
            nombre=nombre.strip(),
            lat=float(lat),
            lon=float(lon),
            categoria=categoria or "otro",
            valor_relativo=float(valor) if valor is not None else 0.5,
            detalle=detalle.strip() if detalle else None,
            radio_m=int(radio) if radio else None,
            fuente="manual",
        )
        return f"POI '{nombre}' guardado.", "success", True, _render_table(location_uuid)
    except Exception as e:
        return f"Error: {e}", "danger", True, no_update


@app.callback(
    Output("admin-pois-feedback", "children", allow_duplicate=True),
    Output("admin-pois-feedback", "color", allow_duplicate=True),
    Output("admin-pois-feedback", "is_open", allow_duplicate=True),
    Output("admin-pois-table", "children", allow_duplicate=True),
    Input("admin-pois-sync-btn", "n_clicks"),
    State("admin-pois-loc-select", "value"),
    prevent_initial_call=True,
)
def _sync_esri_places(n, location_uuid):
    if not n or not location_uuid:
        return no_update, no_update, no_update, no_update
    try:
        from src.data_ingestion.mensual.esri_places import sync_location

        n_upserted = sync_location(location_uuid, verbose=False)
        msg = f"Esri Places: {n_upserted} POI(s) sincronizados."
        return msg, "success", True, _render_table(location_uuid)
    except ImportError:
        return ("Módulo esri_places no disponible — verifica ESRI_KEY.", "warning", True, no_update)
    except Exception as e:
        return f"Error Esri Places: {e}", "danger", True, no_update
