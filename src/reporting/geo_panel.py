"""
Panel geoespacial Esri — Panel PM.
Responde a: ¿Qué potencial tiene esta ubicación y a qué competencia se enfrenta?

Estructura:
  • Header         — gradiente azul con nombre y estado Esri
  • Tarjetas Esri  — una por dimensión (captación / transporte / competencia /
                     socioeconómico / movilidad), badge semáforo, detalle 1 línea
  • Strip de clima — temperatura + lluvia + efecto sobre afluencia
  • Captación      — barras horizontales por isócrona (xs=12, lg=5)
  • Mapa de alcance — isócronas B&N + competidores (xs=12, lg=7)
"""
import json
import math
import random
from pathlib import Path

import plotly.graph_objects as go
from dash import dcc, html
import dash_bootstrap_components as dbc

_C_PRIMARY = "#0052CC"
_C_DARK    = "#2c3e50"
_C_MUTED   = "#6c757d"
_C_GRID    = "#f2f2f2"
_C_GREEN   = "#28A745"
_C_AMBER   = "#f39c12"
_C_RED     = "#DC3545"
_C_TEAL    = "#17a2b8"
_C_PURPLE  = "#8e44ad"

_FONT    = dict(family="Arial, sans-serif")
_CFG     = {"displayModeBar": False, "responsive": True}
_H_CHART = "400px"

_REF_RENTA = 25_000
_UBIC_PATH = Path(__file__).parent.parent / "data" / "todas_las_ubicaciones.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(val, lo, hi):
    if val is None:
        return 0.0
    return max(0.0, min(1.0, (val - lo) / (hi - lo)))


def _isochrone(lat, lon, r_m, seed=0, n=90):
    """
    Approximate walking isochrone with organic boundary.
    Multi-frequency noise simulates how real catchment areas follow street grids —
    irregular, with concavities where blocks are large and extensions along avenues.
    """
    rng = random.Random(seed + int(r_m))
    # Pre-compute noise phases so the shape is deterministic per (location, radius)
    phases = [rng.uniform(0, 2 * math.pi) for _ in range(5)]
    pts_lat, pts_lon = [], []
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        noise = (
            0.16 * math.sin(3  * a + phases[0]) +
            0.10 * math.sin(5  * a + phases[1]) +
            0.07 * math.cos(9  * a + phases[2]) +
            0.04 * math.sin(14 * a + phases[3]) +
            0.03 * math.cos(19 * a + phases[4])
        )
        r = r_m * max(0.52, 1.0 + noise)
        pts_lat.append(lat + (r * math.cos(a)) / 111_320)
        pts_lon.append(lon + (r * math.sin(a)) / (111_320 * math.cos(math.radians(lat))))
    return pts_lat, pts_lon


def _info_ubicacion(uuid):
    """Returns (nombre, lat, lon)."""
    try:
        with open(_UBIC_PATH, encoding="utf-8") as f:
            datos = json.load(f)
        for org in datos:
            for loc in org.get("locations", []):
                if loc.get("uuid") == uuid:
                    nombre = loc.get("name", uuid[:8])
                    lat = loc.get("lat") or loc.get("latitude")
                    lon = loc.get("lon") or loc.get("longitude")
                    if lat and lon:
                        return nombre, float(lat), float(lon)
                    return nombre, None, None
    except Exception:
        pass
    return uuid[:8], None, None


def _mock_competitors(lat, lon, n, dist_nearest, seed):
    """
    Place mock competitors along street-grid directions (8 compass points + small deviation).
    This avoids purely random angular placement that can land competitors in the sea
    for coastal locations.
    """
    rng = random.Random(seed)
    compass = [k * math.pi / 4 for k in range(8)]
    pts = []
    for i in range(max(n, 1)):
        dist  = int(dist_nearest) if i == 0 else rng.randint(int(dist_nearest or 80), 480)
        angle = rng.choice(compass) + rng.gauss(0, 0.18)
        pts.append((
            lat + (dist * math.cos(angle)) / 111_320,
            lon + (dist * math.sin(angle)) / (111_320 * math.cos(math.radians(lat))),
            dist,
        ))
    return pts


def _semaforo_color(val, umbral_bien, umbral_mal, invert=False):
    if val is None:
        return _C_MUTED
    if not invert:
        return _C_GREEN if val >= umbral_bien else (_C_RED if val <= umbral_mal else _C_AMBER)
    return _C_GREEN if val <= umbral_bien else (_C_RED if val >= umbral_mal else _C_AMBER)


