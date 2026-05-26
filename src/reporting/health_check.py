"""
Panel PM — Diagnóstico narrativo orientado al Product Manager.

Filosofía:
  • El Panel BI ya muestra los números. Este panel los INTERPRETA.
  • Cada sección responde una pregunta concreta del PM:
      1. ¿Cómo fue la semana?       → Narrativa con bullets
      2. ¿Qué zonas necesito mirar? → Tarjetas con semáforo + sparkline
      3. ¿Cuándo viene la gente?    → Distribución por día de la semana
      4. ¿Qué contexto tiene esta ubicación? → Panel geo Esri
  • Números solo cuando son imprescindibles para entender la frase.
  • Gráficos que ilustran una conclusión, no que presentan datos brutos.
"""
import os
import re
import json
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import date, timedelta
from dash import html, dcc
import dash_bootstrap_components as dbc
import holidays
from src.data_processing.data_radar import obtener_info_ubicacion, obtener_clima_historico
from src.data_processing.geo_enrichment import get_geo_vals
from src.reporting.geo_panel import generar_panel_geo_visual

festivos_espana = holidays.ES(years=[2024, 2025, 2026])
dias_semana_es  = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
dias_corto      = ['L', 'M', 'X', 'J', 'V', 'S', 'D']

_C_PRIMARY = "#0052CC"
_C_SUCCESS = "#28A745"
_C_DANGER  = "#DC3545"
_C_AMBER   = "#f39c12"
_C_DARK    = "#2c3e50"
_C_MUTED   = "#6c757d"
_CFG_GRAPH = {"displayModeBar": False, "responsive": True}


# ── Zone helpers ──────────────────────────────────────────────────────────────

def _color_zona(zona):
    zl = str(zona).lower()
    if 'caja'    in zl:                       return "#8e44ad"
    if 'tienda'  in zl:                       return "#e67e22"
    if 'calle'   in zl or 'exterior' in zl:   return "#2980b9"
    return "#7f8c8d"


def _zona_meta(zona):
    """Returns (badge_label, icon_cls, tooltip)."""
    zl = str(zona).lower()
    if 'caja' in zl:
        return ("Cierre de venta", "fas fa-cash-register",
                "Zona de caja — tráfico más directamente ligado a compras.")
    if 'tienda' in zl:
        return ("Conversión", "fas fa-store",
                "Zona interior — mide cuántos del exterior entran y exploran.")
    if 'calle' in zl or 'exterior' in zl:
        return ("Captación", "fas fa-walking",
                "Zona exterior — tráfico de paso frente al establecimiento.")
    return ("Analítica", "fas fa-layer-group", "Zona de medición de tráfico.")


# ── Data helpers ──────────────────────────────────────────────────────────────

def obtener_zonas_validas(ruta='src/data/todas_las_ubicaciones.json'):
    validas = set()
    if os.path.exists(ruta):
        try:
            with open(ruta, encoding='utf-8') as f:
                for org in json.load(f):
                    for loc in org.get('locations', []):
                        for z in loc.get('zones', []):
                            if z.get('zoneType', '').lower() == 'last_zone':
                                validas.add(z.get('zoneName', ''))
        except Exception:
            pass
    return validas


def formatear_fecha(fecha_obj):
    return f"{dias_semana_es[fecha_obj.weekday()]} {fecha_obj.strftime('%d/%m')}"


def calcular_delta(actual, anterior):
    if not anterior or pd.isna(anterior):
        return 0
    return (actual - anterior) / anterior * 100


def evaluar_periodo_zona(df_zona, fecha_max, dias_ventana):
    fmin  = fecha_max - timedelta(days=dias_ventana - 1)
    fmax  = fecha_max
    fmin_a = fmin - timedelta(days=dias_ventana)
    fmax_a = fmin - timedelta(days=1)

    dp  = df_zona[(df_zona['fecha_dt'] >= fmin)   & (df_zona['fecha_dt'] <= fmax)]
    da  = df_zona[(df_zona['fecha_dt'] >= fmin_a) & (df_zona['fecha_dt'] <= fmax_a)]

    def _dwell(df):
        if 'dwell_time' not in df.columns or df.empty: return 0.0
        m = df['dwell_time'].mean()
        return 0.0 if pd.isna(m) else m / 60

    res = {'visitantes': int(dp['unique_visitors'].sum()) if 'unique_visitors' in dp.columns else 0,
           'estancia':   _dwell(dp)}
    ant = {'visitantes': int(da['unique_visitors'].sum()) if 'unique_visitors' in da.columns else 0,
           'estancia':   _dwell(da)}

    dias_act = dp.groupby('fecha_dt')['unique_visitors'].sum().reset_index() \
               if 'unique_visitors' in dp.columns else pd.DataFrame()

    return res, ant, {k: calcular_delta(res[k], ant[k]) for k in res}, fmin, fmax, dias_act


