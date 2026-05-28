"""
Panel geoespacial Esri — Panel PM.
Responde a: ¿Qué potencial tiene esta ubicación y a qué competencia se enfrenta?

Secciones (todas auto-generadas desde geo_features.json):
  A. Alcance peatonal  — captación isócrona, mapa, pirámide de edad, estructura de hogar
  B. Capacidad económica — renta, salud financiera, gasto por categoría
  C. Comportamiento digital — canal online, presión omnicanal
  D. Entorno competitivo — transporte, competidores, movilidad (Phase 2)
"""
import json
import math
import random
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html
import dash_bootstrap_components as dbc
from src.data_processing.geo_enrichment import get_catchment_rings

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
_H_MID   = "340px"
_H_SM    = "280px"

_REF_RENTA      = 25_000
_REF_GASTO_ROPA = 1_200
_UBIC_PATH = Path(__file__).parent.parent / "data" / "todas_las_ubicaciones.json"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers genéricos
# ─────────────────────────────────────────────────────────────────────────────

def _norm(val, lo, hi):
    if val is None:
        return 0.0
    return max(0.0, min(1.0, (val - lo) / (hi - lo)))


def _pct_of(num, denom):
    """Safe percentage: num/denom*100, or None if inputs invalid."""
    if num is None or not denom:
        return None
    return num / denom * 100


def _fmt_pct(v, decimals=0):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}%"


def _fmt_eur(v, decimals=0):
    if v is None:
        return "—"
    if v >= 1_000:
        return f"{v:,.{decimals}f} €"
    return f"{v:.{decimals}f} €"


def _isochrone(lat, lon, r_m, seed=0, n=90):
    rng = random.Random(seed + int(r_m))
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
    try:
        with open(_UBIC_PATH, encoding="utf-8") as f:
            datos = json.load(f)
        for org in datos:
            for loc in org.get("locations", []):
                if loc.get("uuid") == uuid:
                    nombre = loc.get("name", uuid[:8])
                    lat = loc.get("lat") or loc.get("latitude")
                    lon = loc.get("lon") or loc.get("longitude")
                    return nombre, (float(lat) if lat else None), (float(lon) if lon else None)
    except Exception:
        pass
    return uuid[:8], None, None


def _mock_competitors(lat, lon, n, dist_nearest, seed):
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


# ─────────────────────────────────────────────────────────────────────────────
# Auto-insights — texto contextual por sección
# ─────────────────────────────────────────────────────────────────────────────

def _auto_insight_captacion(vals):
    pob5  = vals.get("poblacion_5min")
    pob10 = vals.get("poblacion_10min")
    pob15 = vals.get("poblacion_15min")
    if pob5 is None:
        return None
    if pob15 and pob15 > 0:
        pct = pob5 / pob15 * 100
        if pct < 15:
            coment = (f"Solo el {pct:.0f}% de esa masa vive a menos de 5 minutos, "
                      "la tienda depende del tráfico de paso del área ampliada.")
        else:
            coment = (f"El {pct:.0f}% de toda la masa accesible a 15 min vive a menos de 5 min: "
                      "concentración muy favorable para compra por impulso.")
    else:
        coment = ""
    bloque = f"{pob5:,.0f} personas viven a menos de 5 minutos de la tienda."
    if pob10 and pob15:
        bloque += f" A 10 min el área crece hasta {pob10:,.0f} y a 15 min alcanza {pob15:,.0f}."
    return f"{bloque} {coment}".strip()


def _auto_insight_edad(vals):
    p15 = vals.get("pob_15_19") or 0
    p20 = vals.get("pob_20_24") or 0
    p25 = vals.get("pob_25_29") or 0
    p30 = vals.get("pob_30_34") or 0
    p35 = vals.get("pob_35_39") or 0
    peak = p25 + p30
    total_15_39 = p15 + p20 + p25 + p30 + p35
    pob10 = vals.get("poblacion_10min")
    if not total_15_39:
        return None
    pct_target = total_15_39 / pob10 * 100 if pob10 else None
    pct_peak   = peak / total_15_39 * 100 if total_15_39 else 0
    txt = f"En 800 m hay {total_15_39:,.0f} personas entre 15 y 39 años (target Miniso)"
    if pct_target:
        txt += f", el {pct_target:.0f}% del total de {pob10:,.0f} hab. en esa área"
    txt += (f". La cohorte 25–34 (peak de gasto lifestyle) concentra el {pct_peak:.0f}% de ese grupo.")
    return txt


def _auto_insight_hogar(vals):
    nhog      = vals.get("n_hogares_total")
    tam       = vals.get("tamanio_medio_hogar")
    jovenes   = vals.get("hogares_jovenes_solos")   or 0
    parejas_j = vals.get("hogares_parejas_jovenes") or 0
    familias  = vals.get("hogares_familias_hijos")  or 0
    mono      = vals.get("hogares_monoparentales")  or 0
    if not nhog:
        return None
    n_target  = jovenes + parejas_j + familias
    pct       = n_target / nhog * 100 if nhog else 0
    txt = (f"Hay {nhog:,.0f} hogares en radio de 800 m")
    if tam:
        txt += f" (media {tam:.1f} personas/hogar)"
    txt += f". De ellos, {n_target:,.0f} ({pct:.0f}%) son jóvenes solos, parejas jóvenes o familias con hijos, los perfiles con mayor afinidad natural al concepto Miniso."
    if mono:
        pct_m = mono / nhog * 100
        txt += f" Las familias monoparentales ({mono:,.0f} hogares, {pct_m:.0f}%) también buscan valor por precio."
    return txt


def _auto_insight_renta(vals):
    renta      = vals.get("renta_hogar_anual")
    renta_m    = vals.get("renta_hogar_mensual")
    nhog       = vals.get("n_hogares_total")
    renta_alta = vals.get("hogares_renta_alta")
    renta_ma   = vals.get("hogares_renta_media_alta")
    if renta is None:
        return None
    pct = (renta - _REF_RENTA) / _REF_RENTA * 100
    calif = "por encima" if pct >= 0 else "por debajo"
    txt = (f"La renta media del hogar es {renta:,.0f} €/año")
    if renta_m:
        txt += f" ({renta_m:,.0f} €/mes)"
    txt += f", un {abs(pct):.0f}% {calif} de la media nacional."
    if nhog and nhog > 0 and renta_alta is not None:
        pct_alta = (renta_alta + (renta_ma or 0)) / nhog * 100
        txt += (f" El {pct_alta:.0f}% de los hogares supera los 2.122 €/mes, "
                f"hay poder adquisitivo real para compra discrecional habitual.")
    return txt