# ---------------------------------------------------------------------------
# 1. Metric cards — one per Esri dimension
# ---------------------------------------------------------------------------

def _build_metric_cards(vals):
    """
    Returns a list of card dicts, one per Esri dimension with data available.
    Keys: icon, label, main_val, unit, badge_txt, badge_col, border_color,
          funnel (list of (val_str, label) or None), detail (str or None)
    """
    cards = []

    # ── Captación peatonal ─────────────────────────────────────────────
    pob5  = vals.get("poblacion_5min")
    pob10 = vals.get("poblacion_10min")
    pob15 = vals.get("poblacion_15min")
    if pob5 is not None:
        nivel     = "Potencial alto"  if pob5 > 5_000 else ("Potencial medio" if pob5 > 2_000 else "Potencial bajo")
        badge_col = "success"         if pob5 > 5_000 else ("warning"         if pob5 > 2_000 else "danger")
        funnel    = [(f"{pob5:,.0f}", "5 min")]
        if pob10: funnel.append((f"{pob10:,.0f}", "10 min"))
        if pob15: funnel.append((f"{pob15:,.0f}", "15 min"))
        cards.append(dict(
            icon="fas fa-walking", label="Captación peatonal",
            main_val=f"{pob5:,.0f}", unit="hab. a 5 min",
            badge_txt=nivel, badge_col=badge_col,
            border_color=_C_PRIMARY, funnel=funnel, detail=None,
        ))

    # ── Transporte público ────────────────────────────────────────────
    dist_t = vals.get("dist_transporte_min_m")
    if dist_t is not None:
        if dist_t < 150:
            nivel, badge_col = "Excelente", "success"
            detail = "Capta el tráfico de la parada directamente"
        elif dist_t < 400:
            nivel, badge_col = "Adecuado", "warning"
            detail = "Visitas de conveniencia desde zonas no peatonales"
        else:
            nivel, badge_col = "Limitado", "danger"
            detail = "Mayor dependencia del vehículo privado"
        cards.append(dict(
            icon="fas fa-bus", label="Transporte público",
            main_val=f"{dist_t:,.0f} m", unit="al nodo más cercano",
            badge_txt=nivel, badge_col=badge_col,
            border_color=_C_TEAL, funnel=None, detail=detail,
        ))

    # ── Competencia directa ───────────────────────────────────────────
    n_comp = vals.get("n_competidores_500m")
    dist_c = vals.get("dist_competidor_cercano_m")
    if n_comp is not None:
        if n_comp == 0:
            nivel, badge_col = "Sin competencia", "success"
            main_val, unit, detail = "0", "competidores en 500 m", "Posición de monopolio local"
        else:
            nivel     = "Alta presión" if n_comp >= 5 else ("Moderada" if n_comp >= 2 else "Baja")
            badge_col = "danger"       if n_comp >= 5 else ("warning"  if n_comp >= 2 else "success")
            main_val  = str(int(n_comp))
            unit      = f"competidor{'es' if n_comp != 1 else ''} en 500 m"
            detail    = f"El más cercano a {dist_c:,.0f} m" if dist_c else None
        cards.append(dict(
            icon="fas fa-store-alt", label="Competencia directa",
            main_val=main_val, unit=unit,
            badge_txt=nivel, badge_col=badge_col,
            border_color=_C_RED, funnel=None, detail=detail,
        ))

    # ── Perfil socioeconómico ─────────────────────────────────────────
    renta  = vals.get("renta_media_cp")
    pob_cp = vals.get("poblacion_cp")
    if renta is not None:
        pct       = (renta - _REF_RENTA) / _REF_RENTA * 100
        nivel     = "Sobre media" if pct > 10 else ("En la media" if pct > -10 else "Bajo la media")
        badge_col = "success"     if pct > 10 else ("warning"     if pct > -10 else "danger")
        signo     = f"+{pct:.0f}%" if pct >= 0 else f"{pct:.0f}%"
        detail    = f"{signo} vs media nacional"
        if pob_cp:
            detail += f" · {pob_cp:,.0f} hab. en el CP"
        cards.append(dict(
            icon="fas fa-euro-sign", label="Renta media CP",
            main_val=f"{renta:,.0f} €/año", unit="renta anual bruta",
            badge_txt=nivel, badge_col=badge_col,
            border_color=_C_PURPLE, funnel=None, detail=detail,
        ))

    # ── Movilidad peatonal ────────────────────────────────────────────
    mob  = vals.get("indice_movilidad_peatonal")
    dens = vals.get("densidad_comercial_score")
    if mob is not None:
        nivel     = "Alta" if mob >= 0.7 else ("Media" if mob >= 0.4 else "Baja")
        badge_col = "success" if mob >= 0.7 else ("warning" if mob >= 0.4 else "danger")
        detail    = None
        if dens is not None:
            dens_lbl = "alta" if dens > 0.7 else ("media" if dens > 0.35 else "baja")
            detail   = f"Densidad comercial {dens_lbl} · {dens:.2f}/1.00"
        cards.append(dict(
            icon="fas fa-shoe-prints", label="Movilidad peatonal",
            main_val=f"{mob:.2f}", unit="índice 0–1",
            badge_txt=nivel, badge_col=badge_col,
            border_color=_C_GREEN, funnel=None, detail=detail,
        ))

    return cards