def _slug(text):
    return re.sub(r'[^a-z0-9]', '-', str(text).lower())[:20]


# ── Chart builders ────────────────────────────────────────────────────────────

def _fig_sparkline(dias_28, color):
    """Línea de tendencia de 28 días — sin ejes, sin etiquetas, solo la forma."""
    if dias_28 is None or dias_28.empty:
        return None
    df = dias_28.sort_values('fecha_dt')
    y  = df['unique_visitors'].fillna(0).values
    if len(y) < 3:
        return None

    # Línea de tendencia (regresión lineal)
    x_num = np.arange(len(y))
    coef  = np.polyfit(x_num, y, 1)
    trend = np.polyval(coef, x_num)
    trend_color = _C_SUCCESS if coef[0] >= 0 else _C_DANGER

    fig = go.Figure()
    # Área rellena debajo de la línea real
    fig.add_trace(go.Scatter(
        x=list(x_num), y=y.tolist(),
        mode='lines',
        line=dict(color=color, width=1.5, shape='spline'),
        fill='tozeroy',
        fillcolor=color.replace('#', 'rgba(').replace(')', ',0.08)') if False else f"rgba(0,0,0,0.04)",
        hoverinfo='skip',
    ))
    # Línea de tendencia punteada
    fig.add_trace(go.Scatter(
        x=list(x_num), y=trend.tolist(),
        mode='lines',
        line=dict(color=trend_color, width=1.2, dash='dot'),
        hoverinfo='skip',
    ))
    fig.update_layout(
        height=68,
        margin=dict(t=4, b=4, l=4, r=4, pad=0),
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, rangemode='tozero'),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
    )
    return fig


def _fig_dias_semana(df_todas_zonas, fecha_max):
    """
    Distribución media de visitantes por día de la semana (últimas 4 semanas).
    Responde: ¿Cuándo viene la gente? ¿Qué días necesito más personal?
    """
    if df_todas_zonas.empty or 'unique_visitors' not in df_todas_zonas.columns:
        return None

    fmin = fecha_max - timedelta(days=27)
    df = df_todas_zonas[
        (df_todas_zonas['fecha_dt'] >= fmin) &
        (df_todas_zonas['fecha_dt'] <= fecha_max)
    ].copy()

    if df.empty:
        return None

    df['dia_sem'] = pd.to_datetime(df['fecha_dt']).dt.dayofweek
    por_dia = (
        df.groupby(['fecha_dt', 'dia_sem'])['unique_visitors']
        .sum().reset_index()
        .groupby('dia_sem')['unique_visitors']
        .mean()
        .reindex(range(7), fill_value=0)
    )

    vals   = por_dia.values
    max_v  = vals.max() or 1
    ratios = vals / max_v

    # Color: más intenso = más tráfico
    bar_colors = [
        f"rgba(0,82,204,{0.18 + 0.72 * r:.2f})" for r in ratios
    ]
    # Etiquetar solo el pico
    peak_idx = int(np.argmax(vals))
    text_labels = [
        f"<b>{int(v):,}</b>" if i == peak_idx else ""
        for i, v in enumerate(vals)
    ]

    fig = go.Figure(go.Bar(
        x=dias_corto,
        y=vals,
        marker=dict(color=bar_colors, line=dict(width=0)),
        text=text_labels,
        textposition='outside',
        textfont=dict(size=11, color=_C_DARK),
        hovertemplate='%{x}: <b>%{y:,.0f}</b> vis. promedio<extra></extra>',
    ))
    fig.update_layout(
        height=160,
        margin=dict(t=16, b=8, l=8, r=8),
        xaxis=dict(showgrid=False, tickfont=dict(size=12, color=_C_DARK), fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.30]),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
        bargap=0.28,
    )
    return fig


