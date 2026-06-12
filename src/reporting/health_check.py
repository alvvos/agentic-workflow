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
from src.data_processing.geo_enrichment import get_geo_vals, get_geo_snapshot_date
from src.reporting.geo_panel import generar_panel_geo_visual
from src.core import data_master as _dm

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

_PALETA_PM = [
    '#0052CC', '#E67E22', '#27AE60', '#8E44AD', '#E74C3C',
    '#17A2B8', '#F39C12', '#2ECC71', '#9B59B6', '#C0392B',
    '#1ABC9C', '#D35400', '#2980B9', '#16A085', '#7D3C98',
]

def _color_zona(zona):
    zl = str(zona).lower()
    if 'caja'    in zl:                     return "#8e44ad"
    if 'tienda'  in zl:                     return "#e67e22"
    if 'calle'   in zl or 'exterior' in zl: return "#2980b9"
    return _PALETA_PM[hash(zona) % len(_PALETA_PM)]


def _zona_meta(zona):
    """Returns (badge_label, icon_cls, tooltip)."""
    zl = str(zona).lower()
    if 'caja' in zl:
        return ("Cierre de venta", "fas fa-cash-register",
                "Zona de caja — tráfico vinculado directamente a la conversión en compra.")
    if 'tienda' in zl:
        return ("Conversión", "fas fa-store",
                "Zona interior — indica qué proporción del tráfico exterior accede al establecimiento.")
    if 'calle' in zl or 'exterior' in zl:
        return ("Captación", "fas fa-walking",
                "Zona exterior — tráfico peatonal registrado frente al establecimiento.")
    return ("Analítica", "fas fa-layer-group", "Zona de medición de tráfico.")


# ── Data helpers ──────────────────────────────────────────────────────────────