def _auto_insight_salud(vals):
    nhog      = vals.get("n_hogares_total")
    imprev    = vals.get("puede_afrontar_imprevistos_pct")
    facilidad = vals.get("llega_mes_con_facilidad_pct")
    pobreza   = vals.get("en_riesgo_pobreza_pct")
    if not nhog or imprev is None:
        return None
    pct_i = imprev / nhog * 100
    n_de_10 = round(pct_i / 10)
    txt = (f"{n_de_10} de cada 10 hogares pueden asumir un gasto inesperado sin entrar en apuros.")
    if pobreza:
        pct_p = pobreza / nhog * 100
        txt += f" Solo el {pct_p:.0f}% está en riesgo de pobreza."
    if pct_i > 65:
        txt += " La zona tiene estabilidad económica suficiente para sostener gasto en moda y ocio de forma habitual."
    else:
        txt += " La base económica es moderada; el precio y la propuesta de valor son factores decisivos para la conversión."
    return txt


def _auto_insight_gasto(vals):
    gasto_ropa = vals.get("gasto_ropa_calzado")
    gasto_pers = vals.get("gasto_cuidado_personal")
    gasto_ocio = vals.get("gasto_ocio_cultura")
    if gasto_ropa is None:
        return None
    pct  = (gasto_ropa - _REF_GASTO_ROPA) / _REF_GASTO_ROPA * 100
    dir_ = "un" if pct >= 0 else "un"
    verb = "más" if pct >= 0 else "menos"
    txt = (f"Los hogares del área gastan {gasto_ropa:,.0f} € al año en ropa y calzado, "
           f"un {abs(pct):.0f}% {verb} que la media nacional ({_REF_GASTO_ROPA:,.0f} €).")
    if gasto_pers:
        txt += (f" El gasto en cuidado personal suma {gasto_pers:,.0f} €/hogar, "
                "señal de predisposición a marcas de lifestyle y autocuidado, categorías directas de Miniso.")
    if gasto_ocio:
        txt += f" El ocio y la cultura absorben {gasto_ocio:,.0f} €/hogar, indicando disponibilidad para gasto no esencial."
    return txt


def _auto_insight_online(vals):
    nhog     = vals.get("n_hogares_total")
    puthint  = vals.get("pct_compras_online")
    propuspo = vals.get("online_ropa_deporte_pct")
    whelain  = vals.get("online_ultimo_mes_pct")
    if not nhog or puthint is None:
        return None
    pct_online = puthint / nhog * 100
    txt = f"El {pct_online:.0f}% de los hogares compra habitualmente por internet."
    if propuspo:
        pct_ropa = propuspo / nhog * 100
        txt += (f" De ellos, el {pct_ropa:.0f}% ya ha comprado ropa o deporte online, "
                "presión omnicanal directa sobre la categoría de Miniso.")
    if whelain:
        pct_mes = whelain / nhog * 100
        txt += (f" El {pct_mes:.0f}% realizó alguna compra online el último mes: "
                "son compradores activos con hábito consolidado, no ocasionales.")
    if pct_online > 60:
        txt += " La tienda física compite con Amazon y Zara.com por los mismos bolsillos."
    return txt


def _auto_insight_inmobiliario(vals):
    compra   = vals.get("precio_medio_piso_compra")
    alquiler = vals.get("precio_medio_piso_alquiler")
    if compra is None:
        return None
    if compra > 400_000:
        perfil = "zona de alto poder adquisitivo, con demanda solvente y disposición a pagar por calidad"
    elif compra > 200_000:
        perfil = "zona de clase media-alta consolidada"
    else:
        perfil = "zona de renta media, sensible al precio"
    txt = f"El precio medio de compra de piso es {compra/1000:.0f}k €."
    if alquiler:
        txt += f" El alquiler medio se sitúa en {alquiler:,.0f} €/mes."
    txt += f" Señal de {perfil}."
    return txt


# ─────────────────────────────────────────────────────────────────────────────
# Layout helpers
# ─────────────────────────────────────────────────────────────────────────────

def _section_header(icon_cls, title, subtitle=None):
    return html.Div([
        html.Div([
            html.I(className=f"{icon_cls} me-2", style={"color": _C_PRIMARY, "fontSize": "1.15rem"}),
            html.Span(title, style={"fontWeight": "700", "fontSize": "1.18rem", "color": _C_DARK}),
        ], className="d-flex align-items-center"),
        html.P(subtitle, style={"fontSize": "0.82rem", "color": _C_MUTED, "marginBottom": "0", "marginLeft": "1.9rem"})
        if subtitle else html.Span(),
    ], style={"marginBottom": "16px", "paddingBottom": "10px", "borderBottom": f"2px solid {_C_GRID}"})


def _insight_box(text):
    if not text:
        return html.Span()
    return html.Div(
        html.P([
            html.I(className="fas fa-lightbulb me-2",
                   style={"color": _C_AMBER, "fontSize": "0.85rem"}),
            text,
        ], className="mb-0",
           style={"fontSize": "0.88rem", "color": _C_DARK, "lineHeight": "1.65"}),
        style={
            "background": "#fffbf0",
            "border": "1px solid #ffe5a0",
            "borderLeft": f"4px solid {_C_AMBER}",
            "borderRadius": "8px",
            "padding": "10px 14px",
            "marginTop": "12px",
        },
    )


def _chart_card(fig, gid, height, title=None, insight=None):
    children = []
    if title:
        children.append(html.P(title, style={
            "fontSize": "0.65rem", "color": _C_MUTED,
            "textTransform": "uppercase", "letterSpacing": "0.5px",
            "fontWeight": "600", "marginBottom": "6px",
        }))
    children.append(dcc.Graph(id=gid, figure=fig, config=_CFG, style={"height": height}))
    if insight:
        children.append(_insight_box(insight))
    return dbc.Card(
        dbc.CardBody(children, className="p-3"),
        className="border-0 shadow-sm rounded-4 h-100",
        style={"overflow": "visible"},
    )


def _semaforo(val, umbral_bien, umbral_mal, invert=False):
    col = _semaforo_color(val, umbral_bien, umbral_mal, invert)
    name = (
        "Bueno" if col == _C_GREEN else
        ("Moderado" if col == _C_AMBER else
         ("Sin dato" if col == _C_MUTED else "Alerta"))
    )
    bmap = {_C_GREEN: "success", _C_AMBER: "warning", _C_RED: "danger", _C_MUTED: "secondary"}
    return name, bmap.get(col, "secondary")