def _fig_finde_vs_laborable(df_todas_zonas, fecha_max):
    """Promedio visitantes/día: entre semana vs fin de semana (últimas 4 semanas)."""
    if df_todas_zonas.empty or 'unique_visitors' not in df_todas_zonas.columns:
        return None
    fmin = fecha_max - timedelta(days=27)
    df = df_todas_zonas[
        (df_todas_zonas['fecha_dt'] >= fmin) &
        (df_todas_zonas['fecha_dt'] <= fecha_max)
    ].copy()
    if df.empty:
        return None
    df['dia_sem'] = pd.to_datetime(df['fecha_dt']).dt.dayofweek
    df['tipo'] = df['dia_sem'].apply(
        lambda x: 'Fin de semana' if x >= 5 else 'Entre semana'
    )
    por_dia = df.groupby(['fecha_dt', 'tipo'])['unique_visitors'].sum().reset_index()
    avg = por_dia.groupby('tipo')['unique_visitors'].mean()
    tipos  = ['Entre semana', 'Fin de semana']
    vals   = [avg.get(t, 0) for t in tipos]
    if max(vals) == 0:
        return None
    colors = [_C_PRIMARY, "#e67e22"]
    fig = go.Figure(go.Bar(
        x=tipos, y=vals,
        marker=dict(color=colors, line=dict(width=0)),
        text=[f"{v:,.0f}" for v in vals],
        textposition='outside',
        textfont=dict(size=12, color=_C_DARK),
        hovertemplate='%{x}: <b>%{y:,.0f}</b> visitantes/día<extra></extra>',
    ))
    max_v = max(vals)
    fig.update_layout(
        height=180,
        margin=dict(t=20, b=8, l=8, r=8),
        xaxis=dict(showgrid=False, tickfont=dict(size=12, color=_C_DARK), fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.35]),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
        bargap=0.45,
    )
    return fig


def _fig_dwell_zonas(zonas_data):
    """Tiempo medio de permanencia por zona — últimos 7 días."""
    data = [
        (z['zona'], z['r7']['estancia'], _color_zona(z['zona']))
        for z in zonas_data if z['r7']['estancia'] > 0
    ]
    if not data:
        return None
    data.sort(key=lambda x: x[1], reverse=True)
    labels = [d[0] for d in data]
    values = [d[1] for d in data]
    colors = [d[2] for d in data]
    max_v  = max(values)
    fig = go.Figure(go.Bar(
        y=labels, x=values,
        orientation='h',
        marker=dict(color=colors, line=dict(width=0)),
        text=[f"{v:.1f} min" for v in values],
        textposition='outside',
        constraintext='none',
        textfont=dict(size=11, color=_C_DARK),
        hovertemplate='%{y}: <b>%{x:.1f} min</b> promedio<extra></extra>',
    ))
    fig.update_layout(
        height=180,
        margin=dict(t=8, b=8, l=8, r=52),
        xaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.5]),
        yaxis=dict(showgrid=False, tickfont=dict(size=12, color=_C_DARK), fixedrange=True),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
        bargap=0.40,
    )
    return fig


def _fig_embudo_conversion(zonas_data):
    """
    Embudo exterior → tienda → caja con tasa de conversión entre pasos.
    Requiere al menos dos zonas con roles distintos identificables.
    """
    def _rol(z):
        zl = z['zona'].lower()
        if 'exterior' in zl or 'calle' in zl: return 0
        if 'tienda' in zl:                    return 1
        if 'caja'   in zl:                    return 2
        return 99

    pasos = sorted([z for z in zonas_data if _rol(z) < 99], key=_rol)
    if len(pasos) < 2:
        return None
    values = [max(z['r7']['visitantes'], 0) for z in pasos]
    if max(values) == 0:
        return None

    labels = [z['zona'] for z in pasos]
    colors = [_color_zona(z['zona']) for z in pasos]
    texts  = []
    for i, v in enumerate(values):
        if i == 0:
            texts.append(f"<b>{v:,.0f}</b>")
        else:
            pct = v / (values[i - 1] or 1) * 100
            texts.append(f"<b>{v:,.0f}</b>  ·  {pct:.0f}% del paso anterior")

    max_v = max(values)
    fig   = go.Figure()
    for lbl, val, col, txt in zip(labels, values, colors, texts):
        fig.add_trace(go.Bar(
            y=[lbl], x=[val], orientation='h',
            marker=dict(color=col, line=dict(width=0)),
            text=[txt], textposition='outside', constraintext='none',
            textfont=dict(size=11, color=_C_DARK),
            hovertemplate=f'{lbl}: <b>%{{x:,.0f}}</b> visitantes<extra></extra>',
            showlegend=False,
        ))
    fig.update_layout(
        height=180,
        margin=dict(t=8, b=8, l=8, r=8),
        xaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.65]),
        yaxis=dict(showgrid=False, tickfont=dict(size=12, color=_C_DARK), fixedrange=True),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
        barmode='group',
        bargap=0.40,
    )
    return fig


# ── Narrative engine ──────────────────────────────────────────────────────────