def obtener_zonas_validas(ruta=None):
    try:
        from src.db.store import get_conn
        rows = get_conn().execute(
            "SELECT nombre FROM dim_zonas WHERE zone_type = 'last_zone' AND hidden = FALSE"
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


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


def _pct_activos(df_zona, fmin, fmax):
    """Fracción de días en [fmin, fmax] con unique_visitors > 0."""
    n_dias = max((fmax - fmin).days + 1, 1)
    if df_zona.empty or 'unique_visitors' not in df_zona.columns:
        return 0.0
    activos = df_zona[
        (df_zona['fecha_dt'] >= fmin) &
        (df_zona['fecha_dt'] <= fmax) &
        (df_zona['unique_visitors'] > 0)
    ]['fecha_dt'].nunique()
    return activos / n_dias


# ── Chart builders ────────────────────────────────────────────────────────────

def _fig_sparkline(dias_28, color):
    """Línea de tendencia de 28 días — sin ejes, sin etiquetas, solo la forma."""
    if dias_28 is None or dias_28.empty:
        return None
    df = dias_28.sort_values('fecha_dt')
    # NaN-aware: zeros are sensor outage days, treat as missing data
    y_raw = df['unique_visitors'].values.astype(float)
    valid = ~np.isnan(y_raw)
    if valid.sum() < 3:
        return None

    x_num = np.arange(len(y_raw))
    # Trend calculated only on valid (non-gap) points
    coef  = np.polyfit(x_num[valid], y_raw[valid], 1)
    trend = np.polyval(coef, x_num)
    trend_color = _C_SUCCESS if coef[0] >= 0 else _C_DANGER

    fig = go.Figure()
    # Área rellena debajo de la línea real — connectgaps=False shows sensor gaps
    fig.add_trace(go.Scatter(
        x=list(x_num), y=y_raw.tolist(),
        mode='lines',
        connectgaps=False,
        line=dict(color=color, width=1.5, shape='spline'),
        fill='tozeroy',
        fillcolor=f"rgba(0,0,0,0.04)",
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


def _fig_dias_semana(df_todas_zonas, fecha_max, dias=28):
    """
    Distribución de visitantes por día de la semana.
    Con dias=7 muestra los valores reales de esa semana; con dias=28 promedia 4 semanas.
    """
    if df_todas_zonas.empty or 'unique_visitors' not in df_todas_zonas.columns:
        return None

    fmin = fecha_max - timedelta(days=dias - 1)
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
        hovertemplate='%{x}: <b>%{y:,.0f}</b> visitantes (media/día)<extra></extra>',
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


def _fig_finde_vs_laborable(df_todas_zonas, fecha_max, dias=28):
    """Promedio visitantes/día: entre semana vs fin de semana."""
    if df_todas_zonas.empty or 'unique_visitors' not in df_todas_zonas.columns:
        return None
    fmin = fecha_max - timedelta(days=dias - 1)
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
        hovertemplate='%{x}: <b>%{y:,.0f}</b> visitantes/día (media)<extra></extra>',
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


def _fig_dwell_zonas(zonas_data, child_zones=None):
    """Tiempo medio de permanencia por zona — solo zonas padre."""
    _cz = child_zones or set()
    data = [
        (z['zona'], z['r']['estancia'], _color_zona(z['zona']))
        for z in zonas_data if z['r']['estancia'] > 0 and z['zona'] not in _cz
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
    values = [max(z['r']['visitantes'], 0) for z in pasos]
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

def _narrativa(zonas_data, fecha_max, clima, ventana="semana", geo_vals=None):
    """
    Genera una lista de (nivel, icon_cls, texto) con lenguaje natural para un PM.
    Sin guiones como separadores. Cada frase responde una pregunta implícita.
    Prioridad: global → día pico → estancia → alertas por zona → contexto externo.
    """
    items   = []
    periodo = "mes" if ventana == "mes" else "semana"
    periodo_ant = "el mes" if ventana == "mes" else "la semana"
    dias_v  = 28 if ventana == "mes" else 7

    total_p   = sum(z['r']['visitantes'] for z in zonas_data)
    total_p_a = sum(z['a']['visitantes'] for z in zonas_data)
    dg        = calcular_delta(total_p, total_p_a)

    # 1. Resumen global del período
    if dg >= 10:
        items.append(("success", "fas fa-arrow-trend-up",
            f"El volumen total de tráfico creció un {dg:.0f}% respecto al {periodo_ant} anterior."))
    elif dg <= -10:
        items.append(("danger", "fas fa-arrow-trend-down",
            f"El volumen total de tráfico descendió un {abs(dg):.0f}% respecto al {periodo_ant} anterior."))
    else:
        items.append(("secondary", "fas fa-equals",
            f"El volumen total de tráfico se mantuvo estable respecto al {periodo_ant} anterior ({dg:+.0f}%)."))

    # 2. Día pico del período
    all_dias = pd.concat(
        [z['dias_p'] for z in zonas_data if not z['dias_p'].empty],
        ignore_index=True,
    ) if any(not z['dias_p'].empty for z in zonas_data) else pd.DataFrame()

    if not all_dias.empty:
        agg  = all_dias.groupby('fecha_dt')['unique_visitors'].sum().reset_index()
        peak = agg.loc[agg['unique_visitors'].idxmax()]
        items.append(("primary", "fas fa-calendar-day",
            f"El {formatear_fecha(peak['fecha_dt'])} fue el día con más afluencia del {periodo}, "
            f"con {int(peak['unique_visitors']):,} visitantes."))

    # 3. Estancia media
    est_p   = sum(z['r']['estancia'] * max(z['r']['visitantes'], 1) for z in zonas_data) / max(total_p,   1)
    est_p_a = sum(z['a']['estancia'] * max(z['a']['visitantes'], 1) for z in zonas_data) / max(total_p_a, 1)
    d_est   = calcular_delta(est_p, est_p_a)

    if est_p > 0 and abs(d_est) >= 6:
        if d_est > 0:
            items.append(("success", "fas fa-clock",
                f"El tiempo medio de permanencia aumentó a {est_p:.1f} min, frente a "
                f"{est_p_a:.1f} min del {periodo_ant} anterior."))
        else:
            items.append(("warning", "fas fa-clock",
                f"El tiempo medio de permanencia disminuyó a {est_p:.1f} min, frente a "
                f"{est_p_a:.1f} min del {periodo_ant} anterior. Se recomienda analizar los factores "
                f"que puedan estar reduciendo el tiempo de visita."))

    # 4. Alertas por zona
    for z in zonas_data:
        zn = z['zona']
        zl = zn.lower()
        dv = z['d']['visitantes']

        if 'exterior' in zl or 'calle' in zl:
            if dv <= -20:
                items.append(("warning", "fas fa-walking",
                    f"El tráfico exterior descendió un {abs(dv):.0f}% durante el {periodo}. "
                    f"Se recomienda verificar si existen factores externos que justifiquen la variación: "
                    f"obras, cortes de calle o condiciones meteorológicas adversas."))
        elif 'tienda' in zl:
            ext = next((z2 for z2 in zonas_data
                        if 'exterior' in z2['zona'].lower() or 'calle' in z2['zona'].lower()), None)
            if ext:
                ext_dv = ext['d']['visitantes']
                if dv <= -15 and ext_dv > -5:
                    items.append(("danger", "fas fa-store",
                        f"El tráfico exterior se mantuvo estable mientras la zona interior registró "
                        f"un descenso del {abs(dv):.0f}%. Se recomienda revisar los elementos de conversión: "
                        f"escaparate, señalética y disposición del acceso."))
                elif dv >= 15 and ext_dv < 5:
                    items.append(("success", "fas fa-store",
                        f"La zona interior registró un incremento del {dv:.0f}% con el tráfico exterior estable, "
                        f"lo que indica una mejora en la tasa de conversión del paso peatonal."))
            elif dv <= -15:
                items.append(("danger", "fas fa-store",
                    f"La zona interior registró un descenso del {abs(dv):.0f}% durante el {periodo}."))
        elif 'caja' in zl:
            if dv <= -15:
                items.append(("danger", "fas fa-cash-register",
                    f"El tráfico en zona de caja descendió un {abs(dv):.0f}% durante el {periodo}. "
                    f"Se recomienda contrastar con el tráfico interior para determinar si la variación "
                    f"obedece a una menor conversión o a una caída general de afluencia."))
            elif dv >= 15:
                items.append(("success", "fas fa-cash-register",
                    f"La zona de caja registró un incremento del {dv:.0f}% durante el {periodo}."))

    # 4b. Integridad de datos — alertas de nodo caído
    for z in zonas_data:
        zn = z['zona']
        if z.get('gap_actual'):
            items.append(("warning", "fas fa-wifi",
                f"La zona {zn} presenta días sin datos en el {periodo} actual. "
                f"Es posible que el nodo de captura haya estado temporalmente inactivo. "
                f"Los datos disponibles son parciales."))
        elif z.get('gap_anterior'):
            items.append(("info", "fas fa-circle-exclamation",
                f"El período de comparación de la zona {zn} incluye días sin datos registrados "
                f"(incidencia previa en el nodo). La variación mostrada "
                f"({z['d']['visitantes']:+.0f}%) puede estar sobreestimada."))

    # 5. Contexto externo: clima
    if clima:
        fmin_clima = fecha_max - timedelta(days=dias_v - 1)
        dias_rec   = {k: v for k, v in clima.items()
                      if k >= fmin_clima.strftime('%Y-%m-%d')}
        n_lluvia   = sum(1 for v in dias_rec.values() if v.get('precip', 0) > 2)
        umbral     = max(3, dias_v // 4)
        if n_lluvia >= umbral:
            items.append(("info", "fas fa-cloud-rain",
                f"Se registraron {n_lluvia} días de precipitaciones durante el {periodo}. "
                f"Este factor meteorológico puede haber influido en el descenso del tráfico exterior."))
        elif dias_rec:
            tmaxes = [v.get('tmax') for v in dias_rec.values() if v.get('tmax')]
            if tmaxes and max(tmaxes) > 33:
                items.append(("info", "fas fa-sun",
                    f"Durante el {periodo} se registraron temperaturas máximas de hasta {max(tmaxes):.0f}°C. "
                    f"Las altas temperaturas tienden a reducir el tráfico peatonal en las franjas horarias centrales del día."))

    # 6. Festivos
    fmin_fest = fecha_max - timedelta(days=dias_v - 1)
    fest = [(f, n) for f, n in festivos_espana.items()
            if isinstance(f, date) and fmin_fest <= f <= fecha_max]
    if fest:
        nombres = ", ".join(n for _, n in fest[:2])
        pl = "s" if len(fest) > 1 else ""
        items.append(("info", "fas fa-umbrella-beach",
            f"Durante el {periodo} se registró{'ron' if len(fest) > 1 else ''} {len(fest)} festivo{pl} ({nombres}). "
            f"Los datos de días festivos presentan patrones de tráfico diferenciados respecto a los días laborables."))

    # 7. Contexto geoespacial — insights AIS cuando disponibles
    if geo_vals:
        pob5        = geo_vals.get("poblacion_5min")
        gasto_ropa  = geo_vals.get("gasto_ropa_calzado")
        jovenes     = geo_vals.get("hogares_jovenes_solos")
        familias    = geo_vals.get("hogares_familias_hijos")
        renta_hogar = geo_vals.get("renta_hogar_anual")

        # Potencial de captación: visitantes vs población accesible
        if pob5 and total_p > 0:
            ratio_cap = total_p / pob5
            if ratio_cap < 0.015:
                items.append(("warning", "fas fa-map-marker-alt",
                    f"El área de influencia inmediata (5 min a pie) concentra {pob5:,.0f} personas. "
                    f"Con {total_p:,.0f} visitas registradas durante el {periodo}, la tasa de captación "
                    f"del entorno próximo es reducida, lo que sugiere margen de mejora en captación local."))
            elif ratio_cap > 0.10:
                items.append(("success", "fas fa-map-marker-alt",
                    f"La ubicación muestra una tasa de captación elevada: {total_p:,.0f} visitas "
                    f"registradas sobre un área de influencia de {pob5:,.0f} personas en 5 minutos a pie."))

        # Target demográfico Miniso
        if jovenes is not None and familias is not None:
            total_target = (jovenes or 0) + (familias or 0)
            if total_target > 600:
                items.append(("primary", "fas fa-users",
                    f"El área de influencia concentra {total_target:,.0f} hogares del segmento objetivo "
                    f"({jovenes:,.0f} residentes jóvenes y {familias:,.0f} familias con hijos), "
                    f"lo que indica una alta densidad de clientes potenciales en un radio de 800 m."))

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
                           style={"fontSize": "0.97rem", "color": _C_DARK,
                                  "lineHeight": "1.75", "paddingTop": "4px"}),
                ],
            )
        )
    if not rows:
        return html.Div()
    return dbc.Card(
        dbc.CardBody(html.Div(rows), className="px-4 py-2"),
        className="border-0 shadow-sm rounded-4 mb-4 bg-white",
    )


def _render_zona_card(zona, r, a, d, dias_28, uid, periodo_label="semana",
                      child_names=None, has_children=False,
                      gap_actual=False, gap_anterior=False):
    """Tarjeta de zona: % delta en grande (hero) + visitantes absolutos + sparkline."""
    color         = _color_zona(zona)
    badge_lbl, _, tooltip_role = _zona_meta(zona)
    zone_slug     = _slug(zona)
    badge_id      = f"pm-z-{zone_slug}-{uid}"
    spark_info_id = f"pm-spark-info-{zone_slug}-{uid}"
    gap_badge_id  = f"pm-gap-{zone_slug}-{uid}"

    dv = d['visitantes']
    if gap_actual:
        sem_color, arrow = _C_MUTED,  "fas fa-wifi"
        pct_str = "—"
    elif gap_anterior:
        sem_color, arrow = _C_AMBER, "fas fa-triangle-exclamation"
        pct_str = "—"
    elif dv >= 5:
        sem_color, arrow = _C_SUCCESS, "fas fa-arrow-up"
        pct_str = f"{dv:+.0f}%"
    elif dv <= -5:
        sem_color, arrow = _C_DANGER,  "fas fa-arrow-down"
        pct_str = f"{dv:+.0f}%"
    else:
        sem_color, arrow = _C_AMBER,   "fas fa-minus"
        pct_str = f"{dv:+.0f}%"

    abs_str  = f"{r['visitantes']:,.0f} visitantes"
    ant_str  = f" · ant. {a['visitantes']:,.0f}" if a['visitantes'] else ""
    dwell_str = f" · {r['estancia']:.1f} min estancia" if r['estancia'] > 0 else ""

    sparkline = _fig_sparkline(dias_28, color)

    # Badge de alerta de calidad de datos
    if gap_actual:
        gap_ui = html.Div(
            dbc.Badge([html.I(className="fas fa-wifi me-1"), "Sin datos suficientes"],
                      color="warning", text_color="dark", pill=True,
                      style={"fontSize": "0.62rem"}),
            className="mb-2",
        )
    elif gap_anterior:
        gap_ui = html.Div([
            dbc.Badge([html.I(className="fas fa-triangle-exclamation me-1"),
                       "Período anterior incompleto"],
                      id=gap_badge_id, color="warning", text_color="dark", pill=True,
                      style={"fontSize": "0.62rem", "cursor": "help"}),
            dbc.Tooltip(
                "El período de comparación incluye días sin datos registrados "
                "(posible incidencia en el nodo). La variación puede estar sobreestimada.",
                target=gap_badge_id, placement="top",
            ),
        ], className="mb-2")
    else:
        gap_ui = None

    return dbc.Card(
        dbc.CardBody([
            # Nombre + rol
            html.Div(className="d-flex align-items-center gap-2 mb-2", children=[
                html.Span(zona, className="fw-bold",
                          style={"fontSize": "0.80rem", "color": _C_DARK}),
                html.Span(id=badge_id, children=f"· {badge_lbl}",
                          className="text-muted",
                          style={"fontSize": "0.70rem", "cursor": "help"}),
                dbc.Tooltip(tooltip_role, target=badge_id, placement="top"),
            ]),
            # Badge de calidad de datos (solo cuando hay incidencia)
            *([gap_ui] if gap_ui else []),
            # % como métrica principal
            html.Div(className="d-flex align-items-baseline gap-1 mb-1", children=[
                html.Span(pct_str,
                          style={"fontSize": "2.4rem", "fontWeight": "800",
                                 "color": sem_color, "lineHeight": "1"}),
                html.I(className=f"{arrow} ms-1",
                       style={"color": sem_color, "fontSize": "1rem"}),
                html.Span(f"vs {periodo_label} ant.",
                          style={"fontSize": "0.74rem", "color": _C_MUTED, "marginLeft": "6px"}),
            ]),
            # Visitantes absolutos como subtítulo
            html.P(abs_str + ant_str + dwell_str,
                   className="text-muted mb-2",
                   style={"fontSize": "0.70rem", "lineHeight": "1.4"}),
            # Sparkline 28d
            html.Div([
                html.Div(className="d-flex justify-content-between align-items-center mb-1",
                         children=[
                    html.Span("Tendencia 28d",
                              style={"fontSize": "0.62rem", "color": _C_MUTED,
                                     "textTransform": "uppercase", "letterSpacing": "0.4px"}),
                    html.I(className="fas fa-circle-info", id=spark_info_id,
                           style={"color": _C_MUTED, "fontSize": "0.65rem", "cursor": "help"}),
                    dbc.Tooltip(
                        "Visitantes diarios · últimos 28 días. "
                        "Línea continua = tráfico real; línea punteada = tendencia "
                        "(verde = subiendo, roja = bajando).",
                        target=spark_info_id, placement="top",
                    ),
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
            # Child zone chips — shown only on parent zone cards
            *([html.Div([
                html.Span(
                    [html.I(className="fas fa-sitemap me-1"), "Subzonas: "],
                    style={"fontSize": "0.63rem", "color": _C_MUTED},
                ),
                *[dbc.Badge(
                    cn, color="light", text_color="secondary",
                    className="me-1 border",
                    style={"fontSize": "0.59rem"},
                ) for cn in child_names],
            ], className="mt-2 pt-2 border-top")] if child_names else []),
        ], className="p-3"),
        className="border-0 shadow-sm rounded-4 h-100",
        style={
            "borderTop": f"3px solid {color}",
            "overflow": "visible",
            **({"background": "rgba(0,82,204,0.04)"} if has_children else {}),
        },
    )


def _parse_hourly_pm(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        parsed = json.loads(str(val))
        if isinstance(parsed, list) and len(parsed) == 24:
            return [float(v) for v in parsed]
    except Exception:
        pass
    return None


def _fig_hora_pico(df_todas_zonas):
    """Distribución horaria promedio — todas las zonas y días disponibles."""
    if 'hourly_visits' not in df_todas_zonas.columns:
        return None
    acum = [0.0] * 24
    n = 0
    for val in df_todas_zonas['hourly_visits']:
        parsed = _parse_hourly_pm(val)
        if parsed:
            for h, v in enumerate(parsed):
                acum[h] += v
            n += 1
    if n == 0 or sum(acum) == 0:
        return None
    avg = [v / n for v in acum]
    max_v = max(avg) or 1
    peak_h = int(np.argmax(avg))
    colors = [f"rgba(0,82,204,{0.18 + 0.72 * v / max_v:.2f})" for v in avg]
    texts  = [f"<b>{int(v)}</b>" if i == peak_h else "" for i, v in enumerate(avg)]
    fig = go.Figure(go.Bar(
        x=[f"{h:02d}h" for h in range(24)],
        y=avg,
        marker=dict(color=colors, line=dict(width=0)),
        text=texts, textposition='outside',
        textfont=dict(size=10, color=_C_DARK),
        hovertemplate='%{x}: <b>%{y:.0f}</b> visitas/hora (media)<extra></extra>',
    ))
    fig.update_layout(
        height=180, margin=dict(t=20, b=8, l=8, r=8),
        xaxis=dict(showgrid=False, tickfont=dict(size=9, color=_C_DARK),
                   fixedrange=True, tickangle=0),
        yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.35]),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False, bargap=0.12,
    )
    return fig


def _fig_nuevos_ratio(df_todas_zonas, fecha_max, dias=7):
    """% de visitantes nuevos sobre el total — evolución diaria."""
    if 'new_visitors' not in df_todas_zonas.columns or 'unique_visitors' not in df_todas_zonas.columns:
        return None
    fmin = fecha_max - timedelta(days=dias - 1)
    df = df_todas_zonas[
        (df_todas_zonas['fecha_dt'] >= fmin) &
        (df_todas_zonas['fecha_dt'] <= fecha_max)
    ].copy()
    if df.empty:
        return None
    por_dia = df.groupby('fecha_dt').agg(
        nuevos=('new_visitors',    'sum'),
        total =('unique_visitors', 'sum'),
    ).reset_index()
    por_dia = por_dia[por_dia['total'] > 0]
    if por_dia.empty:
        return None
    por_dia['pct'] = (por_dia['nuevos'] / por_dia['total'] * 100).clip(0, 100)
    media = por_dia['pct'].mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=por_dia['fecha_dt'], y=por_dia['pct'],
        mode='lines+markers',
        fill='tozeroy', fillcolor='rgba(0,82,204,0.07)',
        line=dict(color=_C_PRIMARY, width=2),
        marker=dict(size=5),
        hovertemplate='%{x}: <b>%{y:.0f}%</b> nuevos<extra></extra>',
    ))
    fig.add_hline(y=media, line_dash='dot', line_color=_C_MUTED,
                  annotation_text=f"Media {media:.0f}%",
                  annotation_position="top right",
                  annotation_font=dict(size=10, color=_C_MUTED))
    fig.update_layout(
        height=180, margin=dict(t=20, b=8, l=8, r=8),
        xaxis=dict(showgrid=False, tickfont=dict(size=10, color=_C_DARK), fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, 115]),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
    )
    return fig


def _fig_semanas_mes(df, fecha_max):
    """Visitantes totales por semana — desglose del último mes."""
    if df.empty or 'unique_visitors' not in df.columns:
        return None
    fmin = fecha_max - timedelta(days=27)
    df_m = df[(df['fecha_dt'] >= fmin) & (df['fecha_dt'] <= fecha_max)].copy()
    if df_m.empty:
        return None
    df_m['fecha_ts'] = pd.to_datetime(df_m['fecha_dt'])
    df_m['sem'] = df_m['fecha_ts'].dt.to_period('W')
    por_sem = df_m.groupby('sem')['unique_visitors'].sum().sort_index()
    if por_sem.empty or len(por_sem) < 2:
        return None

    n      = len(por_sem)
    labels = [f"Sem {i + 1}" for i in range(n)]
    hover  = [f"{p.start_time.strftime('%d/%m')}–{p.end_time.strftime('%d/%m')}"
              for p in por_sem.index]
    values = por_sem.values.tolist()
    opacities = [0.28 + 0.72 * (i / max(n - 1, 1)) for i in range(n)]
    colors = [f"rgba(0,82,204,{op:.2f})" for op in opacities]

    max_v = max(values) if values else 1
    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker=dict(color=colors, line=dict(width=0)),
        text=[f"<b>{int(v):,}</b>" for v in values],
        textposition='outside',
        textfont=dict(size=11, color=_C_DARK),
        customdata=hover,
        hovertemplate='%{x} (%{customdata}): <b>%{y:,.0f}</b> visitantes<extra></extra>',
        cliponaxis=False,
    ))
    fig.update_layout(
        height=180,
        margin=dict(t=20, b=8, l=8, r=8),
        xaxis=dict(showgrid=False, tickfont=dict(size=12, color=_C_DARK), fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.30]),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
        bargap=0.35,
    )
    return fig


