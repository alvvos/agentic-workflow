from datetime import datetime, timedelta
from dash import Output, Input, html
from src.core.config import app
from src.core.data_master import mapa_tiendas


@app.callback(
    Output("export-resumen-filtros", "children"),
    Input("drop-locs", "value"), Input("tipo-fecha", "value"),
    Input("date-rango", "start_date"), Input("date-rango", "end_date"), Input("date-dia", "date"),
)
def actualizar_resumen_exportacion(locs, t_f, sd, ed, dia):
    hoy = datetime.today().date()
    if t_f == "ayer":
        start = end = hoy - timedelta(days=1)
    elif t_f == "7d_rel":
        start, end = hoy - timedelta(days=7), hoy - timedelta(days=1)
    elif t_f == "28d_rel":
        start, end = hoy - timedelta(days=28), hoy - timedelta(days=1)
    elif t_f == "dia" and dia:
        start = end = datetime.fromisoformat(dia).date()
    elif t_f == "rango" and sd and ed:
        start = datetime.fromisoformat(sd).date()
        end = datetime.fromisoformat(ed).date()
    else:
        start = end = hoy - timedelta(days=1)

    n_meses = max(1, round((end - start).days / 30))
    n_locs = len(locs) if locs else 0
    slides_est = 2 + n_meses * n_locs * 4

    ubi_labels = []
    for loc_uuid in (locs or []):
        nombre = mapa_tiendas.get(loc_uuid, loc_uuid)
        ubi_labels.append(nombre)

    def _fila(icono, etiqueta, valor, color="text-dark"):
        return html.Div([
            html.I(className=f"{icono} me-2 text-muted", style={"width": "1rem"}),
            html.Span(etiqueta, className="text-muted small me-2"),
            html.Span(valor, className=f"fw-bold small {color}"),
        ], className="mb-2")

    return html.Div([
        _fila("fas fa-calendar-alt", "Periodo:",
              f"{start.strftime('%d/%m/%Y')} — {end.strftime('%d/%m/%Y')}",
              "text-primary"),
        _fila("fas fa-map-marker-alt", "Ubicaciones:",
              ", ".join(ubi_labels) if ubi_labels else "Ninguna seleccionada",
              "text-dark" if ubi_labels else "text-danger"),
        _fila("fas fa-layer-group", "Meses en el periodo:", str(n_meses)),
        _fila("fas fa-clone", "Diapositivas estimadas:", f"~{slides_est}"),
    ])