def _narrativa(zonas_data, fecha_max, clima):
    """
    Genera una lista de (nivel, icon_cls, texto) con lenguaje natural para un PM.
    Sin guiones como separadores. Cada frase responde una pregunta implícita.
    Prioridad: global → día pico → estancia → alertas por zona → contexto externo.
    """
    items = []

    total7   = sum(z['r7']['visitantes'] for z in zonas_data)
    total7_a = sum(z['a7']['visitantes'] for z in zonas_data)
    dg       = calcular_delta(total7, total7_a)

    # 1. Resumen global de la semana
    if dg >= 10:
        items.append(("success", "fas fa-arrow-trend-up",
            f"Buena semana de tráfico. El volumen total creció un {dg:.0f}% respecto a la semana pasada."))
    elif dg <= -10:
        items.append(("danger", "fas fa-arrow-trend-down",
            f"Semana complicada. El tráfico total bajó un {abs(dg):.0f}% respecto a la semana pasada."))
    else:
        items.append(("secondary", "fas fa-equals",
            f"Semana sin cambios relevantes. El tráfico se mantuvo prácticamente igual que la semana anterior ({dg:+.0f}%)."))

    # 2. Día pico
    all_dias = pd.concat(
        [z['dias7'] for z in zonas_data if not z['dias7'].empty],
        ignore_index=True,
    ) if any(not z['dias7'].empty for z in zonas_data) else pd.DataFrame()

    if not all_dias.empty:
        agg  = all_dias.groupby('fecha_dt')['unique_visitors'].sum().reset_index()
        peak = agg.loc[agg['unique_visitors'].idxmax()]
        items.append(("primary", "fas fa-calendar-day",
            f"El {formatear_fecha(peak['fecha_dt'])} fue el día con más afluencia de la semana, "
            f"con {int(peak['unique_visitors']):,} personas."))

    # 3. Estancia media
    est7   = sum(z['r7']['estancia'] * max(z['r7']['visitantes'], 1) for z in zonas_data) / max(total7,   1)
    est7_a = sum(z['a7']['estancia'] * max(z['a7']['visitantes'], 1) for z in zonas_data) / max(total7_a, 1)
    d_est  = calcular_delta(est7, est7_a)

    if est7 > 0 and abs(d_est) >= 6:
        if d_est > 0:
            items.append(("success", "fas fa-clock",
                f"Los clientes se quedaron más tiempo esta semana: {est7:.1f} min de media frente a "
                f"{est7_a:.1f} min la semana pasada. Buena señal de interés en el espacio."))
        else:
            items.append(("warning", "fas fa-clock",
                f"Los clientes están pasando menos tiempo en tienda: {est7:.1f} min frente a "
                f"{est7_a:.1f} min. Vale la pena revisar si algo los está alejando antes de tiempo."))

    # 4. Alertas por zona
    for z in zonas_data:
        zn  = z['zona']
        zl  = zn.lower()
        dv  = z['d7']['visitantes']

        if 'exterior' in zl or 'calle' in zl:
            if dv <= -20:
                items.append(("warning", "fas fa-walking",
                    f"El tráfico de paso bajó un {abs(dv):.0f}% esta semana. "
                    f"Antes de actuar, comprueba si hay algo externo que lo explique: obras, calle cortada o mal tiempo. "
                    f"Mira también los interiores, pueden contar una historia diferente."))
        elif 'tienda' in zl:
            ext = next((z2 for z2 in zonas_data
                        if 'exterior' in z2['zona'].lower() or 'calle' in z2['zona'].lower()), None)
            if ext:
                ext_dv = ext['d7']['visitantes']
                if dv <= -15 and ext_dv > -5:
                    items.append(("danger", "fas fa-store",
                        f"El exterior aguantó, pero la tienda cayó un {abs(dv):.0f}%. "
                        f"Algo dentro no está convirtiendo el paso en entrada. "
                        f"Revisa el escaparate, la señalética o la disposición de la entrada."))
                elif dv >= 15 and ext_dv < 5:
                    items.append(("success", "fas fa-store",
                        f"Buena señal de conversión: la tienda creció un {dv:.0f}% con el exterior estable. "
                        f"Estás atrayendo una mayor proporción del paso de calle."))
            elif dv <= -15:
                items.append(("danger", "fas fa-store",
                    f"La zona interior bajó un {abs(dv):.0f}% esta semana. Merece una revisión."))
        elif 'caja' in zl:
            if dv <= -15:
                items.append(("danger", "fas fa-cash-register",
                    f"Menos gente llegó a caja esta semana: bajó un {abs(dv):.0f}%. "
                    f"Compara con el tráfico interior para saber si es un problema de conversión o de afluencia general."))
            elif dv >= 15:
                items.append(("success", "fas fa-cash-register",
                    f"La caja fue bien esta semana: creció un {dv:.0f}%. Más ventas cerradas."))

    # 5. Contexto externo: clima
    if clima:
        fmin7    = fecha_max - timedelta(days=6)
        dias_rec = {k: v for k, v in clima.items()
                    if k >= fmin7.strftime('%Y-%m-%d')}
        n_lluvia = sum(1 for v in dias_rec.values() if v.get('precip', 0) > 2)
        if n_lluvia >= 3:
            items.append(("info", "fas fa-cloud-rain",
                f"Hubo {n_lluvia} días de lluvia esta semana. Eso puede explicar parte de la bajada "
                f"en tráfico exterior. Con mejor tiempo, los números probablemente serían más altos."))
        elif dias_rec:
            tmaxes = [v.get('tmax') for v in dias_rec.values() if v.get('tmax')]
            if tmaxes and max(tmaxes) > 33:
                items.append(("info", "fas fa-sun",
                    f"Esta semana hizo mucho calor, con picos de hasta {max(tmaxes):.0f}°C. "
                    f"El tráfico de calle suele resentirse en las horas centrales cuando aprieta el sol."))

    # 6. Festivos
    fmin7 = fecha_max - timedelta(days=6)
    fest  = [(f, n) for f, n in festivos_espana.items()
             if isinstance(f, date) and fmin7 <= f <= fecha_max]
    if fest:
        nombres = ", ".join(n for _, n in fest[:2])
        pl = "s" if len(fest) > 1 else ""
        items.append(("info", "fas fa-umbrella-beach",
            f"Esta semana hubo festivo{pl} ({nombres}). "
            f"Ten en cuenta que los datos de días festivos no son comparables con una semana laboral normal."))

    return items