def _render_pm_questions(df, zonas_data, fecha_max, uid, ventana="semana", child_zones=None):
    """
    Responde gráficamente las preguntas habituales de un PM sobre el tráfico.
    Cada carta tiene una pregunta en lenguaje natural + gráfico directo.
    Los gráficos segmentados por zona usan solo zonas padre.
    """
    def _q_card(pregunta, subtitulo, fig, gid, height):
        if fig is None:
            return None
        return dbc.Card(
            dbc.CardBody([
                html.P(
                    pregunta,
                    className="fw-bold mb-0",
                    style={"fontSize": "0.96rem", "color": _C_DARK},
                ),
                html.P(subtitulo, className="text-muted mb-2",
                       style={"fontSize": "0.78rem", "lineHeight": "1.4"}),
                dcc.Graph(
                    id=gid, figure=fig, config=_CFG_GRAPH,
                    style={"height": height},
                ),
            ], className="px-4 py-3"),
            className="border-0 shadow-sm rounded-4 h-100 bg-white",
        )

    _cz = child_zones or set()
    zonas_top = [z for z in zonas_data if z['zona'] not in _cz] or zonas_data
    df_top = df[~df['Zona'].isin(_cz)].copy() if _cz else df

    dias_v = 28 if ventana == "mes" else 7
    _periodo       = "último mes (28 días)"    if ventana == "mes" else "última semana (7 días)"
    _periodo_corto = "último mes"              if ventana == "mes" else "última semana"
    _lbl_dias      = "Media por día · último mes" if ventana == "mes" else "Visitantes por día · esta semana"

    preguntas = []

    # Gráfico semana-a-semana: solo en modo mes
    if ventana == "mes":
        preguntas.append((
            _fig_semanas_mes(df, fecha_max),
            f"q-semanas-{uid}",
            "¿Cómo evolucionó el tráfico semana a semana?",
            "Visitantes por semana · último mes · de izquierda (más antigua) a derecha (más reciente)",
            "180px",
        ))

    preguntas += [
        (
            _fig_dias_semana(df, fecha_max, dias=dias_v),
            f"q-dias-{uid}",
            "¿Cuándo llegan los visitantes?",
            f"{_lbl_dias} · tono más oscuro = día pico",
            "160px",
        ),
        (
            _fig_hora_pico(df_top),
            f"q-hora-{uid}",
            "¿A qué hora llegan?",
            f"Distribución horaria promedio · zonas principales · tono más oscuro = hora pico",
            "180px",
        ),
        (
            _fig_finde_vs_laborable(df, fecha_max, dias=dias_v),
            f"q-finde-{uid}",
            "¿Rinde mejor el fin de semana o entre semana?",
            f"Visitantes/día (media) · {_periodo}",
            "180px",
        ),
        (
            _fig_nuevos_ratio(df_top, fecha_max, dias=dias_v),
            f"q-nuevos-{uid}",
            "¿Cuántos visitantes son nuevos?",
            f"% de visitantes nuevos sobre el total · {_periodo} · línea punteada = media del período",
            "180px",
        ),
        (
            _fig_dwell_zonas(zonas_top, child_zones=_cz),
            f"q-dwell-{uid}",
            "¿Cuánto tiempo se quedan?",
            f"Tiempo medio de permanencia por zona principal · {_periodo_corto}",
            "180px",
        ),
        (
            _fig_embudo_conversion(zonas_top),
            f"q-embudo-{uid}",
            "¿Cuántos visitantes convierten?",
            f"Visitantes por etapa · {_periodo_corto} · % respecto al paso anterior",
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

    _v_lbl = "últimos 28 días" if ventana == "mes" else "últimos 7 días"
    return html.Div([
        html.H5(
            [html.I(className="fas fa-magnifying-glass me-2 text-primary"),
             "Patrones de comportamiento"],
            className="fw-bold mb-1",
            style={"fontSize": "1.15rem", "color": _C_DARK},
        ),
        html.P(
            f"Distribución del tráfico por día y tipo de jornada · {_v_lbl}.",
            className="text-muted mb-3",
            style={"fontSize": "0.84rem"},
        ),
        dbc.Row(cols, className="g-3"),
    ], className="mb-4")


# ── Eventos externos ─────────────────────────────────────────────────────────

_UNIVERSAL_KEYS = frozenset({
    'ev_festivo_regional', 'ev_rank_concierto', 'ev_rank_deportivo',
    'ev_rank_festival', 'ev_rank_municipal', 'ev_rank_total',
    'llueve', 'temp_max', 'temp_min',
})

_FEATURE_META = {
    'n_pasajeros_crucero_dia':  ('Pasajeros de crucero',    'pax totales',        'sum', '#1abc9c'),
    'n_turistas_isocrona':      ('Turistas en isócrona',    'pers. estimadas',    'sum', '#3498db'),
    'n_eventos_gran_via':       ('Eventos Gran Vía',         'eventos en rango',   'sum', '#9b59b6'),
    'afluencia_metro_gran_via': ('Metro Gran Vía',           'viajeros validados', 'sum', '#e67e22'),
    'afluencia_metro_callao':   ('Metro Callao',             'viajeros validados', 'sum', '#00539B'),
    'ev_vacaciones_escolares':  ('Vacaciones escolares',     'días en el mes',     'sum', '#8e44ad'),
    'cal_escolar_is_break':     ('Período vacacional',       'días en el mes',     'sum', '#8e44ad'),
    'cal_escolar_dias_hasta':   ('Días hasta próx. vacaciones', 'días (media)',    'mean','#8e44ad'),
}
_DEFAULT_COLOR = '#0052CC'


def _render_eventos_externos(location_uuid: str, fecha_max) -> html.Div | None:
    """
    Sección 'Contexto externo': agrega por semana y mes las features de
    store_features_ext exclusivas de la ubicación (excluye features universales).
    Devuelve None si no hay datos.
    """
    try:
        from src.db.store import get_conn
        conn = get_conn()

        desde = fecha_max - timedelta(days=119)  # ~4 meses para cubrir 4 semanas + 3 meses
        rows = conn.execute(
            """SELECT feature_key, fecha::text, value
               FROM   store_features_ext
               WHERE  location_uuid = ?
                 AND  value IS NOT NULL
                 AND  fecha >= ?
               ORDER  BY feature_key, fecha""",
            [location_uuid, str(desde.date() if hasattr(desde, 'date') else desde)],
        ).fetchall()
    except Exception:
        return None

    if not rows:
        return None

    df_ext = pd.DataFrame(rows, columns=['feature_key', 'fecha', 'value'])
    df_ext['fecha'] = pd.to_datetime(df_ext['fecha'])

    keys_loc = [k for k in df_ext['feature_key'].unique() if k not in _UNIVERSAL_KEYS]
    if not keys_loc:
        return None

    df_ext = df_ext[df_ext['feature_key'].isin(keys_loc)].copy()
    df_ext['semana_iso'] = df_ext['fecha'].dt.to_period('W').dt.start_time
    df_ext['mes']        = df_ext['fecha'].dt.to_period('M').dt.to_timestamp()

    _MESES_ES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

    feature_cards = []
    for fk in sorted(keys_loc):
        meta   = _FEATURE_META.get(fk, (fk.replace('_', ' ').title(), '', 'sum', _DEFAULT_COLOR))
        label, unidad, agg_fn, color = meta

        df_k = df_ext[df_ext['feature_key'] == fk]

        # ── Semanas (últimas 4 completas) ──────────────────────────────
        sem_agg = (df_k.groupby('semana_iso')['value']
                   .agg(agg_fn).reset_index()
                   .sort_values('semana_iso').tail(5))
        sem_labels = [f"S{r.isocalendar()[1]}" for r in sem_agg['semana_iso'].dt.date]
        sem_vals   = sem_agg['value'].tolist()

        # ── Meses (últimos 3) ──────────────────────────────────────────
        mes_agg = (df_k.groupby('mes')['value']
                   .agg(agg_fn).reset_index()
                   .sort_values('mes').tail(4))
        mes_labels = [f"{_MESES_ES[r.month - 1]} {r.year}" for r in mes_agg['mes'].dt.date]
        mes_vals   = mes_agg['value'].tolist()

        def _bar_fig(x_vals, y_vals, title):
            fig = go.Figure(go.Bar(
                x=x_vals, y=y_vals,
                marker_color=color, opacity=0.85,
                text=[f"<b>{int(v):,}</b>" if v >= 1 else f"<b>{v:.1f}</b>" for v in y_vals],
                textposition='outside',
                textfont=dict(size=10, color='#2c3e50'),
            ))
            fig.update_layout(
                title=dict(text=title, font=dict(size=11, color='#7f8c8d'), x=0),
                plot_bgcolor='white', paper_bgcolor='white',
                margin=dict(t=30, b=10, l=10, r=10),
                xaxis=dict(showgrid=False, tickfont=dict(size=10)),
                yaxis=dict(showgrid=True, gridcolor='#f0f0f0', visible=False),
                height=150,
            )
            return fig

        gid_sem = f"ext-{location_uuid[:8]}-{fk}-sem"
        gid_mes = f"ext-{location_uuid[:8]}-{fk}-mes"

        fig_sem = _bar_fig(sem_labels, sem_vals, 'Por semana') if sem_vals else None
        fig_mes = _bar_fig(mes_labels, mes_vals, 'Por mes')   if mes_vals else None

        # KPI rápido: última semana vs anterior
        delta_badge = html.Span()
        if len(sem_vals) >= 2 and sem_vals[-2] > 0:
            pct = (sem_vals[-1] - sem_vals[-2]) / sem_vals[-2] * 100
            color_b = '#27ae60' if pct > 0 else '#e74c3c'
            flecha  = '▲' if pct > 0 else '▼'
            delta_badge = html.Span(
                f"{flecha} {pct:+.1f}% vs semana ant.",
                style={'color': color_b, 'fontSize': '0.75rem', 'fontWeight': '600'},
            )

        val_ult = f"{int(sem_vals[-1]):,}" if sem_vals and sem_vals[-1] >= 1 else (f"{sem_vals[-1]:.2f}" if sem_vals else '—')
        unidad_txt = f" {unidad}" if unidad else ''

        header_row = html.Div([
            html.I(className="fas fa-satellite-dish me-2", style={'color': color}),
            html.Span(label, className="fw-bold me-2", style={'fontSize': '0.9rem', 'color': '#2c3e50'}),
            html.Span([val_ult, unidad_txt, ' esta semana'], className="text-muted me-2",
                      style={'fontSize': '0.78rem'}),
            delta_badge,
        ], className="d-flex align-items-center flex-wrap gap-1 mb-2")

        graficos = dbc.Row([
            dbc.Col(dcc.Graph(id=gid_sem, figure=fig_sem, config={'displayModeBar': False},
                              style={'height': '150px'}) if fig_sem else html.Div(), xs=12, md=6),
            dbc.Col(dcc.Graph(id=gid_mes, figure=fig_mes, config={'displayModeBar': False},
                              style={'height': '150px'}) if fig_mes else html.Div(), xs=12, md=6),
        ], className="g-2")

        feature_cards.append(html.Div([header_row, graficos], className="mb-3"))

    if not feature_cards:
        return None

    return html.Div([
        html.Div([
            html.I(className="fas fa-broadcast-tower me-2 text-primary"),
            html.Span("Contexto externo", className="fw-bold text-dark",
                      style={'fontSize': '1rem'}),
        ], className="d-flex align-items-center border-bottom pb-2 mb-3"),
        html.Div(feature_cards),
    ], className="mb-4 p-3 bg-white rounded-4 shadow-sm border")


# ── Shared zone-ordering helper ───────────────────────────────────────────────

def _orden_zona(zona: str) -> int:
    zl = zona.lower()
    if 'exterior' in zl or 'calle' in zl: return 0
    if 'tienda' in zl:                    return 1
    if 'caja' in zl:                      return 2
    return 3


# ── New "Estado" redesign helpers ─────────────────────────────────────────────

def _hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


_FEATURE_FA_ICONS = {
    'afluencia_metro_gran_via':  'fas fa-train-subway',
    'afluencia_metro_callao':    'fas fa-train-subway',
    'n_turistas_isocrona':       'fas fa-passport',
    'n_pasajeros_crucero_dia':   'fas fa-ship',
    'n_eventos_gran_via':        'fas fa-calendar-check',
    'ev_vacaciones_escolares':   'fas fa-school',
    'cal_escolar_is_break':      'fas fa-school',
    'cal_escolar_dias_hasta':    'fas fa-school',
}


def _icon_for_feature(fk: str) -> str:
    return _FEATURE_FA_ICONS.get(fk, 'fas fa-satellite-dish')


def _render_signal_yoy_chart(df_k, fk, label, sublabel, color, uid,
                              anio_actual, anio_prev, meses_es, agg_fn):
    """Grouped-bar chart with current year (solid) and prior year (translucent)."""
    mes_pivot = df_k.groupby(['anio', 'mes_num'])['value'].agg(agg_fn).reset_index()

    meses_actuales = sorted(mes_pivot[mes_pivot['anio'] == anio_actual]['mes_num'].unique())
    if not meses_actuales:
        return None

    x_labels = [meses_es[m - 1] for m in meses_actuales]

    def _get(anio, mes):
        row = mes_pivot[(mes_pivot['anio'] == anio) & (mes_pivot['mes_num'] == mes)]
        return float(row['value'].iloc[0]) if not row.empty else 0.0

    y_actual = [_get(anio_actual, m) for m in meses_actuales]
    y_prev   = [_get(anio_prev,   m) for m in meses_actuales]
    has_prev = any(v > 0 for v in y_prev)

    fig = go.Figure()
    if has_prev:
        fig.add_trace(go.Bar(
            name=str(anio_prev), x=x_labels, y=y_prev,
            marker_color=color, opacity=0.15,
            marker_line_width=1, marker_line_color=color,
            hoverinfo='skip', showlegend=False,
        ))
    fig.add_trace(go.Bar(
        name=str(anio_actual), x=x_labels, y=y_actual,
        marker_color=color, opacity=0.9,
        text=[f"<b>{int(v):,}</b>" if v > 0 else "" for v in y_actual],
        textposition='outside', textfont=dict(size=9, color=_C_DARK),
        hovertemplate=f'{anio_actual} · %{{x}}: <b>%{{y:,.0f}}</b><extra></extra>',
    ))

    max_v = max([max(y_actual or [0]), max(y_prev or [0])]) or 1
    fig.update_layout(
        barmode='group', height=210,
        margin=dict(t=44, b=10, l=10, r=10),
        plot_bgcolor='white', paper_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(showgrid=False, tickfont=dict(size=10, color=_C_DARK), fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.45]),
        showlegend=False,
        bargap=0.28,
    )
    return html.Div([
        html.Div([
            html.I(className=f"{_icon_for_feature(fk)} me-2",
                   style={'color': color, "fontSize": "0.9rem"}),
            html.Span(label, className="fw-semibold me-1",
                      style={'fontSize': '0.9rem', 'color': _C_DARK}),
            html.Span(sublabel, className="text-muted",
                      style={'fontSize': '0.74rem'}),
        ], className="d-flex align-items-center mb-2"),
        dcc.Graph(id=f"yoy-{uid}-{fk[:16]}", figure=fig, config=_CFG_GRAPH,
                  style={"height": "210px"}),
    ], className="mb-4")


_SRC_COLOR: dict = {
    'concierto_wizink':       '#e74c3c',
    'estreno_callao':         '#8e44ad',
    'festival_madrid':        '#f39c12',
    'manifestacion_gran_via': '#e67e22',
    'partido_deportivo':      '#3498db',
    'festivo_regional':       '#27ae60',
    'vacaciones_escolares':   '#9b59b6',
    'crucero':                '#1abc9c',
}
_SRC_LABEL: dict = {
    'concierto_wizink':       'Concierto',
    'estreno_callao':         'Estreno',
    'festival_madrid':        'Festival',
    'manifestacion_gran_via': 'Manifestación',
    'partido_deportivo':      'Deportivo',
    'festivo_regional':       'Festivo',
    'vacaciones_escolares':   'Vacaciones',
    'crucero':                'Crucero',
}


def _render_calendario_eventos_clima(location_uuid: str, fecha_max) -> html.Div | None:
    """
    CSS-grid calendar split by month. Each day cell: climate icons + one tag per
    event source (calendar events + cruise calls). Legend maps colors to sources.
    """
    import calendar as _cal
    try:
        from src.db.store import get_conn
        conn = get_conn()
        hoy_d   = fecha_max.date() if hasattr(fecha_max, 'date') else fecha_max
        desde_d = hoy_d - timedelta(days=56)
        hasta_d = hoy_d + timedelta(days=28)
        ev_rows = conn.execute(
            """SELECT evento_key, fecha_inicio, metadata
               FROM store_calendario_org
               WHERE location_uuid = ? AND fecha_fin >= ? AND fecha_inicio <= ?
               ORDER BY fecha_inicio""",
            [location_uuid, str(desde_d), str(hasta_d)],
        ).fetchall()
        cl_rows = conn.execute(
            """SELECT feature_key, fecha::text, value
               FROM store_features_ext
               WHERE location_uuid = ? AND feature_key IN ('llueve','temp_max','temp_min')
                 AND fecha >= ? AND fecha <= ?""",
            [location_uuid, str(desde_d), str(hasta_d)],
        ).fetchall()
        # Cruise calls
        crucero_rows: list = []
        try:
            crucero_rows = conn.execute(
                """SELECT fecha::text, nombre_barco, operador
                   FROM store_crucero_llamadas
                   WHERE location_uuid = ? AND fecha >= ? AND fecha <= ?
                   ORDER BY fecha""",
                [location_uuid, str(desde_d), str(hasta_d)],
            ).fetchall()
        except Exception:
            pass
    except Exception:
        return None

    _IMPACT = {'alto': 3, 'medio': 2, 'bajo': 1}
    _CLEAN  = str.maketrans({'—': ' ', '–': ' '})

    # day_events: date → list of {source, titulo, icono_fa, score}
    day_events: dict = {}
    for key, fi, meta_json in ev_rows:
        fi_d = pd.to_datetime(fi).date()
        meta = meta_json if isinstance(meta_json, dict) else (json.loads(meta_json) if meta_json else {})
        is_vac = 'vacaciones' in key.lower()
        # Normalize source for color lookup — any crucero-like key maps to 'crucero'
        src_key = 'crucero' if 'crucero' in key.lower() else key
        titulo_raw = meta.get('titulo', meta.get('nombre', key.replace('_', ' ').title()))
        day_events.setdefault(fi_d, []).append(dict(
            source=src_key,
            titulo=titulo_raw.translate(_CLEAN).strip(),
            icono_fa=meta.get('icono_fa', 'fas fa-calendar-day'),
            is_vacation=is_vac,
            score=0.5 if is_vac else float(_IMPACT.get(meta.get('impacto', ''), 1)),
        ))

    # Inject cruise calls as calendar events (source='crucero')
    _CLEAN_T = str.maketrans({'—': ' ', '–': ' '})
    for fecha_s, nombre, operador in crucero_rows:
        fi_d = pd.to_datetime(fecha_s).date()
        day_events.setdefault(fi_d, []).append(dict(
            source='crucero',
            titulo=(nombre or operador or 'Crucero').translate(_CLEAN_T).strip(),
            icono_fa='fas fa-ship',
            is_vacation=False,
            score=1.5,
        ))

    clima: dict = {}
    for fk, fecha, val in cl_rows:
        d = pd.to_datetime(fecha).date()
        clima.setdefault(d, {})[fk] = val

    if not day_events and not clima:
        return None

    _MES_ES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
               'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
    DIAS_HDR = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']

    months = []
    y, m = desde_d.year, desde_d.month
    while date(y, m, 1) <= hasta_d:
        months.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1

    def _ev_tag(ev):
        c = _SRC_COLOR.get(ev['source'], '#7f8c8d')
        lbl = _SRC_LABEL.get(ev['source'], ev['source'].replace('_', ' ').title())
        short = ev['titulo'][:18] + ('…' if len(ev['titulo']) > 18 else '')
        return html.Div([
            html.Span(style={"display": "inline-block", "width": "7px", "height": "7px",
                             "borderRadius": "50%", "background": c, "flexShrink": "0",
                             "marginTop": "2px"}),
            html.Span(f"{lbl} · {short}",
                      style={"fontSize": "0.60rem", "lineHeight": "1.2",
                             "color": '#2c3e50', "fontWeight": "500"}),
        ], className="d-flex align-items-start gap-1 mt-1")

    def _day_cell(d):
        is_today = d == hoy_d
        evs  = day_events.get(d, [])
        acts = sorted([e for e in evs if not e['is_vacation']],
                      key=lambda e: -e['score'])
        vac  = [e for e in evs if e['is_vacation']]

        # Border and background from top event's source
        if acts:
            bc = _SRC_COLOR.get(acts[0]['source'], '#7f8c8d')
            bg = _hex_rgba(bc, 0.06)
        elif vac:
            bc, bg = '#9b59b6', '#f3e5f5'
        else:
            bg = '#ffffff'
            bc = _C_PRIMARY if is_today else '#e9ecef'

        cl   = clima.get(d, {})
        tmax = cl.get('temp_max', None)
        tmin = cl.get('temp_min', None)
        lluv = cl.get('llueve', 0) or 0
        if lluv > 0:
            w_cls, w_col = 'fas fa-cloud-showers-heavy', '#3498db'
        elif tmax is not None and tmax >= 25:
            w_cls, w_col = 'fas fa-sun', '#f39c12'
        elif tmax is not None and tmax < 12:
            w_cls, w_col = 'fas fa-snowflake', '#74b9ff'
        else:
            w_cls, w_col = 'fas fa-cloud-sun', '#95a5a6'
        temp_txt = (f"{round(tmax)}°/{round(tmin)}°"
                    if tmax is not None and tmin is not None else "")

        num_color = _C_PRIMARY if is_today else (_C_DARK if d <= hoy_d else '#555')
        cell_style = {
            "background": bg, "borderLeft": f"3px solid {bc}",
            "minHeight": "130px", "padding": "6px 8px", "borderRadius": "4px",
        }
        if is_today:
            cell_style["boxShadow"] = f"0 0 0 2px {_C_PRIMARY}"

        ev_content: list = [_ev_tag(e) for e in acts[:3]]
        if len(acts) > 3:
            ev_content.append(html.Div(
                f"+{len(acts) - 3} más",
                style={"fontSize": "0.57rem", "color": _C_MUTED, "marginLeft": "10px"},
            ))
        if not acts and vac:
            ev_content.append(html.Div(
                html.I(className="fas fa-school",
                       style={"color": "#9b59b6", "fontSize": "0.62rem"}),
                style={"marginTop": "3px"},
            ))

        return html.Div([
            html.Div([
                html.Span(str(d.day),
                          style={"fontSize": "0.88rem", "fontWeight": "700",
                                 "color": num_color}),
                html.I(className=f"{w_cls} ms-1", title=temp_txt,
                       style={"color": w_col, "fontSize": "0.72rem"}),
                html.Span(temp_txt, className="ms-1 text-muted",
                          style={"fontSize": "0.60rem"}),
            ], className="d-flex align-items-center"),
            *ev_content,
        ], style=cell_style)

    header_row = [
        html.Div(lbl, className="text-center fw-bold py-1 text-secondary bg-light",
                 style={"fontSize": "0.70rem", "textTransform": "uppercase",
                        "letterSpacing": "0.5px", "borderRadius": "3px"})
        for lbl in DIAS_HDR
    ]

    tabs_meses = []
    for (y, m) in months:
        primer_dia = date(y, m, 1)
        ultimo_dia = date(y, m, _cal.monthrange(y, m)[1])
        grid_start = primer_dia - timedelta(days=primer_dia.weekday())
        grid_end   = ultimo_dia + timedelta(days=6 - ultimo_dia.weekday())

        cells = list(header_row)
        d_iter = grid_start
        while d_iter <= grid_end:
            if d_iter.month != m:
                cells.append(html.Div(style={
                    "minHeight": "130px", "background": "#f8f9fa",
                    "borderRadius": "4px", "opacity": "0.4",
                }))
            else:
                cells.append(_day_cell(d_iter))
            d_iter += timedelta(days=1)

        grilla = html.Div(cells, style={
            "display": "grid",
            "gridTemplateColumns": "repeat(7, 1fr)",
            "gap": "8px",
        })
        tab_id  = f"tab-{y}-{m}"
        tab_lbl = _MES_ES[m - 1] if y == hoy_d.year else f"{_MES_ES[m - 1]} {y}"
        tabs_meses.append(dbc.Tab(
            html.Div(grilla, className="pt-3"),
            label=tab_lbl, tab_id=tab_id, className="fw-bold",
        ))

    # Legend by source (only sources present in the current window)
    present_sources = {e['source']
                       for evs in day_events.values()
                       for e in evs}
    present_sources.discard('vacaciones_escolares')  # shown via icon
    legend_items = []
    for src in ['crucero','concierto_wizink','estreno_callao','festival_madrid',
                'partido_deportivo','manifestacion_gran_via','festivo_regional']:
        if src not in present_sources:
            continue
        c = _SRC_COLOR[src]
        legend_items.append(html.Div([
            html.Span(style={"display": "inline-block", "width": "8px", "height": "8px",
                             "borderRadius": "50%", "background": c, "marginRight": "4px"}),
            html.Span(_SRC_LABEL[src], style={"fontSize": "0.67rem", "color": _C_MUTED}),
        ], className="d-flex align-items-center me-3"))

    # Always show clima icons in legend
    legend_items.append(html.Div([
        html.I(className="fas fa-cloud-showers-heavy me-1",
               style={"color": "#3498db", "fontSize": "0.67rem"}),
        html.I(className="fas fa-sun me-1",
               style={"color": "#f39c12", "fontSize": "0.67rem"}),
        html.I(className="fas fa-snowflake me-1",
               style={"color": "#74b9ff", "fontSize": "0.67rem"}),
        html.I(className="fas fa-cloud-sun",
               style={"color": "#95a5a6", "fontSize": "0.67rem"}),
    ], className="d-flex align-items-center"))

    active_tab = f"tab-{hoy_d.year}-{hoy_d.month}"
    if tabs_meses and active_tab not in {t.tab_id for t in tabs_meses}:
        active_tab = tabs_meses[-1].tab_id

    return html.Div([
        html.H6("Calendario del entorno", className="fw-bold mb-2",
                style={"color": _C_DARK, "fontSize": "0.98rem"}),
        html.Div(legend_items, className="d-flex flex-wrap gap-1 mb-3"),
        dbc.Tabs(tabs_meses, active_tab=active_tab),
    ])


def _render_cruceros_section(location_uuid: str, fecha_max) -> html.Div | None:
    """Monthly YoY passenger comparison for cruise locations."""
    try:
        from src.db.store import get_conn
        conn = get_conn()
        desde_yoy = fecha_max - timedelta(days=760)
        yoy_rows = conn.execute(
            """SELECT e.fecha::text, e.value
               FROM store_features_ext e
               JOIN feature_flags f ON f.feature_key = e.feature_key
                 AND f.location_uuid = e.location_uuid AND f.status = 'active'
               WHERE e.location_uuid = ? AND e.feature_key = 'n_pasajeros_crucero_dia'
                 AND e.value IS NOT NULL AND e.fecha >= ?
               ORDER BY e.fecha""",
            [location_uuid,
             str(desde_yoy.date() if hasattr(desde_yoy, 'date') else desde_yoy)],
        ).fetchall()
    except Exception:
        return None

    if not yoy_rows:
        return None

    _MESES_ES = ['Ene','Feb','Mar','Abr','May','Jun',
                 'Jul','Ago','Sep','Oct','Nov','Dic']
    color = '#1abc9c'

    children: list = [
        html.Div([
            html.I(className="fas fa-ship me-2", style={'color': color}),
            html.Span("Pasajeros de crucero", className="fw-bold",
                      style={'fontSize': '0.9rem', 'color': _C_DARK}),
        ], className="d-flex align-items-center mb-3"),
    ]

    if yoy_rows:
        df_y = pd.DataFrame(yoy_rows, columns=['fecha', 'value'])
        df_y['fecha']   = pd.to_datetime(df_y['fecha'])
        df_y['anio']    = df_y['fecha'].dt.year
        df_y['mes_num'] = df_y['fecha'].dt.month

        anio_actual = (fecha_max.year if hasattr(fecha_max, 'year')
                       else pd.Timestamp(fecha_max).year)
        anio_prev   = anio_actual - 1

        mes_pivot = df_y.groupby(['anio', 'mes_num'])['value'].sum().reset_index()
        meses_act = sorted(
            mes_pivot[mes_pivot['anio'] == anio_actual]['mes_num'].unique()
        )
        if meses_act:
            xl = [_MESES_ES[m - 1] for m in meses_act]

            def _gv(yr, m):
                r = mes_pivot[
                    (mes_pivot['anio'] == yr) & (mes_pivot['mes_num'] == m)
                ]
                return float(r['value'].iloc[0]) if not r.empty else 0.0

            y_act  = [_gv(anio_actual, m) for m in meses_act]
            y_prev = [_gv(anio_prev,   m) for m in meses_act]
            has_p  = any(v > 0 for v in y_prev)

            fig = go.Figure()
            if has_p:
                fig.add_trace(go.Bar(
                    x=xl, y=y_prev,
                    marker_color=color, opacity=0.15,
                    marker_line_width=1, marker_line_color=color,
                    hoverinfo='skip', showlegend=False,
                ))
            fig.add_trace(go.Bar(
                x=xl, y=y_act,
                marker_color=color, opacity=0.9,
                text=[f"<b>{int(v):,}</b>" if v > 0 else "" for v in y_act],
                textposition='outside', textfont=dict(size=9, color=_C_DARK),
                hovertemplate=f'{anio_actual} · %{{x}}: <b>%{{y:,.0f}}</b> pax<extra></extra>',
            ))
            max_v = max([max(y_act or [0]), max(y_prev or [0])]) or 1
            sub   = (f"pax/mes · {anio_actual} (sólido) vs {anio_prev} (translúcido)"
                     if has_p else f"pax/mes · {anio_actual}")
            fig.update_layout(
                barmode='group', height=200,
                margin=dict(t=30, b=10, l=10, r=10),
                plot_bgcolor='white', paper_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=False, tickfont=dict(size=10), fixedrange=True),
                yaxis=dict(visible=False, fixedrange=True, range=[0, max_v * 1.45]),
                showlegend=False,
                title=dict(text=sub, font=dict(size=10, color='#7f8c8d'), x=0),
            )
            children.append(
                dcc.Graph(id=f"crucero-yoy-{location_uuid[:8]}",
                          figure=fig, config=_CFG_GRAPH,
                          style={"height": "200px"})
            )

    return html.Div(children, className="mb-4") if len(children) > 1 else None