def _build_clima_card(clima):
    """Climate as a regular grid card — same structure as _build_metric_cards entries."""
    if not clima:
        return None
    cv      = list(clima.values())
    tmaxes  = [v["tmax"]   for v in cv if v.get("tmax")   is not None]
    precips = [v["precip"] for v in cv if v.get("precip") is not None]
    if not tmaxes:
        return None

    avg_tmax   = sum(tmaxes) / len(tmaxes)
    n_lluvia   = sum(1 for p in precips if p > 1.0) if precips else 0
    n_dias     = len(precips) if precips else 0
    pct_lluvia = n_lluvia / n_dias if n_dias else 0

    if avg_tmax > 28:
        nivel, badge_col, icon = "Calor extremo", "danger",    "fas fa-sun"
    elif avg_tmax > 20:
        nivel, badge_col, icon = "Templado",      "success",   "fas fa-cloud-sun"
    elif avg_tmax > 13:
        nivel, badge_col, icon = "Fresco",        "info",      "fas fa-cloud"
    else:
        nivel, badge_col, icon = "Frío",          "secondary", "fas fa-snowflake"

    lluvia_txt = f"{n_lluvia} de {n_dias} días con lluvia ({pct_lluvia * 100:.0f}%)"

    return dict(
        icon=icon, label="Clima del período",
        main_val=f"{avg_tmax:.1f}°C", unit="temperatura máxima media",
        badge_txt=nivel, badge_col=badge_col,
        border_color=_C_TEAL, funnel=None, detail=lluvia_txt,
    )


def _render_insight_cards(vals, clima=None):
    cards_data = _build_metric_cards(vals)

    # Climate integrates as a regular card so the grid stays uniform
    if clima:
        cc = _build_clima_card(clima)
        if cc:
            cards_data.append(cc)

    if not cards_data:
        return html.Div()

    cols = []
    for c in cards_data:
        # Funnel de isócronas (solo captación)
        if c["funnel"] and len(c["funnel"]) > 1:
            nodes = []
            for i, (v, lbl) in enumerate(c["funnel"]):
                nodes.append(html.Div([
                    html.Div(v,   style={"fontWeight": "700", "fontSize": "0.88rem", "color": _C_DARK}),
                    html.Div(lbl, style={"fontSize": "0.62rem", "color": _C_MUTED, "textAlign": "center"}),
                ], style={"textAlign": "center"}))
                if i < len(c["funnel"]) - 1:
                    nodes.append(html.Span("→", style={
                        "color": _C_MUTED, "fontSize": "0.75rem",
                        "alignSelf": "center", "margin": "0 4px",
                    }))
            value_block = html.Div(
                className="d-flex align-items-center flex-wrap mt-2 mb-1",
                children=nodes,
            )
        else:
            value_block = html.Div([
                html.Div(c["main_val"],
                         style={"fontSize": "1.28rem", "fontWeight": "700",
                                "color": _C_DARK, "lineHeight": "1.2", "marginTop": "6px"}),
                html.Div(c["unit"],
                         style={"fontSize": "0.67rem", "color": _C_MUTED, "marginBottom": "2px"}),
            ])

        detail_el = html.Div(
            c["detail"],
            style={"fontSize": "0.70rem", "color": _C_MUTED, "marginTop": "4px",
                   "borderTop": "1px solid #f0f0f0", "paddingTop": "4px"},
        ) if c["detail"] else html.Span()

        card = dbc.Card(
            dbc.CardBody([
                html.Div(className="d-flex justify-content-between align-items-center", children=[
                    html.Div([
                        html.I(className=f"{c['icon']} me-1",
                               style={"color": c["border_color"], "fontSize": "0.72rem"}),
                        html.Span(c["label"], style={
                            "fontSize": "0.65rem", "color": _C_MUTED,
                            "textTransform": "uppercase", "letterSpacing": "0.4px",
                            "fontWeight": "600",
                        }),
                    ]),
                    dbc.Badge(c["badge_txt"], color=c["badge_col"], pill=True,
                              style={"fontSize": "0.76rem"}),
                ]),
                value_block,
                detail_el,
            ], className="p-3"),
            className="border-0 shadow-sm rounded-4 h-100",
            style={"borderLeft": f"4px solid {c['border_color']}"},
        )
        cols.append(dbc.Col(card, xs=12, sm=6, lg=4, className="mb-3"))

    return html.Div(
        dbc.Row(cols, className="g-3 mb-1"),
        className="mb-3",
    )


