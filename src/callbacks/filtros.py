import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, html

from src.core import data_master
from src.core.config import app


@app.callback(
    Output("sidebar-open", "data"),
    Input("btn-sidebar-toggle", "n_clicks"),
    State("sidebar-open", "data"),
    prevent_initial_call=True,
)
def toggle_sidebar_open(_, is_open):
    return not is_open


@app.callback(
    Output("sidebar-col", "style"),
    Output("main-col", "style"),
    Output("sidebar-toggle-icon", "className"),
    Input("sidebar-open", "data"),
)
def apply_sidebar_state(is_open):
    if is_open:
        return {}, {}, "fas fa-bars"
    return (
        {"display": "none"},
        {"flex": "0 0 100%", "maxWidth": "100%"},
        "fas fa-chevron-right",
    )


@app.callback(Output("sidebar-periodo-wrapper", "style"), Input("tabs-panel", "value"))
def toggle_periodo_sidebar(tab):
    if tab in ("tab-ejecutivo", "tab-ml", "tab-admin", "tab-prediccion-publica"):
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
    return (show if tab == "tab-ejecutivo" else hide, show if tab == "tab-auditoria" else hide)


@app.callback(
    Output("contenedor-rango", "style"),
    Output("contenedor-dia", "style"),
    Input("tipo-fecha", "value"),
)
def toggle_fecha(tipo):
    if tipo == "dia":
        return {"display": "none"}, {"display": "block"}
    if tipo == "rango":
        return {"display": "block"}, {"display": "none"}
    return {"display": "none"}, {"display": "none"}


@app.callback(
    Output("drop-locs", "options"), Output("drop-locs", "value"), Input("drop-org", "value")
)
def actualizar_locs(org_uuid):
    data_master.reload_if_changed()
    if not org_uuid:
        return [], None
    opciones = data_master.mapa_locs_por_org.get(org_uuid, [])
    default = opciones[0]["value"] if opciones else None
    return opciones, default


@app.callback(
    Output("org-branding-store", "data"),
    Output("org-brand-style", "children"),
    Output("sidebar-logo-img", "src"),
    Output("sidebar-accent-bar", "style"),
    Input("drop-org", "value"),
)
def aplicar_branding_org(org_id):
    import os

    from src.core.org_branding import OrgBranding, branding_css, get_org_branding

    b: OrgBranding = get_org_branding(org_id)

    # Ruta absoluta del asset para comprobar existencia
    _assets_root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "assets",
    )
    logo_filename = b.logo_asset.removeprefix("/assets/")
    logo_src = (
        b.logo_asset
        if os.path.exists(os.path.join(_assets_root, logo_filename))
        else "/assets/logo.png"
    )

    accent_style = {
        "width": "3px",
        "height": "18px",
        "backgroundColor": b.primary,
        "borderRadius": "2px",
        "flexShrink": 0,
    }
    return (
        {"org_id": b.org_id, "primary": b.primary, "secondary": b.secondary},
        branding_css(b),
        logo_src,
        accent_style,
    )


def _funnel_key(z):
    tipo = z.get("tipo", "").lower()
    nombre = z.get("label", "").lower()
    if tipo == "entry_zone" or "calle" in nombre or "exterior" in nombre:
        return 0
    if tipo == "end_zone":
        return 3
    if tipo == "last_zone" or "caja" in nombre:
        return 2
    return 1  # tienda / interior / resto


@app.callback(
    [Output("radar-drop-zonas", "options"), Output("radar-drop-zonas", "value")],
    [Input("drop-locs", "value")],
)
def auto_fill_zonas(locs):
    data_master.reload_if_changed()
    if not locs:
        return [], []
    if isinstance(locs, str):
        locs = [locs]
    opts_bi = []
    vistos_bi = set()

    for loc in locs:
        for z in data_master.mapa_zonas_por_loc.get(loc, []):
            nombre = z["value"]
            if nombre not in vistos_bi and (not z.get("padre_uuid") or z.get("funnel_step")):
                opts_bi.append(z)
                vistos_bi.add(nombre)

    opts_bi.sort(key=_funnel_key)
    vals_bi = [z["value"] for z in opts_bi]
    return opts_bi, vals_bi


def _build_child_section(locs, parent_name, seen_parents: set) -> list:
    """Recursively build child zone selector blocks for parent_name."""
    if parent_name in seen_parents:
        return []
    seen_parents.add(parent_name)

    child_zones = []
    seen_vals: set = set()
    for loc in locs or []:
        for z in data_master.mapa_hijos_por_zona.get(loc, {}).get(parent_name, []):
            if z["value"] not in seen_vals:
                child_zones.append(z)
                seen_vals.add(z["value"])
    if not child_zones:
        return []

    blocks = [
        html.Div(
            [
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
            ],
            className="ms-3 mb-3 border-start border-2 border-primary ps-3",
        )
    ]
    for z in child_zones:
        blocks.extend(_build_child_section(locs, z["value"], seen_parents))
    return blocks


@app.callback(
    Output("radar-child-zones-wrapper", "children"),
    [Input("drop-locs", "value"), Input("radar-drop-zonas", "value")],
)
def render_child_zone_selectors(locs, selected_parents):
    data_master.reload_if_changed()
    if not locs or not selected_parents:
        return []
    if isinstance(locs, str):
        locs = [locs]
    children_ui = []
    seen_parents: set = set()
    for parent_name in selected_parents:
        children_ui.extend(_build_child_section(locs, parent_name, seen_parents))
    return children_ui


@app.callback(
    Output("zonas-activas-combined", "data"),
    [
        Input("radar-drop-zonas", "value"),
        Input({"type": "child-zone-checklist", "index": ALL}, "value"),
    ],
)
def combine_zones(parent_zones, child_zones_all):
    combined = list(parent_zones or [])
    for child_list in child_zones_all or []:
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