def _render_senal_contexto_modal(location_uuid: str, uid: str, fecha_max) -> html.Div | None:
    """External signals modal: YoY bar charts per feature + events feed."""
    if not location_uuid:
        return None
    try:
        from src.db.store import get_conn
        conn = get_conn()
        desde = fecha_max - timedelta(days=760)
        ts_rows = conn.execute(
            """SELECT e.feature_key, e.fecha::text, e.value
               FROM store_features_ext e
               JOIN feature_flags f
                 ON f.feature_key = e.feature_key
                AND f.location_uuid = e.location_uuid
                AND f.status = 'active'
               WHERE e.location_uuid = ? AND e.value IS NOT NULL AND e.fecha >= ?
               ORDER BY e.feature_key, e.fecha""",
            [location_uuid, str(desde)],
        ).fetchall()
    except Exception:
        return None

    _MESES_ES = ['Ene','Feb','Mar','Abr','May','Jun',
                 'Jul','Ago','Sep','Oct','Nov','Dic']
    anio_actual = fecha_max.year
    anio_prev   = anio_actual - 1

    charts = []
    if ts_rows:
        df_ts = pd.DataFrame(ts_rows, columns=['feature_key', 'fecha', 'value'])
        df_ts['fecha']   = pd.to_datetime(df_ts['fecha'])
        df_ts['anio']    = df_ts['fecha'].dt.year
        df_ts['mes_num'] = df_ts['fecha'].dt.month

        keys       = [k for k in df_ts['feature_key'].unique()
                      if k not in _UNIVERSAL_KEYS and k != 'n_pasajeros_crucero_dia']
        metro_keys = sorted([k for k in keys if 'metro' in k])
        other_keys = sorted([k for k in keys if k not in metro_keys])

        for fk in metro_keys + other_keys:
            meta = _FEATURE_META.get(fk, (fk.replace('_', ' ').title(), '', 'sum', _DEFAULT_COLOR))
            label, sublabel, agg_fn, color = meta
            if 'gran_via' in fk:
                station = "Gran Vía: validaciones diarias"
                sub = "Línea 1 (azul) · Línea 5 (verde)"
            elif 'callao' in fk:
                station = "Callao: validaciones diarias"
                sub = "Línea 3 (amarilla) · Línea 5 (verde)"
            else:
                station, sub = label, sublabel
            c = _render_signal_yoy_chart(
                df_ts[df_ts['feature_key'] == fk], fk, station, sub,
                color, uid, anio_actual, anio_prev, _MESES_ES, agg_fn,
            )
            if c:
                charts.append(c)

    cal_section      = _render_calendario_eventos_clima(location_uuid, fecha_max)
    cruceros_section = _render_cruceros_section(location_uuid, fecha_max)

    if not charts and not cal_section and not cruceros_section:
        return None

    return html.Div([
        *([html.Div([
            html.H6("Afluencia en el entorno · comparativa interanual",
                    className="fw-bold mb-1",
                    style={"color": _C_DARK, "fontSize": "0.98rem"}),
            html.P(
                f"Barras sólidas = {anio_actual} · barras translúcidas = {anio_prev}. "
                "Agregación mensual.",
                className="text-muted mb-3", style={"fontSize": "0.80rem"},
            ),
            html.Div(charts),
        ])] if charts else []),
        *([html.Div([html.Hr(className="my-4"), cruceros_section])]
          if cruceros_section else []),
        *([html.Div([html.Hr(className="my-4"), cal_section])]
          if cal_section else []),
    ])