# ─────────────────────────────────────────────────────────────────────────────
# Metric cards
# ─────────────────────────────────────────────────────────────────────────────

def _build_metric_cards(vals):
    cards = []
    nhog = vals.get("n_hogares_total")

    # ── Captación peatonal ────────────────────────────────────────────────────
    pob5  = vals.get("poblacion_5min")
    pob10 = vals.get("poblacion_10min")
    pob15 = vals.get("poblacion_15min")
    if pob5 is not None:
        nivel     = "Potencial alto"  if pob5 > 5_000 else ("Potencial medio" if pob5 > 2_000 else "Potencial bajo")
        badge_col = "success"         if pob5 > 5_000 else ("warning"         if pob5 > 2_000 else "danger")
        funnel = [(f"{pob5:,.0f}", "5 min")]
        if pob10: funnel.append((f"{pob10:,.0f}", "10 min"))
        if pob15: funnel.append((f"{pob15:,.0f}", "15 min"))
        cards.append(dict(
            icon="fas fa-walking", label="Captación peatonal",
            main_val=f"{pob5:,.0f}", unit="hab. a 5 min",
            badge_txt=nivel, badge_col=badge_col,
            border_color=_C_PRIMARY, funnel=funnel, detail=None,
        ))

    # ── Renta del hogar ───────────────────────────────────────────────────────
    renta_hogar = vals.get("renta_hogar_anual")
    renta_pc    = vals.get("renta_per_capita")
    renta_alta  = vals.get("hogares_renta_alta")
    renta_ma    = vals.get("hogares_renta_media_alta")
    if renta_hogar is not None:
        pct       = (renta_hogar - _REF_RENTA) / _REF_RENTA * 100
        nivel     = "Sobre media" if pct > 10 else ("En la media" if pct > -10 else "Bajo la media")
        badge_col = "success"     if pct > 10 else ("warning"     if pct > -10 else "danger")
        signo     = f"+{pct:.0f}%" if pct >= 0 else f"{pct:.0f}%"
        detail_parts = [f"{signo} vs media nacional (€{_REF_RENTA:,.0f})"]
        if renta_pc:
            detail_parts.append(f"{renta_pc:,.0f} €/cápita")
        if nhog and renta_alta is not None:
            pct_alta = (renta_alta + (renta_ma or 0)) / nhog * 100
            detail_parts.append(f"{pct_alta:.0f}% hog. renta media-alta+")
        cards.append(dict(
            icon="fas fa-euro-sign", label="Renta del hogar",
            main_val=f"{renta_hogar:,.0f} €", unit="renta anual media (800 m)",
            badge_txt=nivel, badge_col=badge_col,
            border_color=_C_PURPLE, funnel=None, detail=" · ".join(detail_parts),
        ))

    # ── Gasto ropa y calzado ──────────────────────────────────────────────────
    gasto_ropa = vals.get("gasto_ropa_calzado")
    gasto_pers = vals.get("gasto_cuidado_personal")
    if gasto_ropa is not None:
        pct       = (gasto_ropa - _REF_GASTO_ROPA) / _REF_GASTO_ROPA * 100
        nivel     = "Gasto alto"  if pct > 15 else ("Gasto medio" if pct > -15 else "Gasto bajo")
        badge_col = "success"     if pct > 15 else ("warning"     if pct > -15 else "danger")
        signo     = f"+{pct:.0f}%" if pct >= 0 else f"{pct:.0f}%"
        detail_parts = [f"{signo} vs ref. nacional (€{_REF_GASTO_ROPA:,.0f})"]
        if gasto_pers:
            detail_parts.append(f"cuidado personal {gasto_pers:,.0f} €/hog.")
        cards.append(dict(
            icon="fas fa-shopping-bag", label="Gasto ropa y calzado",
            main_val=f"{gasto_ropa:,.0f} €", unit="por hogar/año en 800 m",
            badge_txt=nivel, badge_col=badge_col,
            border_color=_C_GREEN, funnel=None, detail=" · ".join(detail_parts),
        ))

    # ── Perfil demográfico target ─────────────────────────────────────────────
    jovenes  = vals.get("hogares_jovenes_solos")
    familias = vals.get("hogares_familias_hijos")
    parejas_j = vals.get("hogares_parejas_jovenes")
    if any(v is not None for v in [jovenes, familias, parejas_j]):
        total_target = (jovenes or 0) + (familias or 0) + (parejas_j or 0)
        nivel     = "Target alto"  if total_target > 1_500 else ("Target medio" if total_target > 600 else "Target bajo")
        badge_col = "success"      if total_target > 1_500 else ("warning"      if total_target > 600 else "danger")
        parts = []
        if jovenes:   parts.append(f"{jovenes:,.0f} jóv. solos")
        if parejas_j: parts.append(f"{parejas_j:,.0f} parejas jóvenes")
        if familias:  parts.append(f"{familias:,.0f} familias c/ hijos")
        pct_str = f"{total_target/nhog*100:.0f}% del área" if nhog else None
        cards.append(dict(
            icon="fas fa-users", label="Hogares target Miniso",
            main_val=f"{total_target:,.0f}", unit=f"hogares target en 800 m{(' · ' + pct_str) if pct_str else ''}",
            badge_txt=nivel, badge_col=badge_col,
            border_color=_C_AMBER, funnel=None, detail=" · ".join(parts) if parts else None,
        ))

    # ── Salud financiera ──────────────────────────────────────────────────────
    imprev    = vals.get("puede_afrontar_imprevistos_pct")
    facilidad = vals.get("llega_mes_con_facilidad_pct")
    pobreza   = vals.get("en_riesgo_pobreza_pct")
    if nhog and imprev is not None:
        pct_i = imprev / nhog * 100
        pct_p = pobreza / nhog * 100 if pobreza and nhog else None
        nivel     = "Zona solvente" if pct_i > 70 else ("Zona estable" if pct_i > 50 else "Zona vulnerable")
        badge_col = "success"       if pct_i > 70 else ("warning"      if pct_i > 50 else "danger")
        detail_parts = [f"{pct_i:.0f}% puede afrontar imprevistos"]
        if pct_p is not None:
            detail_parts.append(f"{pct_p:.0f}% en riesgo de pobreza")
        if facilidad and nhog:
            pct_f = facilidad / nhog * 100
            detail_parts.append(f"{pct_f:.0f}% llega a fin de mes con facilidad")
        cards.append(dict(
            icon="fas fa-shield-alt", label="Salud financiera del hogar",
            main_val=f"{pct_i:.0f}%", unit="hogares con capacidad de afrontar imprevistos",
            badge_txt=nivel, badge_col=badge_col,
            border_color=_C_TEAL, funnel=None, detail=" · ".join(detail_parts),
        ))

    # ── Canal digital ─────────────────────────────────────────────────────────
    puthint  = vals.get("pct_compras_online")
    propuspo = vals.get("online_ropa_deporte_pct")
    if nhog and puthint is not None:
        pct_online = puthint / nhog * 100
        pct_ropa   = propuspo / nhog * 100 if propuspo and nhog else None
        nivel     = "Presión alta"   if pct_online > 70 else ("Presión media" if pct_online > 45 else "Presión baja")
        badge_col = "danger"         if pct_online > 70 else ("warning"       if pct_online > 45 else "success")
        detail_parts = [f"{pct_online:.0f}% compra online"]
        if pct_ropa:
            detail_parts.append(f"{pct_ropa:.0f}% compra ropa/deporte online")
        cards.append(dict(
            icon="fas fa-mobile-alt", label="Canal online (presión omnicanal)",
            main_val=f"{pct_online:.0f}%", unit="hogares que compran online en 800 m",
            badge_txt=nivel, badge_col=badge_col,
            border_color=_C_RED, funnel=None, detail=" · ".join(detail_parts),
        ))

    # ── Mercado inmobiliario ──────────────────────────────────────────────────
    compra   = vals.get("precio_medio_piso_compra")
    alquiler = vals.get("precio_medio_piso_alquiler")
    if compra is not None:
        nivel     = "Zona premium"  if compra > 400_000 else ("Zona media"   if compra > 200_000 else "Zona popular")
        badge_col = "success"       if compra > 400_000 else ("warning"      if compra > 200_000 else "secondary")
        detail_parts = []
        if alquiler:
            detail_parts.append(f"Alquiler medio {alquiler:,.0f} €/mes")
        cards.append(dict(
            icon="fas fa-building", label="Mercado inmobiliario",
            main_val=f"{compra/1000:.0f}k €", unit="precio medio de compra de piso",
            badge_txt=nivel, badge_col=badge_col,
            border_color=_C_PURPLE, funnel=None,
            detail=" · ".join(detail_parts) if detail_parts else None,
        ))

    # ── Transporte público (Phase 2) ──────────────────────────────────────────
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

    # ── Competencia directa (Phase 2) ─────────────────────────────────────────
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

    # ── Movilidad peatonal (Phase 2) ──────────────────────────────────────────
    mob  = vals.get("indice_movilidad_peatonal")
    dens = vals.get("densidad_comercial_score")
    if mob is not None:
        nivel     = "Alta" if mob >= 0.7 else ("Media" if mob >= 0.4 else "Baja")
        badge_col = "success" if mob >= 0.7 else ("warning" if mob >= 0.4 else "danger")
        detail = None
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