# ── Section renderers ─────────────────────────────────────────────────────────

def _render_narrativa(items):
    """Convierte la lista de insights en tarjetas de texto con icono coloreado."""
    _LEVEL_COLOR = {
        "success":   (_C_SUCCESS, "#e8f5e9"),
        "danger":    (_C_DANGER,  "#fdecea"),
        "warning":   (_C_AMBER,   "#fff8e1"),
        "primary":   (_C_PRIMARY, "#e8f0fe"),
        "secondary": (_C_MUTED,   "#f5f5f5"),
        "info":      ("#17a2b8",  "#e8f7fa"),
    }
    rows = []
    for level, icon_cls, texto in items:
        icon_color, bg = _LEVEL_COLOR.get(level, (_C_MUTED, "#f5f5f5"))
        rows.append(
            html.Div(
                className="d-flex align-items-start gap-3 py-3",
                style={"borderBottom": "1px solid #f0f0f0"},
                children=[
                    html.Div(
                        html.I(className=f"{icon_cls}",
                               style={"color": icon_color, "fontSize": "0.9rem"}),
                        className="d-flex align-items-center justify-content-center flex-shrink-0",
                        style={
                            "width": "32px", "height": "32px",
                            "borderRadius": "8px", "background": bg,
                        },
                    ),
                    html.P(texto, className="mb-0",
                           style={"fontSize": "0.88rem", "color": _C_DARK,
                                  "lineHeight": "1.7", "paddingTop": "4px"}),
                ],
            )
        )
    if not rows:
        return html.Div()
    return dbc.Card(
        dbc.CardBody(html.Div(rows), className="px-4 py-2"),
        className="border-0 shadow-sm rounded-4 mb-4 bg-white",
    )


