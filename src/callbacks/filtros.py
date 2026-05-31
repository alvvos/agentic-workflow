from dash import Output, Input, no_update
from src.core.config import app
from src.core import data_master


@app.callback(Output("sidebar-periodo-wrapper", "style"), Input("tabs-panel", "value"))
def toggle_periodo_sidebar(tab):
    if tab in ('tab-ejecutivo', 'tab-ml', 'tab-admin'):
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
    return opciones, [opc['value'] for opc in opciones]


@app.callback(
    [Output("radar-drop-zonas", "options"), Output("radar-drop-zonas", "value"),
     Output("ejecutivo-drop-zonas", "options"), Output("ejecutivo-drop-zonas", "value")],
    [Input("drop-locs", "value")]
)
def auto_fill_zonas(locs):
    data_master.reload_if_changed()
    if not locs:
        return [], [], [], []
    opts_bi, vals_bi, opts_exe, vals_exe = [], [], [], []
    vistos_bi, vistos_exe = set(), set()

    for l in locs:
        for z in data_master.mapa_zonas_por_loc.get(l, []):
            nombre = z['value']
            tipo = z.get('tipo', '').lower()

            if nombre not in vistos_bi:
                opts_bi.append(z)
                vistos_bi.add(nombre)
                if tipo != 'end_zone':
                    vals_bi.append(nombre)

            if tipo == 'last_zone' and nombre not in vistos_exe:
                opts_exe.append(z)
                vistos_exe.add(nombre)
                vals_exe.append(nombre)

    return opts_bi, vals_bi, opts_exe, vals_exe


# Refresca las opciones del dropdown de orgs cuando el admin modifica el árbol.
# Solo se ejecuta en sesiones admin (admin-crud-signal solo existe en el DOM admin).
@app.callback(
    Output("drop-org", "options"),
    Input("admin-crud-signal", "data"),
    prevent_initial_call=True,
)
def refresh_org_options(signal):
    data_master.reload_if_changed()
    return list(data_master.opciones_orgs)