def _render_cards(cards_data, max_per_row=3):
    if not cards_data:
        return html.Div()
    cols = []
    for c in cards_data:
        if c["funnel"] and len(c["funnel"]) > 1:
            nodes = []
            for i, (v, lbl) in enumerate(c["funnel"]):
                nodes.append(html.Div([
                    html.Div(v, style={"fontWeight": "700", "fontSize": "0.88rem", "color": _C_DARK}),
                    html.Div(lbl, style={"fontSize": "0.62rem", "color": _C_MUTED, "textAlign": "center"}),
                ], style={"textAlign": "center"}))
                if i < len(c["funnel"]) - 1:
                    nodes.append(html.Span("→", style={
                        "color": _C_MUTED, "fontSize": "0.75rem",
                        "alignSelf": "center", "margin": "0 4px",
                    }))
            value_block = html.Div(className="d-flex align-items-center flex-wrap mt-2 mb-1", children=nodes)
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
        lg = 12 // max_per_row
        cols.append(dbc.Col(card, xs=12, sm=6, lg=lg, className="mb-3"))
    return dbc.Row(cols, className="g-3 mb-3")


# ─────────────────────────────────────────────────────────────────────────────
# Charts — Sección A: Alcance
# ─────────────────────────────────────────────────────────────────────────────

def _fig_captacion(vals):
    pob5, pob10, pob15 = vals.get("poblacion_5min"), vals.get("poblacion_10min"), vals.get("poblacion_15min")
    specs = []
    if pob5  is not None: specs.append(("0–5 min",   pob5,                                    "rgba(40,167,69,0.75)",  pob5))
    if pob10 is not None: specs.append(("5–10 min",  max(0, pob10 - (pob5 or 0)),              "rgba(243,156,18,0.80)", pob10))
    if pob15 is not None: specs.append(("10–15 min", max(0, pob15 - (pob10 or pob5 or 0)),    "rgba(0,82,204,0.70)",  pob15))
    if not specs:
        return None
    labels, values, colors, cum_vals = zip(*specs)
    max_v = max(values) if max(values) > 0 else 1
    fig = go.Figure(go.Bar(
        y=list(labels), x=list(values), orientation="h",
        marker=dict(color=list(colors), line=dict(color="white", width=2)),
        text=[f"{v:,.0f} hab." for v in values],
        textposition="outside", constraintext="none",
        textfont=dict(size=11, color=_C_DARK, **_FONT),
        customdata=list(cum_vals),
        hovertemplate="%{y}: <b>%{x:,.0f}</b> pers. en este anillo<br>Total hasta aquí: <b>%{customdata:,.0f}</b><extra></extra>",
    ))
    fig.update_layout(
        xaxis=dict(title=dict(text="Habitantes por anillo isócrono", font=dict(size=11, color=_C_MUTED, **_FONT)),
                   showgrid=True, gridcolor=_C_GRID, tickformat=",", tickfont=dict(size=10, **_FONT),
                   range=[0, max_v * 1.45]),
        yaxis=dict(showgrid=False, tickfont=dict(size=12, color=_C_DARK, **_FONT), autorange="reversed"),
        plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
        margin=dict(t=16, b=44, l=88, r=16), hovermode="y unified", bargap=0.40,
    )
    return fig


