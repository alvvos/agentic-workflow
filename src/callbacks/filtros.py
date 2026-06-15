from dash import Output, Input, no_update, html, ALL
import dash_bootstrap_components as dbc
from src.core.config import app
from src.core import data_master


@app.callback(Output("sidebar-periodo-wrapper", "style"), Input("tabs-panel", "value"))
def toggle_periodo_sidebar(tab):
    if tab in ('tab-ejecutivo', 'tab-ml', 'tab-admin', 'tab-prediccion-publica'):
        return {"display": "none"}
    return {}


@app.callback(
    Output("pm-options-wrapper", "style"),
    Output("bi-comparativa-wrapper", "style"),
    Input("tabs-panel", "value"),
)
def toggle_sidebar_options(tab):
    show = {"display": "block"}
    hide = {"display": "none"}
    return (show if tab == "tab-ejecutivo" else hide,
            show if tab == "tab-auditoria" else hide)


@app.callback(Output("contenedor-rango", "style"), Output("contenedor-dia", "style"), Input("tipo-fecha", "value"))
def toggle_fecha(tipo):
    if tipo == "dia":
        return {"display": "none"}, {"display": "block"}
    if tipo == "rango":
        return {"display": "block"}, {"display": "none"}
    return {"display": "none"}, {"display": "none"}


@app.callback(Output("drop-locs", "options"), Output("drop-locs", "value"), Input("drop-org", "value"))
def actualizar_locs(org_uuid):
    data_master.reload_if_changed()
    if not org_uuid:
        return [], []
    opciones = data_master.mapa_locs_por_org.get(org_uuid, [])
    default = [opciones[0]['value']] if opciones else []
    return opciones, default


def _funnel_key(z):
    tipo   = z.get('tipo', '').lower()
    nombre = z.get('label', '').lower()
    if tipo == 'entry_zone' or 'calle' in nombre or 'exterior' in nombre:
        return 0
    if tipo == 'end_zone':
        return 3
    if tipo == 'last_zone' or 'caja' in nombre:
        return 2
    return 1  # tienda / interior / resto


@app.callback(
    [Output("radar-drop-zonas", "options"), Output("radar-drop-zonas", "value")],
    [Input("drop-locs", "value")]
)
def auto_fill_zonas(locs):
    data_master.reload_if_changed()
    if not locs:
        return [], []
    opts_bi = []
    vistos_bi = set()

    for l in locs:
        for z in data_master.mapa_zonas_por_loc.get(l, []):
            nombre = z['value']
            if nombre not in vistos_bi and not z.get('padre_uuid'):
                opts_bi.append(z)
                vistos_bi.add(nombre)

    opts_bi.sort(key=_funnel_key)
    vals_bi = [z['value'] for z in opts_bi]
    return opts_bi, vals_bi


@app.callback(
    Output("radar-child-zones-wrapper", "children"),
    [Input("drop-locs", "value"), Input("radar-drop-zonas", "value")]
)
def render_child_zone_selectors(locs, selected_parents):
    data_master.reload_if_changed()
    if not locs or not selected_parents:
        return []
    children_ui = []
    for parent_name in selected_parents:
        child_zones = []
        seen_vals: set = set()
        for l in (locs or []):
            for z in data_master.mapa_hijos_por_zona.get(l, {}).get(parent_name, []):
                if z['value'] not in seen_vals:
                    child_zones.append(z)
                    seen_vals.add(z['value'])
        if not child_zones:
            continue
        children_ui.append(
            html.Div([
                html.Label(
                    [html.I(className="fas fa-sitemap me-1"), f"Subzonas — {parent_name}"],
                    className="fw-bold small text-secondary mb-2 ms-1",
                ),
                dbc.Checklist(
                    id={"type": "child-zone-checklist", "index": parent_name},
                    options=child_zones,
                    value=[],
                    inline=True,
                    input_class_name="btn-check",
                    label_class_name="btn btn-outline-secondary mb-2 me-2 fw-bold shadow-sm rounded-3",
                ),
            ], className="ms-3 mb-3 border-start border-2 border-primary ps-3")
        )
    return children_ui


@app.callback(
    Output("zonas-activas-combined", "data"),
    [Input("radar-drop-zonas", "value"),
     Input({"type": "child-zone-checklist", "index": ALL}, "value")]
)
def combine_zones(parent_zones, child_zones_all):
    combined = list(parent_zones or [])
    for child_list in (child_zones_all or []):
        if child_list:
            combined.extend(child_list)
    return list(dict.fromkeys(combined))  # preserves order, deduplicates


# Refresca las opciones del dropdown de orgs cuando el admin modifica el árbol.
# Solo se ejecuta en sesiones admin (admin-crud-signal solo existe en el DOM admin).
@app.callback(
    Output("drop-org", "options"),
    Input("admin-crud-signal", "data"),
    prevent_initial_call=True,
)
def refresh_org_options(signal):
    data_master.reload_if_changed()
    from src.core.auth import get_current_org_access
    return data_master.get_opciones_orgs_for_user(get_current_org_access())