def _render_zona_card(zona, r7, a7, d7, dias_28, uid):
    """Tarjeta de zona: semáforo + nombre + una línea + sparkline."""
    color          = _color_zona(zona)
    badge_lbl, icon_cls, tooltip_role = _zona_meta(zona)
    zone_slug      = _slug(zona)
    badge_id       = f"pm-z-{zone_slug}-{uid}"
    sem_id         = f"pm-sem-{zone_slug}-{uid}"
    spark_info_id  = f"pm-spark-info-{zone_slug}-{uid}"

    dv = d7['visitantes']
    if dv >= 5:
        sem_color, sem_txt = _C_SUCCESS, f"Subió un {dv:.0f}% esta semana"
    elif dv <= -5:
        sem_color, sem_txt = _C_DANGER,  f"Bajó un {abs(dv):.0f}% esta semana"
    else:
        sem_color, sem_txt = _C_AMBER,   "Sin cambios relevantes esta semana"

    sem_tooltip = (
        f"Esta semana: {r7['visitantes']:,} visitantes únicos"
        + (f" · Semana anterior: {a7['visitantes']:,}" if a7['visitantes'] else "")
        + (f" · Estancia media: {r7['estancia']:.1f} min" if r7['estancia'] > 0 else "")
    )

    sparkline = _fig_sparkline(dias_28, color)

    return dbc.Card(
        dbc.CardBody([
            # Header de zona
            html.Div(className="d-flex justify-content-between align-items-center mb-2",
                     children=[
                html.Div(className="d-flex align-items-center gap-2", children=[
                    html.I(className="fas fa-circle", id=sem_id,
                           style={"color": sem_color, "fontSize": "0.65rem",
                                  "flexShrink": "0", "cursor": "help"}),
                    dbc.Tooltip(sem_tooltip, target=sem_id, placement="top"),
                    html.Span(zona, className="fw-bold",
                              style={"fontSize": "0.82rem", "color": _C_DARK}),
                    html.Span(id=badge_id, children=f"· {badge_lbl}",
                              className="text-muted",
                              style={"fontSize": "0.74rem", "cursor": "help"}),
                    dbc.Tooltip(tooltip_role, target=badge_id, placement="top"),
                ]),
            ]),
            # Estado en texto
            html.P(sem_txt,
                   style={"fontSize": "0.76rem", "color": sem_color,
                          "fontWeight": "600", "marginBottom": "6px"}),
            # Sparkline 28d
            html.Div([
                html.Div(className="d-flex justify-content-between align-items-center mb-1",
                         children=[
                    html.Span("Tendencia 28d",
                              style={"fontSize": "0.62rem", "color": _C_MUTED,
                                     "textTransform": "uppercase", "letterSpacing": "0.4px"}),
                    html.Span([
                        html.I(className="fas fa-circle-info", id=spark_info_id,
                               style={"color": _C_MUTED, "fontSize": "0.65rem",
                                      "cursor": "help"}),
                        dbc.Tooltip(
                            "Visitantes únicos diarios · últimos 28 días. "
                            "La línea continua muestra el tráfico real; "
                            "la línea punteada es la tendencia lineal "
                            "(verde = subiendo, roja = bajando).",
                            target=spark_info_id, placement="top",
                        ),
                    ]),
                ]),
                dcc.Graph(
                    id=f"spark-{zone_slug}-{uid}",
                    figure=sparkline,
                    config=_CFG_GRAPH,
                    style={"height": "68px"},
                ) if sparkline else html.P(
                    "Sin datos de tendencia",
                    className="text-muted small text-center mb-0 py-2",
                ),
            ]) if sparkline else html.P(
                "Sin datos de tendencia",
                className="text-muted small text-center mb-0 py-2",
            ),
        ], className="p-3"),
        className="border-0 shadow-sm rounded-4 h-100",
        style={"borderTop": f"3px solid {color}", "overflow": "visible"},
    )


def _render_pm_questions(df, zonas_data, fecha_max, uid):
    """
    Responde gráficamente las preguntas habituales de un PM sobre el tráfico.
    Cada carta tiene una pregunta en lenguaje natural + gráfico directo.
    """
    def _q_card(pregunta, subtitulo, fig, gid, height):
        if fig is None:
            return None
        return dbc.Card(
            dbc.CardBody([
                html.P(
                    pregunta,
                    className="fw-bold mb-0",
                    style={"fontSize": "0.84rem", "color": _C_DARK},
                ),
                html.P(subtitulo, className="text-muted mb-2",
                       style={"fontSize": "0.72rem", "lineHeight": "1.4"}),
                dcc.Graph(
                    id=gid, figure=fig, config=_CFG_GRAPH,
                    style={"height": height},
                ),
            ], className="px-4 py-3"),
            className="border-0 shadow-sm rounded-4 h-100 bg-white",
        )

    preguntas = [
        (
            _fig_dias_semana(df, fecha_max),
            f"q-dias-{uid}",
            "¿Cuándo viene la gente?",
            "Media de visitantes por día de la semana · últimas 4 semanas · el tono más oscuro marca el pico",
            "160px",
        ),
        (
            _fig_finde_vs_laborable(df, fecha_max),
            f"q-finde-{uid}",
            "¿Rinde mejor el fin de semana o entre semana?",
            "Promedio de visitantes por día · últimas 4 semanas",
            "180px",
        ),
        (
            _fig_dwell_zonas(zonas_data),
            f"q-dwell-{uid}",
            "¿Cuánto tiempo se quedan?",
            "Tiempo medio de permanencia por zona · últimos 7 días",
            "180px",
        ),
        (
            _fig_embudo_conversion(zonas_data),
            f"q-embudo-{uid}",
            "¿Cuántos visitantes convierten?",
            "Tráfico por etapa · últimos 7 días · porcentaje respecto al paso anterior",
            "180px",
        ),
    ]

    cols = []
    for fig, gid, preg, sub, h in preguntas:
        card = _q_card(preg, sub, fig, gid, h)
        if card:
            cols.append(dbc.Col(card, xs=12, md=6, className="mb-3"))

    if not cols:
        return html.Div()

    return html.Div([
        html.P(
            [html.I(className="fas fa-magnifying-glass me-2 text-primary"),
             "Comportamiento de la visita"],
            className="fw-bold mb-3",
            style={"fontSize": "0.78rem", "color": _C_MUTED,
                   "textTransform": "uppercase", "letterSpacing": "0.5px"},
        ),
        dbc.Row(cols, className="g-3"),
    ], className="mb-4")