def _render_zona_section_jerarquica(zonas_data, zona_children_map,
                                    child_zone_names, uid, periodo_label) -> html.Div:
    """Zone cards: parent zones first (blue accent), children grouped below each parent."""
    parent_zones = sorted(
        [z for z in zonas_data if z['zona'] not in child_zone_names],
        key=lambda z: _orden_zona(z['zona']),
    )

    if not zona_children_map:
        cols = [
            dbc.Col(
                _render_zona_card(
                    z['zona'], z['r'], z['a'], z['d'], z['dias_28'], uid, periodo_label,
                    has_children=False,
                    gap_actual=z.get('gap_actual', False),
                    gap_anterior=z.get('gap_anterior', False),
                ),
                xs=12, sm=6, xl=3, className="mb-3",
            )
            for z in sorted(zonas_data, key=lambda z: _orden_zona(z['zona']))
        ]
        return dbc.Row(cols, className="g-3")

    sections = []
    for pz in parent_zones:
        children_names = zona_children_map.get(pz['zona'], [])
        children_data  = [z for z in zonas_data if z['zona'] in children_names]

        parent_card = _render_zona_card(
            pz['zona'], pz['r'], pz['a'], pz['d'], pz['dias_28'], uid, periodo_label,
            child_names=None,
            has_children=bool(children_names),
            gap_actual=pz.get('gap_actual', False),
            gap_anterior=pz.get('gap_anterior', False),
        )

        block = [dbc.Row([dbc.Col(parent_card, xs=12)], className="mb-2 g-2")]

        if children_data:
            child_cols = [
                dbc.Col(
                    _render_zona_card(
                        cz['zona'], cz['r'], cz['a'], cz['d'], cz['dias_28'],
                        uid, periodo_label, has_children=False,
                        gap_actual=cz.get('gap_actual', False),
                        gap_anterior=cz.get('gap_anterior', False),
                    ),
                    xs=12, sm=6, className="mb-2",
                )
                for cz in sorted(children_data, key=lambda z: _orden_zona(z['zona']))
            ]
            block.append(
                html.Div(
                    dbc.Row(child_cols, className="g-2"),
                    className="ps-4",
                    style={"borderLeft": f"3px solid {_color_zona(pz['zona'])}",
                           "marginLeft": "8px"},
                )
            )
        sections.append(html.Div(block, className="mb-4"))

    return html.Div(sections)