def _fig_piramide_edad(vals):
    """Pirámide completa con todas las franjas de edad (800 m). Target Miniso 15–39 resaltado."""

    def _sum(*keys):
        total = sum(vals.get(k) or 0 for k in keys)
        return total if total > 0 else None

    _C_NON_TARGET = "rgba(150,150,150,0.38)"
    _C_TARGET_EDGE = "rgba(0,82,204,0.48)"
    _C_TARGET_PEAK = _C_PRIMARY

    # (label, value, color, is_aggregate)
    specs = [
        ("10–14 años",  _sum("pob_0_4", "pob_5_9", "pob_10_14"),       _C_NON_TARGET),
        ("15–19 años",  vals.get("pob_15_19"),                          _C_TARGET_EDGE),
        ("20–24 años",  vals.get("pob_20_24"),                          _C_TARGET_EDGE),
        ("25–29 años ★",vals.get("pob_25_29"),                          _C_TARGET_PEAK),
        ("30–34 años ★",vals.get("pob_30_34"),                          _C_TARGET_PEAK),
        ("35–39 años",  vals.get("pob_35_39"),                          _C_TARGET_EDGE),
        ("40–54 años",  _sum("pob_40_44", "pob_45_49", "pob_50_54"),    _C_NON_TARGET),
        ("55–69 años",  _sum("pob_55_59", "pob_60_64", "pob_65_69"),    _C_NON_TARGET),
        ("70+ años",    _sum("pob_70_74", "pob_75_79", "pob_80_84", "pob_85_plus"), _C_NON_TARGET),
    ]

    labels, values, colors = [], [], []
    for label, v, color in specs:
        if v is not None:
            labels.append(label)
            values.append(v)
            colors.append(color)

    if not labels:
        return None

    max_v = max(values) if max(values) > 0 else 1
    fig = go.Figure(go.Bar(
        y=labels, x=values, orientation="h",
        marker=dict(color=colors, line=dict(color="white", width=1)),
        text=[f"{v:,.0f}" for v in values],
        textposition="outside", constraintext="none",
        textfont=dict(size=11, color=_C_DARK, **_FONT),
        hovertemplate="%{y}: <b>%{x:,.0f}</b> personas (800 m)<extra></extra>",
    ))
    fig.update_layout(
        xaxis=dict(title=dict(text="Personas en radio 800 m", font=dict(size=11, color=_C_MUTED, **_FONT)),
                   showgrid=True, gridcolor=_C_GRID, tickformat=",",
                   tickfont=dict(size=10, **_FONT), range=[0, max_v * 1.50]),
        yaxis=dict(showgrid=False, tickfont=dict(size=11, color=_C_DARK, **_FONT), autorange="reversed"),
        plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
        margin=dict(t=8, b=36, l=100, r=8), hovermode="y unified", bargap=0.28,
        annotations=[dict(
            text="★ peak gasto lifestyle · azul intenso = target Miniso (15–39)",
            x=1, y=-0.10, xref="paper", yref="paper",
            showarrow=False, font=dict(size=9, color=_C_MUTED), xanchor="right",
        )],
    )
    return fig


def _fig_estructura_hogar(vals):
    """Vertical bars — all household types at 800 m, sorted by value."""
    specs = [
        ("hogares_jovenes_solos",   "Solos\n<35",      _C_TEAL),
        ("hogares_parejas_jovenes", "Parejas\njóvenes", "rgba(0,82,204,0.65)"),
        ("hogares_parejas_adultas", "Parejas\nadultas", "rgba(0,82,204,0.40)"),
        ("hogares_familias_hijos",  "Familias\nc/hijos", _C_PRIMARY),
        ("hogares_monoparentales",  "Monoparen-\ntales", "rgba(243,156,18,0.75)"),
        ("hogares_renta_alta",      "Renta\nalta",      _C_PURPLE),
        ("hogares_renta_media_alta","Renta\nmedia-alta", "rgba(142,68,173,0.50)"),
    ]
    labels, values, colors = [], [], []
    for key, label, color in specs:
        v = vals.get(key)
        if v is not None:
            labels.append(label)
            values.append(v)
            colors.append(color)

    if not labels:
        return None

    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker=dict(color=colors, opacity=0.88, line=dict(color="white", width=2)),
        text=[f"{v:,.0f}" for v in values],
        textposition="outside",
        textfont=dict(size=11, color=_C_DARK, **_FONT),
        hovertemplate="%{x}: <b>%{y:,.0f}</b> hogares (800 m)<extra></extra>",
    ))
    fig.update_layout(
        xaxis=dict(showgrid=False, tickfont=dict(size=10, color=_C_DARK, **_FONT)),
        yaxis=dict(title=dict(text="Nº hogares en radio 800 m",
                              font=dict(size=11, color=_C_MUTED, **_FONT)),
                   showgrid=True, gridcolor=_C_GRID, tickformat=",",
                   tickfont=dict(size=10, **_FONT), range=[0, max(values) * 1.28]),
        plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
        margin=dict(t=24, b=8, l=16, r=16), bargap=0.38,
    )
    return fig