def _render_clima_strip(clima):
    if not clima:
        return None
    cv     = list(clima.values())
    tmaxes = [v["tmax"]   for v in cv if v.get("tmax")   is not None]
    precips= [v["precip"] for v in cv if v.get("precip") is not None]
    if not tmaxes:
        return None

    avg_tmax   = sum(tmaxes) / len(tmaxes)
    n_lluvia   = sum(1 for p in precips if p > 1.0) if precips else 0
    n_dias     = len(precips) if precips else 0
    total_prec = sum(precips) if precips else 0
    pct_lluvia = n_lluvia / n_dias if n_dias else 0

    if avg_tmax > 28:
        temp_badge, temp_col, t_icon = "Calor extremo", "danger",    "fas fa-sun"
    elif avg_tmax > 20:
        temp_badge, temp_col, t_icon = "Templado",      "success",   "fas fa-cloud-sun"
    elif avg_tmax > 13:
        temp_badge, temp_col, t_icon = "Fresco",        "info",      "fas fa-cloud"
    else:
        temp_badge, temp_col, t_icon = "Frío",          "secondary", "fas fa-snowflake"

    rain_col = "danger" if pct_lluvia > 0.35 else ("warning" if pct_lluvia > 0.15 else "success")
    efecto   = (
        "Afluencia favorecida"      if avg_tmax <= 28 and pct_lluvia <= 0.15 else
        "Impacto negativo probable" if avg_tmax > 33  or  pct_lluvia > 0.35  else
        "Impacto moderado"
    )
    efecto_col = "success" if "favorecida" in efecto else ("danger" if "negativo" in efecto else "warning")

    def _stat(icon_cls, main, sub, badge, col):
        return html.Div(className="d-flex align-items-center gap-2 py-1", children=[
            html.I(className=icon_cls,
                   style={"color": _C_TEAL, "fontSize": "1rem", "width": "20px"}),
            html.Div([
                html.Span(main, style={"fontWeight": "700", "fontSize": "0.88rem", "color": _C_DARK}),
                html.Span(f" {sub}", style={"fontSize": "0.72rem", "color": _C_MUTED}),
            ]),
            dbc.Badge(badge, color=col, pill=True, className="ms-auto",
                      style={"fontSize": "0.76rem"}),
        ])

    return dbc.Card(
        dbc.CardBody(
            dbc.Row([
                dbc.Col(
                    _stat(t_icon, f"{avg_tmax:.1f}°C", "temp. máx. media", temp_badge, temp_col),
                    xs=12, sm=4, className="mb-2 mb-sm-0",
                ),
                dbc.Col(
                    _stat("fas fa-cloud-rain",
                          f"{total_prec:.0f} mm",
                          f"· {n_lluvia} de {n_dias} días con lluvia",
                          f"{pct_lluvia*100:.0f}% días con lluvia",
                          rain_col),
                    xs=12, sm=4, className="mb-2 mb-sm-0",
                ),
                dbc.Col(
                    _stat("fas fa-chart-line", efecto, "sobre afluencia peatonal", efecto, efecto_col),
                    xs=12, sm=4,
                ),
            ], className="align-items-center g-2"),
            className="px-4 py-3",
        ),
        className="border-0 shadow-sm rounded-4 mb-3",
        style={"borderLeft": f"4px solid {_C_TEAL}"},
    )


