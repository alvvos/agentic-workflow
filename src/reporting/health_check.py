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
        hovertemplate='%{x}: <b>%{y:,.0f}</b> visitantes únicos (media/día)<extra></extra>',
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
        hovertemplate='%{x}: <b>%{y:,.0f}</b> visitantes únicos/día (media)<extra></extra>',
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
            f"con {int(peak['unique_visitors']):,} visitantes únicos."))

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

    abs_str  = f"{r['visitantes']:,.0f} visitantes únicos"
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
                        "Visitantes únicos diarios · últimos 28 días. "
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
    """Visitantes únicos totales por semana — desglose del último mes."""
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
        hovertemplate='%{x} (%{customdata}): <b>%{y:,.0f}</b> visitantes únicos<extra></extra>',
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
            "Visitantes únicos por semana · último mes · de izquierda (más antigua) a derecha (más reciente)",
            "180px",
        ))

    preguntas += [
        (
            _fig_dias_semana(df, fecha_max, dias=dias_v),
            f"q-dias-{uid}",
            "¿Cuándo viene la gente?",
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
            f"Visitantes únicos/día (media) · {_periodo}",
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
            f"Visitantes únicos por etapa · {_periodo_corto} · % respecto al paso anterior",
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
    dias_v       = 28 if ventana == "mes" else 7
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
    puntos  = 0
    zonas_data = []
    for zona in df['Zona'].unique():
        dz = df[df['Zona'] == zona]
        r7,  a7,  d7,  fmin7,  fmax7,  dias7  = evaluar_periodo_zona(dz, fecha_max, 7)
        r28, a28, d28, fmin28, fmax28, dias28  = evaluar_periodo_zona(dz, fecha_max, 28)

        # Period-specific data for cards / narrative
        r_p  = r28  if ventana == "mes" else r7
        a_p  = a28  if ventana == "mes" else a7
        d_p  = d28  if ventana == "mes" else d7
        dias_p = dias28 if ventana == "mes" else dias7

        # Sparkline always 28d for visual context
        dias_28_raw = (
            dz[dz['fecha_dt'] >= fecha_max - timedelta(days=27)]
            .groupby('fecha_dt')['unique_visitors'].sum().reset_index()
            if 'unique_visitors' in dz.columns else pd.DataFrame()
        )
        # Zeros → NaN: sensor outage days must not pull the trend line down
        if not dias_28_raw.empty:
            dias_28 = dias_28_raw.copy()
            dias_28['unique_visitors'] = dias_28['unique_visitors'].replace(0, np.nan)
        else:
            dias_28 = dias_28_raw

        # Gap detection — compares active days in current vs previous period
        fmin_p = fecha_max - timedelta(days=dias_v - 1)
        fmin_a = fmin_p - timedelta(days=dias_v)
        fmax_a = fmin_p - timedelta(days=1)
        pct_p  = _pct_activos(dz, fmin_p, fecha_max)
        pct_a  = _pct_activos(dz, fmin_a, fmax_a)
        # >50% of days in a period without data → that period is unreliable
        gap_actual   = pct_p < 0.5
        gap_anterior = pct_a < 0.5

        if   d_p['visitantes'] >=  5: puntos += 1
        elif d_p['visitantes'] <= -5: puntos -= 1

        zonas_data.append(dict(
            zona=zona,
            r=r_p, a=a_p, d=d_p, dias_p=dias_p,
            r7=r7, a7=a7, d7=d7, fmin7=fmin7, fmax7=fmax7, dias7=dias7,
            r28=r28, a28=a28, d28=d28,
            dias_28=dias_28,
            gap_actual=gap_actual,
            gap_anterior=gap_anterior,
        ))

    # Subset used for narrative and zone-segmented charts (parent zones only)
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

    # ── 1. Header ────────────────────────────────────────────────────────
    header = dbc.Card(
        dbc.CardBody(dbc.Row([
            dbc.Col([
                html.P("Panel PM", className="mb-1 text-white-50 text-uppercase fw-bold",
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
                    dbc.Tooltip(health_tooltip, target=health_badge_id,
                                placement="left"),
                ], className="d-flex justify-content-end align-items-center h-100"),
                xs=3,
            ),
        ])),
        className="border-0 rounded-4 mb-4 shadow-sm",
        style={"background": "linear-gradient(135deg, #0052CC 0%, #003d99 100%)"},
    )

    # ── Geo data (loaded once — shared by narrativa and geo panel) ───────
    geo_vals_loc  = get_geo_vals(location_uuid) if location_uuid else {}
    fecha_captura = get_geo_snapshot_date(location_uuid) if location_uuid else None

    # ── 2. Narrativa ─────────────────────────────────────────────────────
    items_narrativa = _narrativa(zonas_data_top, fecha_max, clima, ventana=ventana,
                                 geo_vals=geo_vals_loc)

    _ventana_label = "este mes" if ventana == "mes" else "esta semana"
    narrativa_header = html.Div([
        html.H5(
            [html.I(className="fas fa-comment-dots me-2 text-primary"),
             f"¿Qué pasó {_ventana_label}?"],
            className="fw-bold mb-1",
            style={"fontSize": "1.15rem", "color": _C_DARK},
        ),
        html.P(
            (f"Análisis de los últimos 28 días vs los 28 días anteriores."
             if ventana == "mes" else
             f"Análisis de los últimos 7 días vs los 7 días anteriores."),
            className="text-muted mb-3",
            style={"fontSize": "0.84rem"},
        ),
    ], className="mb-2")

    narrativa = html.Div([narrativa_header, _render_narrativa(items_narrativa)])

    # ── 3. Zonas (semáforo + sparkline) ──────────────────────────────────
    def _orden(z):
        zl = z['zona'].lower()
        if 'exterior' in zl or 'calle' in zl: return 0
        if 'tienda' in zl:                    return 1
        if 'caja' in zl:                      return 2
        return 3

    zona_cols = [
        dbc.Col(
            _render_zona_card(
                z['zona'], z['r'], z['a'], z['d'], z['dias_28'], uid, periodo_label,
                child_names=zona_children_map.get(z['zona'], []),
                has_children=z['zona'] in zona_children_map,
                gap_actual=z.get('gap_actual', False),
                gap_anterior=z.get('gap_anterior', False),
            ),
            xs=12, sm=6, xl=3, className="mb-3",
        )
        for z in sorted(zonas_data, key=_orden)
    ]  # noqa: E501

    _ventana_zona_lbl = "últimos 28 días" if ventana == "mes" else "últimos 7 días"
    zonas_section = html.Div([
        html.H5(
            [html.I(className="fas fa-layer-group me-2 text-primary"),
             f"Estado por zona — {_ventana_zona_lbl}"],
            className="fw-bold mb-1",
            style={"fontSize": "1.15rem", "color": _C_DARK},
        ),
        html.P(
            "Variación de visitantes únicos respecto al período equivalente anterior. "
            "La línea punteada en el sparkline marca la tendencia de los últimos 28 días.",
            className="text-muted mb-3",
            style={"fontSize": "0.84rem"},
        ),
        dbc.Row(zona_cols, className="g-3"),
    ], className="mb-4")

    # ── 4. Preguntas PM ──────────────────────────────────────────────────
    dias_section = _render_pm_questions(
        df, zonas_data, fecha_max, uid,
        ventana=ventana, child_zones=child_zone_names,
    )

    # ── 5. Geo panel ─────────────────────────────────────────────────────
    geo = (
        generar_panel_geo_visual(location_uuid, geo_vals_loc, clima,
                                  fecha_captura=fecha_captura)
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