def _fig_mapa(vals, lat, lon, uuid):
    if lat is None or lon is None:
        return None
    n_comp    = int(vals.get("n_competidores_500m") or 0)
    dist_near = vals.get("dist_competidor_cercano_m") or 200
    pob5      = vals.get("poblacion_5min")
    iso_seed  = int(uuid.replace("-", ""), 16) % (2 ** 31)

    # Geometría real de Esri (returnGeometry=true) — índices [0]=400m, [1]=800m, [2]=1200m
    catchment = get_catchment_rings(uuid)
    usa_geo_real = catchment is not None and len(catchment) == 3

    fig = go.Figure()

    # Anillos: dibujamos del mayor al menor para que los menores queden encima
    ring_specs = [
        (2, "rgba(0,82,204,0.07)",   "rgba(0,82,204,0.28)",   "15 min a pie"),
        (1, "rgba(243,156,18,0.10)", "rgba(243,156,18,0.42)", "10 min a pie"),
        (0, "rgba(40,167,69,0.15)",  "rgba(40,167,69,0.65)",  " 5 min a pie"),
    ]
    radii = [400, 800, 1200]

    for idx, fill_col, line_col, name in ring_specs:
        if usa_geo_real and catchment[idx] is not None:
            lats_c = catchment[idx]["lats"]
            lons_c = catchment[idx]["lons"]
        else:
            lats_c, lons_c = _isochrone(lat, lon, radii[idx], seed=iso_seed)

        fig.add_trace(go.Scattermapbox(
            lat=lats_c, lon=lons_c, mode="lines",
            fill="toself", fillcolor=fill_col,
            line=dict(color=line_col, width=2),
            name=name, hoverinfo="skip",
        ))

    if n_comp > 0:
        comps = _mock_competitors(lat, lon, n_comp, dist_near, iso_seed)
        fig.add_trace(go.Scattermapbox(
            lat=[c[0] for c in comps], lon=[c[1] for c in comps],
            mode="markers",
            marker=dict(size=11, color=_C_RED, opacity=0.85),
            name=f"Competidores ({n_comp})",
            customdata=[c[2] for c in comps],
            hovertemplate="<b>Competidor</b><br>a ~%{customdata:,.0f} m<extra></extra>",
        ))

    store_tip = "<b>Tu ubicación</b>"
    if pob5:
        store_tip += f"<br>{pob5:,.0f} hab. en 5 min a pie"
    store_tip += "<extra></extra>"
    fig.add_trace(go.Scattermapbox(
        lat=[lat], lon=[lon], mode="markers",
        marker=dict(size=20, color=_C_PRIMARY),
        name="Ubicación", hovertemplate=store_tip,
    ))

    annotations = []
    if not usa_geo_real:
        annotations.append(dict(
            x=0.99, y=0.99, xref="paper", yref="paper",
            text="⚠ Isócronas aproximadas — sin geometría Esri",
            showarrow=False, font=dict(size=9, color="rgba(80,80,80,0.75)"),
            align="right", xanchor="right", yanchor="top",
            bgcolor="rgba(255,255,255,0.82)",
            bordercolor="rgba(0,0,0,0.12)", borderwidth=1, borderpad=4,
        ))

    fig.update_layout(
        mapbox=dict(style="carto-positron", center=dict(lat=lat, lon=lon), zoom=14),
        margin=dict(t=0, b=0, l=0, r=0),
        showlegend=True,
        legend=dict(orientation="h", x=0.01, y=0.01,
                    bgcolor="rgba(255,255,255,0.90)",
                    bordercolor="#ddd", borderwidth=1,
                    font=dict(size=11, color=_C_DARK, **_FONT)),
        paper_bgcolor="white",
        annotations=annotations,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Charts — Sección B: Capacidad económica
# ─────────────────────────────────────────────────────────────────────────────

def _fig_gasto_comparativo(vals):
    """Horizontal bars — all spending categories, catchment 800 m."""
    specs = [
        ("gasto_comunicaciones",    "Comunicaciones",         "rgba(23,162,184,0.45)"),
        ("gasto_transporte",        "Transporte",             "rgba(23,162,184,0.60)"),
        ("gasto_vacaciones",        "Vacaciones",             "rgba(142,68,173,0.45)"),
        ("gasto_alimentacion",      "Alimentación",           "rgba(40,167,69,0.65)"),
        ("gasto_restaurantes",      "Hoteles y restaurantes", "rgba(23,162,184,0.80)"),
        ("gasto_ocio_cultura",      "Ocio y cultura",         "rgba(142,68,173,0.70)"),
        ("gasto_cuidado_personal",  "Cuidado personal",       "rgba(243,156,18,0.75)"),
        ("gasto_calzado",           "Calzado",                "rgba(0,82,204,0.55)"),
        ("gasto_ropa",              "Ropa",                   "rgba(0,82,204,0.70)"),
        ("gasto_ropa_calzado",      "Ropa + calzado ★",       "rgba(0,82,204,0.92)"),
    ]
    labels, values, colors = [], [], []
    for key, label, color in specs:
        v = vals.get(key)
        if v is not None:
            labels.append(label)
            values.append(v)
            colors.append(color)

    if not labels:
        return None

    max_v = max(values)
    fig = go.Figure(go.Bar(
        y=labels, x=values, orientation="h",
        marker=dict(color=colors, line=dict(color="white", width=1)),
        text=[f"{v:,.0f} €/hog." for v in values],
        textposition="outside", constraintext="none",
        textfont=dict(size=10, color=_C_DARK, **_FONT),
        hovertemplate="%{y}: <b>%{x:,.0f} €</b>/hogar/año<extra></extra>",
    ))

    # Reference line for ropa+calzado benchmark
    fig.add_vline(
        x=_REF_GASTO_ROPA, line_dash="dash",
        line_color="rgba(220,53,69,0.5)", line_width=1.5,
        annotation_text=f"Ref. nacional ropa+calzado ({_REF_GASTO_ROPA:,.0f} €)",
        annotation_position="top right",
        annotation_font=dict(size=9, color=_C_RED),
    )

    fig.update_layout(
        xaxis=dict(title=dict(text="€ por hogar / año — radio 800 m",
                              font=dict(size=11, color=_C_MUTED, **_FONT)),
                   showgrid=True, gridcolor=_C_GRID, tickformat=",",
                   tickfont=dict(size=10, **_FONT), range=[0, max_v * 1.40]),
        yaxis=dict(showgrid=False, tickfont=dict(size=10, color=_C_DARK, **_FONT), autorange="reversed"),
        plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
        margin=dict(t=28, b=44, l=152, r=12), hovermode="y unified", bargap=0.30,
    )
    return fig


def _fig_salud_financiera(vals):
    """Horizontal bars showing financial health as % of households."""
    nhog = vals.get("n_hogares_total")
    if not nhog:
        return None

    specs = [
        ("puede_afrontar_imprevistos_pct", "Puede afrontar\nimprevistos", "rgba(40,167,69,0.80)"),
        ("llega_mes_con_facilidad_pct",    "Llega a fin de\nmes con facilidad", "rgba(23,162,184,0.75)"),
        ("en_riesgo_pobreza_pct",          "En riesgo\nde pobreza", "rgba(220,53,69,0.70)"),
    ]
    labels, values, colors = [], [], []
    for key, label, color in specs:
        v = vals.get(key)
        if v is not None:
            pct = v / nhog * 100
            labels.append(label)
            values.append(round(pct, 1))
            colors.append(color)

    if not labels:
        return None

    fig = go.Figure(go.Bar(
        y=labels, x=values, orientation="h",
        marker=dict(color=colors, line=dict(color="white", width=2)),
        text=[f"{v:.1f}%" for v in values],
        textposition="outside", constraintext="none",
        textfont=dict(size=13, color=_C_DARK, **_FONT),
        hovertemplate="%{y}: <b>%{x:.1f}%</b> de los hogares<extra></extra>",
    ))
    fig.update_layout(
        xaxis=dict(title=dict(text="% de hogares en 800 m",
                              font=dict(size=11, color=_C_MUTED, **_FONT)),
                   showgrid=True, gridcolor=_C_GRID,
                   ticksuffix="%", tickfont=dict(size=10, **_FONT),
                   range=[0, max(values) * 1.45]),
        yaxis=dict(showgrid=False, tickfont=dict(size=11, color=_C_DARK, **_FONT), autorange="reversed"),
        plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
        margin=dict(t=8, b=44, l=138, r=8), hovermode="y unified", bargap=0.38,
    )
    return fig


def _fig_inmobiliario(vals):
    """Property prices — compra y alquiler as simple KPI bars."""
    compra   = vals.get("precio_medio_piso_compra")
    alquiler = vals.get("precio_medio_piso_alquiler")
    if compra is None:
        return None

    labels, values, colors = [], [], []
    if compra:
        labels.append("Precio compra\n(€/piso)")
        values.append(compra)
        colors.append(_C_PURPLE)
    if alquiler:
        labels.append("Alquiler medio\n(€/mes)")
        values.append(alquiler * 100)  # scale for visibility — annotated separately
        colors.append("rgba(142,68,173,0.50)")

    # Simple horizontal bars — compra only since scales differ
    fig = go.Figure()
    if compra:
        fig.add_trace(go.Indicator(
            mode="number+delta",
            value=compra,
            number={"prefix": "€", "valueformat": ",.0f",
                    "font": {"size": 36, "color": _C_DARK, **_FONT}},
            title={"text": "Precio medio piso compra",
                   "font": {"size": 12, "color": _C_MUTED, **_FONT}},
            domain={"x": [0, 0.5], "y": [0.45, 1.0]},
        ))
    if alquiler:
        fig.add_trace(go.Indicator(
            mode="number",
            value=alquiler,
            number={"prefix": "€", "suffix": "/mes", "valueformat": ",.0f",
                    "font": {"size": 36, "color": _C_DARK, **_FONT}},
            title={"text": "Alquiler medio",
                   "font": {"size": 12, "color": _C_MUTED, **_FONT}},
            domain={"x": [0.5, 1.0], "y": [0.45, 1.0]},
        ))
    fig.update_layout(
        paper_bgcolor="white", plot_bgcolor="white",
        margin=dict(t=16, b=16, l=16, r=16),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Charts — Sección C: Comportamiento digital
# ─────────────────────────────────────────────────────────────────────────────

def _fig_canal_online(vals):
    """Horizontal bars — online shopping metrics as % of households."""
    nhog = vals.get("n_hogares_total")
    if not nhog:
        return None

    specs = [
        ("online_ultimo_mes_pct",   "Compró online el\núltimo mes",         "rgba(220,53,69,0.50)"),
        ("online_ropa_deporte_pct", "Ha comprado ropa/\ndeporte online",    "rgba(220,53,69,0.75)"),
        ("pct_compras_online",      "Compra online\n(habitual)",             "rgba(220,53,69,0.95)"),
    ]
    labels, values, colors = [], [], []
    for key, label, color in specs:
        v = vals.get(key)
        if v is not None:
            pct = v / nhog * 100
            labels.append(label)
            values.append(round(pct, 1))
            colors.append(color)

    if not labels:
        return None

    fig = go.Figure(go.Bar(
        y=labels, x=values, orientation="h",
        marker=dict(color=colors, line=dict(color="white", width=2)),
        text=[f"{v:.1f}%" for v in values],
        textposition="outside", constraintext="none",
        textfont=dict(size=13, color=_C_DARK, **_FONT),
        hovertemplate="%{y}: <b>%{x:.1f}%</b> de los hogares<extra></extra>",
    ))
    fig.add_vline(x=50, line_dash="dash", line_color="rgba(100,100,100,0.3)", line_width=1.5,
                  annotation_text="50%", annotation_font=dict(size=9, color=_C_MUTED),
                  annotation_position="top")
    fig.update_layout(
        xaxis=dict(title=dict(text="% de hogares en 800 m",
                              font=dict(size=11, color=_C_MUTED, **_FONT)),
                   showgrid=True, gridcolor=_C_GRID,
                   ticksuffix="%", tickfont=dict(size=10, **_FONT),
                   range=[0, max(values) * 1.40]),
        yaxis=dict(showgrid=False, tickfont=dict(size=11, color=_C_DARK, **_FONT), autorange="reversed"),
        plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
        margin=dict(t=20, b=44, l=155, r=8), hovermode="y unified", bargap=0.38,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Ensamblaje público
# ─────────────────────────────────────────────────────────────────────────────

def generar_panel_geo_visual(location_uuid, vals, clima=None, fecha_captura=None):
    activos = {k: v for k, v in vals.items() if v is not None}
    nombre, lat, lon = _info_ubicacion(location_uuid)
    all_cards = _build_metric_cards(activos)

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
                    dbc.Badge(
                        (f"Esri · {pd.Timestamp(fecha_captura).strftime('%d/%m/%Y')}"
                         if fecha_captura else "Esri · datos disponibles"),
                        color="success", pill=True, className="fs-6 px-3 py-2",
                    ) if activos else
                    dbc.Badge("Esri · pendiente", color="secondary", pill=True, className="fs-6 px-3 py-2"),
                    className="d-flex justify-content-end align-items-center h-100",
                ), xs=3,
            ),
        ])),
        className="border-0 rounded-4 mb-4 shadow-sm",
        style={"background": "linear-gradient(135deg, #0052CC 0%, #003d99 100%)"},
    )

    if not activos:
        return html.Div([header, dbc.Card(
            dbc.CardBody(html.P("Variables geoespaciales pendientes de integración con Esri.",
                                className="text-muted small mb-0")),
            className="border-0 shadow-sm rounded-4 mb-3 bg-white",
        )])

    # ── Tarjetas A: Alcance ───────────────────────────────────────────────────
    cards_a = [c for c in all_cards if c["label"] in
               {"Captación peatonal", "Hogares target Miniso"}]
    # ── Tarjetas B: Capacidad económica ───────────────────────────────────────
    cards_b = [c for c in all_cards if c["label"] in
               {"Renta del hogar", "Salud financiera del hogar", "Mercado inmobiliario"}]
    # ── Tarjetas C: Gasto y digital ───────────────────────────────────────────
    cards_c = [c for c in all_cards if c["label"] in
               {"Gasto ropa y calzado", "Canal online (presión omnicanal)"}]
    # ── Tarjetas D: Entorno competitivo (Phase 2) ─────────────────────────────
    cards_d = [c for c in all_cards if c["label"] in
               {"Transporte público", "Competencia directa", "Movilidad peatonal"}]

    # ── Charts ───────────────────────────────────────────────────────────────
    fig_cap    = _fig_captacion(activos)
    fig_mapa   = _fig_mapa(activos, lat, lon, location_uuid)
    fig_edad   = _fig_piramide_edad(activos)
    fig_hogar  = _fig_estructura_hogar(activos)
    fig_gasto  = _fig_gasto_comparativo(activos)
    fig_salud  = _fig_salud_financiera(activos)
    fig_inmob  = _fig_inmobiliario(activos)
    fig_online = _fig_canal_online(activos)

    uid = location_uuid[:8]

    def _row(cols): return dbc.Row(cols, className="g-3 mb-3")

    # Pre-generar todos los insights (texto enriquecido para PM)
    ins_captacion = _auto_insight_captacion(activos)
    ins_edad      = _auto_insight_edad(activos)
    ins_hogar     = _auto_insight_hogar(activos)
    ins_renta     = _auto_insight_renta(activos)
    ins_salud     = _auto_insight_salud(activos)
    ins_gasto     = _auto_insight_gasto(activos)
    ins_online    = _auto_insight_online(activos)
    ins_inmob     = _auto_insight_inmobiliario(activos)

    # ── SECCIÓN A: ALCANCE PEATONAL ───────────────────────────────────────────
    # El mapa lleva el insight de captación; las barras llevan el de edad+hogar
    sec_a_charts = []
    if fig_cap:
        sec_a_charts.append(dbc.Col(
            _chart_card(fig_cap, f"geo-cap-{uid}", _H_CHART,
                        title="Población al alcance a pie · isócronas de 5 / 10 / 15 min"),
            xs=12, lg=5, className="mb-3",
        ))
    if fig_mapa:
        iso_label = "Área de influencia · isócronas peatonales Esri (WalkTime)" if get_catchment_rings(location_uuid) else "Área de influencia · isócronas aproximadas (círculos)"
        sec_a_charts.append(dbc.Col(
            _chart_card(fig_mapa, f"geo-map-{uid}", _H_CHART,
                        title=iso_label,
                        insight=ins_captacion),
            xs=12, lg=7, className="mb-3",
        ))

    sec_a_charts2 = []
    if fig_edad:
        sec_a_charts2.append(dbc.Col(
            _chart_card(fig_edad, f"geo-edad-{uid}", _H_CHART,
                        title="Pirámide de edad · radio 800 m · target Miniso resaltado",
                        insight=ins_edad),
            xs=12, lg=6, className="mb-3",
        ))
    if fig_hogar:
        sec_a_charts2.append(dbc.Col(
            _chart_card(fig_hogar, f"geo-hogar-{uid}", _H_MID,
                        title="Composición del hogar · tipos de familia en 800 m",
                        insight=ins_hogar),
            xs=12, lg=6, className="mb-3",
        ))

    seccion_a = html.Div([
        _section_header("fas fa-walking", "Alcance peatonal",
                        "¿Cuántas personas pueden llegar a pie y cuál es su perfil demográfico?"),
        _render_cards(cards_a, max_per_row=4),
        _row(sec_a_charts),
        _row(sec_a_charts2),
    ], className="mb-4")

    # ── SECCIÓN B: CAPACIDAD ECONÓMICA ────────────────────────────────────────
    # Gasto lleva insight de gasto+renta; salud lleva insight de salud; inmobiliario el suyo
    sec_b_charts = []
    if fig_gasto:
        sec_b_charts.append(dbc.Col(
            _chart_card(fig_gasto, f"geo-gasto-{uid}", "460px",
                        title="Gasto por categoría · €/hogar/año en radio 800 m",
                        insight=ins_gasto),
            xs=12, lg=8, className="mb-3",
        ))
    salud_inmob_col = []
    if fig_salud:
        salud_inmob_col.append(dbc.Col(
            _chart_card(fig_salud, f"geo-salud-{uid}", _H_SM,
                        title="Salud financiera del hogar · radio 800 m",
                        insight=ins_salud),
            xs=12, className="mb-3",
        ))
    if fig_inmob:
        salud_inmob_col.append(dbc.Col(
            _chart_card(fig_inmob, f"geo-inmob-{uid}", _H_SM,
                        title="Precios inmobiliarios · indicador de nivel socioeconómico",
                        insight=ins_inmob),
            xs=12, className="mb-3",
        ))
    if salud_inmob_col:
        sec_b_charts.append(dbc.Col(
            html.Div(salud_inmob_col),
            xs=12, lg=4, className="mb-3",
        ))

    # La tarjeta de renta lleva su propio insight (sin gráfico propio — se muestra bajo las tarjetas)
    seccion_b = html.Div([
        _section_header("fas fa-euro-sign", "Capacidad económica",
                        "¿Tienen renta y estabilidad financiera para gastar de forma habitual?"),
        _render_cards(cards_b, max_per_row=3),
        _insight_box(ins_renta),
        _row(sec_b_charts),
    ], className="mb-4")

    # ── SECCIÓN C: COMPORTAMIENTO DIGITAL ─────────────────────────────────────
    sec_c_charts = []
    if fig_online:
        sec_c_charts.append(dbc.Col(
            _chart_card(fig_online, f"geo-online-{uid}", _H_SM,
                        title="Hábito de compra online · hogares en radio 800 m",
                        insight=ins_online),
            xs=12,
        ))

    seccion_c = html.Div([
        _section_header("fas fa-mobile-alt", "Comportamiento digital",
                        "¿Compran por internet y cuánta presión ejerce eso sobre la tienda física?"),
        _render_cards(cards_c, max_per_row=4),
        _row(sec_c_charts) if sec_c_charts else html.Div(),
    ], className="mb-4")

    # ── SECCIÓN D: ENTORNO COMPETITIVO (Phase 2) ──────────────────────────────
    has_phase2 = any(activos.get(k) is not None for k in
                     ["dist_transporte_min_m", "n_competidores_500m", "indice_movilidad_peatonal"])
    seccion_d = html.Div()
    if has_phase2 and cards_d:
        seccion_d = html.Div([
            _section_header("fas fa-map-marker-alt", "Entorno competitivo",
                            "¿Qué tan accesible es la ubicación y a cuánta competencia directa se enfrenta?"),
            _render_cards(cards_d, max_per_row=3),
        ], className="mb-4")
    elif not has_phase2:
        seccion_d = dbc.Alert(
            [html.I(className="fas fa-info-circle me-2"),
             "Datos de entorno competitivo pendientes — se activan con Places API y Routing (Fase 2)."],
            color="secondary", className="small py-2 px-3 rounded-4 mb-4",
        )

    return html.Div([
        header,
        seccion_a,
        seccion_b,
        seccion_c,
        seccion_d,
    ])