# ── Main assembly ─────────────────────────────────────────────────────────────

def generar_mensajes_salud(df, ubi, zonas_seleccionadas=None, location_uuid=None):
    if df.empty:
        return dbc.Alert("Ausencia de datos.", color="warning", className="rounded-4")

    zonas_validas = obtener_zonas_validas()
    if zonas_validas:
        df = df[df['Zona'].isin(zonas_validas)]
    if zonas_seleccionadas:
        df = df[df['Zona'].isin(zonas_seleccionadas)]
    if df.empty:
        return dbc.Alert("Ausencia de datos en la selección.", color="info", className="rounded-4")

    df = df.copy()
    df['fecha_dt'] = pd.to_datetime(df['fecha']).dt.date
    fecha_max = df['fecha_dt'].max()
    if pd.isna(fecha_max):
        return dbc.Alert("Error de formato de fecha.", color="danger", className="rounded-4")

    lat, lon, _ = obtener_info_ubicacion(ubi)
    clima = obtener_clima_historico(
        lat, lon,
        (fecha_max - timedelta(days=60)).strftime('%Y-%m-%d'),
        fecha_max.strftime('%Y-%m-%d'),
    )

    uid = _slug(location_uuid or ubi)

    # ── Datos por zona ───────────────────────────────────────────────────
    puntos  = 0
    zonas_data = []
    for zona in df['Zona'].unique():
        dz = df[df['Zona'] == zona]
        r7, a7, d7, fmin7, fmax7, dias7 = evaluar_periodo_zona(dz, fecha_max, 7)
        r28, a28, d28, *_              = evaluar_periodo_zona(dz, fecha_max, 28)

        # Sparkline: 28 días diarios
        dias_28 = (
            dz[dz['fecha_dt'] >= fecha_max - timedelta(days=27)]
            .groupby('fecha_dt')['unique_visitors'].sum().reset_index()
            if 'unique_visitors' in dz.columns else pd.DataFrame()
        )

        if   d7['visitantes'] >=  5: puntos += 1
        elif d7['visitantes'] <= -5: puntos -= 1

        zonas_data.append(dict(
            zona=zona, r7=r7, a7=a7, d7=d7, r28=r28, a28=a28, d28=d28,
            fmin7=fmin7, fmax7=fmax7, dias7=dias7, dias_28=dias_28,
        ))

    # ── Health status ────────────────────────────────────────────────────
    if   puntos >= 1:  health_label, badge_color = "Tendencia positiva", "success"
    elif puntos <= -1: health_label, badge_color = "Tendencia negativa",  "danger"
    else:               health_label, badge_color = "Tendencia estable",   "warning"

    health_badge_id = f"pm-health-{uid}"
    n_zonas = len(zonas_data)
    health_tooltip = (
        f"Score calculado sobre {n_zonas} zona{'s' if n_zonas != 1 else ''}: "
        f"+1 por cada zona con δ visitantes ≥ +5 %, "
        f"−1 por cada zona con δ ≤ −5 %. "
        f"Score total: {puntos:+d}."
    )

    # ── 1. Header ────────────────────────────────────────────────────────
    header = dbc.Card(
        dbc.CardBody(dbc.Row([
            dbc.Col([
                html.P("Panel PM", className="mb-1 text-white-50 text-uppercase fw-bold",
                       style={"fontSize": "0.61rem", "letterSpacing": "1px"}),
                html.H4(ubi, className="fw-bold mb-1 text-white"),
                html.P(
                    f"{(fecha_max - timedelta(days=27)).strftime('%d %b')} – "
                    f"{fecha_max.strftime('%d %b %Y')}",
                    className="mb-0",
                    style={"fontSize": "0.84rem", "color": "rgba(255,255,255,0.82)",
                           "fontWeight": "500"},
                ),
            ], xs=9),
            dbc.Col(
                html.Div([
                    dbc.Badge(health_label, color=badge_color, pill=True,
                              className="fs-6 px-3 py-2", id=health_badge_id,
                              style={"cursor": "help"}),
                    dbc.Tooltip(health_tooltip, target=health_badge_id,
                                placement="left"),
                ], className="d-flex justify-content-end align-items-center h-100"),
                xs=3,
            ),
        ])),
        className="border-0 rounded-4 mb-4 shadow-sm",
        style={"background": "linear-gradient(135deg, #0052CC 0%, #003d99 100%)"},
    )

    # ── 2. Narrativa ─────────────────────────────────────────────────────
    items_narrativa = _narrativa(zonas_data, fecha_max, clima)
    narrativa       = _render_narrativa(items_narrativa)

    # ── 3. Zonas (semáforo + sparkline) ──────────────────────────────────
    def _orden(z):
        zl = z['zona'].lower()
        if 'exterior' in zl or 'calle' in zl: return 0
        if 'tienda' in zl:                    return 1
        if 'caja' in zl:                      return 2
        return 3

    zona_cols = [
        dbc.Col(
            _render_zona_card(z['zona'], z['r7'], z['a7'], z['d7'],
                              z['dias_28'], uid),
            xs=12, sm=6, xl=3, className="mb-3",
        )
        for z in sorted(zonas_data, key=_orden)
    ]

    zonas_section = html.Div([
        html.P(
            [html.I(className="fas fa-layer-group me-2 text-primary"),
             "Estado por zona · últimos 7 días"],
            className="fw-bold mb-3",
            style={"fontSize": "0.78rem", "color": _C_MUTED,
                   "textTransform": "uppercase", "letterSpacing": "0.5px"},
        ),
        dbc.Row(zona_cols, className="g-3"),
    ], className="mb-4")

    # ── 4. Preguntas PM ──────────────────────────────────────────────────
    dias_section = _render_pm_questions(df, zonas_data, fecha_max, uid)

    # ── 5. Geo panel ─────────────────────────────────────────────────────
    geo = (
        generar_panel_geo_visual(location_uuid, get_geo_vals(location_uuid), clima)
        if location_uuid else html.Div()
    )

    # ── PDF header (print-only) ───────────────────────────────────────────
    zonas_txt  = ", ".join(zonas_seleccionadas or []) or "Todas las zonas analíticas"
    pdf_header = html.Div([
        dbc.Row([
            dbc.Col([
                html.H2("INFORME DE RENDIMIENTO OPERATIVO", className="fw-bold text-dark mb-1"),
                html.H5(f"UBICACIÓN: {ubi.upper()}", className="text-secondary fw-bold mb-0"),
            ], width=8),
            dbc.Col([
                html.P(f"Emitido: {pd.Timestamp('today').strftime('%d/%m/%Y')}",
                       className="text-end text-muted mb-0 small fw-bold"),
                html.P(f"Datos hasta: {fecha_max.strftime('%d/%m/%Y')}",
                       className="text-end text-muted mb-0 small"),
            ], width=4, className="d-flex flex-column justify-content-center"),
        ], className="mb-3"),
        html.P([html.Strong("Segmentación: "), zonas_txt], className="mb-2"),
        html.Hr(style={"borderTop": "3px solid #2c3e50", "opacity": "1"}),
        html.Br(),
    ], className="d-none d-print-block")

    return html.Div([
        pdf_header,
        header,
        narrativa,
        zonas_section,
        dias_section,
        geo,
    ])


def generar_panel_pm(df_completo, locs, zonas_sel):
    if df_completo is None or df_completo.empty:
        return dbc.Alert("Sincroniza los datos.", color="warning", className="rounded-4")
    if not locs:
        return dbc.Alert("Selecciona una ubicación.", color="info", className="rounded-4")

    paneles = []
    for ubi in df_completo[df_completo['location_id'].isin(locs)]['Ubicación'].unique():
        df_ubi   = df_completo[df_completo['Ubicación'] == ubi]
        loc_uuid = df_ubi['location_id'].iloc[0] if 'location_id' in df_ubi.columns else None
        paneles.append(generar_mensajes_salud(df_ubi, ubi, zonas_sel, loc_uuid))
    return html.Div(paneles)