# ---------------------------------------------------------------------------
# 2. Gráfico de captación — barras con etiquetas fuera para evitar recorte
# ---------------------------------------------------------------------------

def _fig_captacion(vals):
    specs = [
        ("5 min",  vals.get("poblacion_5min"),  1.00),
        ("10 min", vals.get("poblacion_10min"), 0.65),
        ("15 min", vals.get("poblacion_15min"), 0.35),
    ]
    specs = [(l, v, op) for l, v, op in specs if v is not None]
    if not specs:
        return None

    labels = [s[0] for s in specs]
    values = [s[1] for s in specs]
    colors = [f"rgba(0,82,204,{s[2]})" for s in specs]
    max_v  = max(values)

    fig = go.Figure(go.Bar(
        y=labels,
        x=values,
        orientation="h",
        marker=dict(
            color=colors,
            line=dict(color="white", width=2),
        ),
        text=[f"{v:,.0f} hab." for v in values],
        textposition="outside",
        constraintext="none",
        textfont=dict(size=11, color=_C_DARK, **_FONT),
        hovertemplate="%{y} a pie: <b>%{x:,.0f}</b> personas accesibles<extra></extra>",
    ))

    fig.update_layout(
        xaxis=dict(
            title=dict(text="Habitantes accesibles", font=dict(size=11, color=_C_MUTED, **_FONT)),
            showgrid=True, gridcolor=_C_GRID,
            tickformat=",", tickfont=dict(size=10, **_FONT),
            range=[0, max_v * 1.35],
        ),
        yaxis=dict(
            showgrid=False,
            tickfont=dict(size=12, color=_C_DARK, **_FONT),
            autorange="reversed",
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        margin=dict(t=16, b=44, l=70, r=16),
        hovermode="y unified",
        bargap=0.40,
    )
    return fig


# ---------------------------------------------------------------------------
# 3. Mapa de alcance — estilo blanco y negro (carto-positron)
# ---------------------------------------------------------------------------

def _fig_mapa(vals, lat, lon, uuid):
    if lat is None or lon is None:
        return None

    n_comp    = int(vals.get("n_competidores_500m") or 0)
    dist_near = vals.get("dist_competidor_cercano_m") or 200
    pob5      = vals.get("poblacion_5min")

    iso_seed = int(uuid.replace("-", ""), 16) % (2 ** 31)
    fig = go.Figure()

    # Each ring has its own colour: green (5 min) → amber (10 min) → blue (15 min)
    rings = [
        (1200, "rgba(0,82,204,0.07)",    "rgba(0,82,204,0.28)",    "15 min  ≈ 1.2 km"),
        (800,  "rgba(243,156,18,0.10)",  "rgba(243,156,18,0.42)",  "10 min  ≈ 800 m"),
        (400,  "rgba(40,167,69,0.15)",   "rgba(40,167,69,0.65)",   " 5 min  ≈ 400 m"),
    ]
    for r_m, fill_col, line_col, name in rings:
        lats_c, lons_c = _isochrone(lat, lon, r_m, seed=iso_seed)
        fig.add_trace(go.Scattermapbox(
            lat=lats_c, lon=lons_c, mode="lines",
            fill="toself",
            fillcolor=fill_col,
            line=dict(color=line_col, width=2),
            name=name, hoverinfo="skip",
        ))

    if n_comp > 0:
        seed  = int(uuid.replace("-", ""), 16) % (2 ** 31)
        comps = _mock_competitors(lat, lon, n_comp, dist_near, seed)
        fig.add_trace(go.Scattermapbox(
            lat=[c[0] for c in comps],
            lon=[c[1] for c in comps],
            mode="markers",
            marker=dict(size=11, color=_C_RED, opacity=0.85),
            name=f"Competidores ({n_comp})",
            customdata=[c[2] for c in comps],
            hovertemplate=(
                "<b>Competidor</b><br>"
                "a ~%{customdata:,.0f} m de la tienda"
                "<extra></extra>"
            ),
        ))

    store_tip = "<b>Tu ubicación</b>"
    if pob5:
        store_tip += f"<br>{pob5:,.0f} hab. en 5 min a pie"
    if n_comp:
        store_tip += f"<br>{n_comp} competidor{'es' if n_comp != 1 else ''} en 500 m"
    store_tip += "<extra></extra>"

    fig.add_trace(go.Scattermapbox(
        lat=[lat], lon=[lon], mode="markers",
        marker=dict(size=20, color=_C_PRIMARY),
        name="Ubicación",
        hovertemplate=store_tip,
    ))

    fig.update_layout(
        mapbox=dict(style="carto-positron", center=dict(lat=lat, lon=lon), zoom=14),
        margin=dict(t=0, b=0, l=0, r=0),
        showlegend=True,
        legend=dict(
            orientation="h", x=0.01, y=0.01,
            bgcolor="rgba(255,255,255,0.90)",
            bordercolor="#ddd", borderwidth=1,
            font=dict(size=11, color=_C_DARK, **_FONT),
        ),
        paper_bgcolor="white",
    )
    return fig


# ---------------------------------------------------------------------------
# Ensamblaje público
# ---------------------------------------------------------------------------

def generar_panel_geo_visual(location_uuid, vals, clima=None):
    activos = {k: v for k, v in vals.items() if v is not None}
    nombre, lat, lon = _info_ubicacion(location_uuid)

    # ── Header ───────────────────────────────────────────────────────────────
    header = dbc.Card(
        dbc.CardBody(dbc.Row([
            dbc.Col([
                html.P("CONTEXTO ESPACIAL", className="mb-1 text-white-50 text-uppercase fw-bold",
                       style={"fontSize": "0.61rem", "letterSpacing": "1px"}),
                html.H5(nombre, className="fw-bold mb-0 text-white"),
            ], xs=9),
            dbc.Col(
                html.Div(
                    dbc.Badge("Esri · datos disponibles", color="success", pill=True,
                              className="fs-6 px-3 py-2")
                    if activos else
                    dbc.Badge("Esri · pendiente", color="secondary", pill=True,
                              className="fs-6 px-3 py-2"),
                    className="d-flex justify-content-end align-items-center h-100",
                ),
                xs=3,
            ),
        ])),
        className="border-0 rounded-4 mb-4 shadow-sm",
        style={"background": "linear-gradient(135deg, #0052CC 0%, #003d99 100%)"},
    )

    if not activos:
        return html.Div([
            header,
            dbc.Card(
                dbc.CardBody(
                    html.P("Variables geoespaciales pendientes de integración con Esri.",
                           className="text-muted small mb-0"),
                ),
                className="border-0 shadow-sm rounded-4 mb-3 bg-white",
            ),
        ])

    # ── Tarjetas de métricas + clima ─────────────────────────────────────────
    insight_section = _render_insight_cards(activos, clima)

    # ── Charts ───────────────────────────────────────────────────────────────
    fig_cap  = _fig_captacion(activos)
    fig_mapa = _fig_mapa(activos, lat, lon, location_uuid)

    def _chart_card(fig, gid, height):
        return dbc.Card(
            dbc.CardBody(
                dcc.Graph(id=gid, figure=fig, config=_CFG,
                          style={"height": height}),
                className="p-2",
            ),
            className="border-0 shadow-sm rounded-4 h-100",
            style={"overflow": "visible"},
        )

    col_cap = dbc.Col(
        _chart_card(fig_cap, f"geo-cap-{location_uuid[:8]}", _H_CHART),
        xs=12, lg=5, className="mb-3",
    ) if fig_cap else None

    col_mapa = dbc.Col(
        _chart_card(fig_mapa, f"geo-map-{location_uuid[:8]}", _H_CHART),
        xs=12, lg=7, className="mb-3",
    ) if fig_mapa else None

    if col_cap and col_mapa:
        fila_graficos = dbc.Row([col_cap, col_mapa], className="g-3")
    elif col_mapa:
        fila_graficos = dbc.Row(dbc.Col(
            _chart_card(fig_mapa, f"geo-map-{location_uuid[:8]}", "480px"), xs=12,
        ))
    elif col_cap:
        fila_graficos = dbc.Row(dbc.Col(
            _chart_card(fig_cap, f"geo-cap-{location_uuid[:8]}", _H_CHART), xs=12,
        ))
    else:
        fila_graficos = html.Div()

    return html.Div([
        header,
        insight_section,
        fila_graficos,
    ])