# ── Main assembly ─────────────────────────────────────────────────────────────

def generar_mensajes_salud(df, ubi, zonas_seleccionadas=None, location_uuid=None, ventana="semana"):
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
    dias_v        = 28 if ventana == "mes" else 7
    periodo_label = "mes" if ventana == "mes" else "semana"

    # ── Jerarquía de zonas ───────────────────────────────────────────────
    zona_children_map: dict[str, list[str]] = {}
    child_zone_names: set[str] = set()
    for parent_name, child_dicts in _dm.mapa_hijos_por_zona.get(location_uuid or '', {}).items():
        names = [z['value'] for z in child_dicts]
        if names:
            zona_children_map[parent_name] = names
            child_zone_names.update(names)

    # ── Datos por zona ───────────────────────────────────────────────────
    puntos = 0
    zonas_data = []
    for zona in df['Zona'].unique():
        dz = df[df['Zona'] == zona]
        r7,  a7,  d7,  fmin7,  fmax7,  dias7  = evaluar_periodo_zona(dz, fecha_max, 7)
        r28, a28, d28, fmin28, fmax28, dias28  = evaluar_periodo_zona(dz, fecha_max, 28)

        r_p    = r28  if ventana == "mes" else r7
        a_p    = a28  if ventana == "mes" else a7
        d_p    = d28  if ventana == "mes" else d7
        dias_p = dias28 if ventana == "mes" else dias7

        dias_28_raw = (
            dz[dz['fecha_dt'] >= fecha_max - timedelta(days=27)]
            .groupby('fecha_dt')['unique_visitors'].sum().reset_index()
            if 'unique_visitors' in dz.columns else pd.DataFrame()
        )
        if not dias_28_raw.empty:
            dias_28 = dias_28_raw.copy()
            dias_28['unique_visitors'] = dias_28['unique_visitors'].replace(0, np.nan)
        else:
            dias_28 = dias_28_raw

        fmin_p = fecha_max - timedelta(days=dias_v - 1)
        fmin_a = fmin_p - timedelta(days=dias_v)
        fmax_a = fmin_p - timedelta(days=1)
        pct_p  = _pct_activos(dz, fmin_p, fecha_max)
        pct_a  = _pct_activos(dz, fmin_a, fmax_a)
        gap_actual   = pct_p < 0.5
        gap_anterior = pct_a < 0.5

        if   d_p['visitantes'] >=  5: puntos += 1
        elif d_p['visitantes'] <= -5: puntos -= 1

        zonas_data.append(dict(
            zona=zona, r=r_p, a=a_p, d=d_p, dias_p=dias_p,
            r7=r7, a7=a7, d7=d7, fmin7=fmin7, fmax7=fmax7, dias7=dias7,
            r28=r28, a28=a28, d28=d28, dias_28=dias_28,
            gap_actual=gap_actual, gap_anterior=gap_anterior,
        ))

    zonas_data_top = [z for z in zonas_data if z['zona'] not in child_zone_names] or zonas_data

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

    # ── Geo data ─────────────────────────────────────────────────────────
    geo_vals_loc  = get_geo_vals(location_uuid) if location_uuid else {}
    fecha_captura = get_geo_snapshot_date(location_uuid) if location_uuid else None

    # ── Narrativa ────────────────────────────────────────────────────────
    items_narrativa = _narrativa(zonas_data_top, fecha_max, clima, ventana=ventana,
                                 geo_vals=geo_vals_loc)

    # ── Header ───────────────────────────────────────────────────────────
    header = dbc.Card(
        dbc.CardBody(dbc.Row([
            dbc.Col([
                html.P("ESTADO", className="mb-1 text-white-50 text-uppercase fw-bold",
                       style={"fontSize": "0.61rem", "letterSpacing": "1px"}),
                html.H4(ubi, className="fw-bold mb-1 text-white"),
                html.P(
                    f"{(fecha_max - timedelta(days=dias_v - 1)).strftime('%d %b')} – "
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
                    dbc.Tooltip(health_tooltip, target=health_badge_id, placement="left"),
                ], className="d-flex justify-content-end align-items-center h-100"),
                xs=3,
            ),
        ])),
        className="border-0 rounded-4 mb-4 shadow-sm",
        style={"background": "linear-gradient(135deg, #0052CC 0%, #003d99 100%)"},
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

    # ── Narrativa (briefing siempre visible) ─────────────────────────────

    _ventana_label = "este mes" if ventana == "mes" else "esta semana"
    narrativa = html.Div([
        html.H5(
            [html.I(className="fas fa-comment-dots me-2 text-primary"),
             f"Resumen · {_ventana_label}"],
            className="fw-bold mb-1",
            style={"fontSize": "1.05rem", "color": _C_DARK},
        ),
        html.P(
            ("Análisis de los últimos 28 días vs los 28 días anteriores."
             if ventana == "mes" else
             "Análisis de los últimos 7 días vs los 7 días anteriores."),
            className="text-muted mb-2", style={"fontSize": "0.84rem"},
        ),
        _render_narrativa(items_narrativa),
    ], className="mb-3")

    # ── Contenidos de las secciones desplegables ──────────────────────────

    _ventana_zona_lbl = "últimos 28 días" if ventana == "mes" else "últimos 7 días"

    sec_zona = html.Div([
        html.P(
            "Variación de visitantes respecto al período equivalente anterior. "
            "Las zonas padre se muestran con fondo azul; sus subzonas aparecen agrupadas debajo.",
            className="text-muted mb-3", style={"fontSize": "0.82rem"},
        ),
        _render_zona_section_jerarquica(zonas_data, zona_children_map,
                                        child_zone_names, uid, periodo_label),
    ])

    sec_patrones = html.Div([
        html.P("Distribución temporal de visitantes por día, hora y tipo de jornada.",
               className="text-muted mb-3", style={"fontSize": "0.82rem"}),
        _render_pm_questions(df, zonas_data, fecha_max, uid,
                             ventana=ventana, child_zones=child_zone_names),
    ])

    sec_senales = (
        _render_senal_contexto_modal(location_uuid, uid, fecha_max)
        or html.Div(html.P("Sin datos de contexto externo disponibles.", className="text-muted"))
    )

    sec_geo = (
        generar_panel_geo_visual(location_uuid, geo_vals_loc, clima,
                                 fecha_captura=fecha_captura)
        if location_uuid
        else html.Div(html.P("Sin datos de contexto geoespacial.", className="text-muted"))
    )

    # ── Acordeón ─────────────────────────────────────────────────────────

    def _acc_title(icon_cls, texto, color):
        return html.Span([
            html.I(className=f"{icon_cls} me-2",
                   style={"color": color, "fontSize": "0.9rem"}),
            html.Span(texto, style={"fontWeight": "600", "fontSize": "0.92rem",
                                    "color": _C_DARK}),
        ])

    acordeon = dbc.Accordion([
        dbc.AccordionItem(
            sec_zona,
            title=_acc_title("fas fa-layer-group", f"Estado por zona · {_ventana_zona_lbl}", "#0052CC"),
            item_id="zona",
        ),
        dbc.AccordionItem(
            sec_patrones,
            title=_acc_title("fas fa-chart-column", "Patrones de comportamiento", "#27AE60"),
            item_id="patrones",
        ),
        dbc.AccordionItem(
            sec_senales,
            title=_acc_title("fas fa-broadcast-tower", "Señal del contexto exterior", "#E67E22"),
            item_id="senales",
        ),
        dbc.AccordionItem(
            sec_geo,
            title=_acc_title("fas fa-map-marked-alt", "Contexto geoespacial", "#8E44AD"),
            item_id="geo",
        ),
    ],
    always_open=True,
    active_item=[],
    className="shadow-sm rounded-4",
    )

    return html.Div([
        pdf_header,
        header,
        narrativa,
        acordeon,
    ])


def generar_panel_pm(df_completo, locs, zonas_sel, ventana="semana"):
    if df_completo is None or df_completo.empty:
        return dbc.Alert("Sincroniza los datos.", color="warning", className="rounded-4")
    if not locs:
        return dbc.Alert("Selecciona una ubicación.", color="info", className="rounded-4")

    paneles = []
    for ubi in df_completo[df_completo['location_id'].isin(locs)]['Ubicación'].unique():
        df_ubi   = df_completo[df_completo['Ubicación'] == ubi]
        loc_uuid = df_ubi['location_id'].iloc[0] if 'location_id' in df_ubi.columns else None
        paneles.append(generar_mensajes_salud(df_ubi, ubi, zonas_sel, loc_uuid, ventana=ventana))
    return html.Div(paneles)
