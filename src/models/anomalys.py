import pandas as pd
import numpy as np
import plotly.graph_objects as go
from dash import html, dcc
import dash_bootstrap_components as dbc
import holidays
import uuid
import json
from datetime import timedelta

festivos_espana = holidays.ES(years=[2024, 2025, 2026])

_GRAPH_CONFIG = {
    'displayModeBar': True,
    'displaylogo': False,
    'modeBarButtons': [['toImage']],
    'toImageButtonOptions': {'format': 'png', 'scale': 3, 'height': 600, 'width': 1400},
}

def formato_fecha_es(fecha):
    dias = ['L', 'M', 'X', 'J', 'V', 'S', 'D']
    meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    return f"{dias[fecha.weekday()]} {fecha.day} {meses[fecha.month - 1]}"

def obtener_mapa_colores(zonas):
    color_map = {}
    for z in zonas:
        zl = str(z).lower()
        if 'caja' in zl: color_map[z] = '#8e44ad'
        elif 'tienda' in zl: color_map[z] = '#e67e22'
        elif 'calle' in zl or 'exterior' in zl: color_map[z] = '#2980b9'
        else: color_map[z] = '#7f8c8d'
    return color_map

def ordenar_zonas(zonas):
    def peso(z):
        zl = str(z).lower()
        if 'exterior' in zl or 'calle' in zl: return 1
        if 'tienda' in zl: return 2
        if 'caja' in zl: return 3
        return 4
    return sorted(zonas, key=peso)

def obtener_titulo_intuitivo(col):
    mapa = {
        'total_visits': 'Visitas totales',
        'unique_visitors': 'Visitantes diarios',
        'new_visitors': 'Nuevos visitantes',
        'dwell_time': 'Tiempo medio de estancia (min)',
        'uv_7d': 'Visitantes únicos (7d)',
        'uv_28d': 'Visitantes únicos (28d)',
        'freq_7d': 'Frecuencia de retorno (7d)',
        'freq_28d': 'Frecuencia de retorno (28d)',
        'ratio_atraccion': 'Ratio de atracción (%)'
    }
    return mapa.get(col, col)

def preparar_df_ratio(df, z_out, z_in):
    if df.empty: return pd.DataFrame()
    df_out = df[df['Zona'] == z_out].groupby('fecha_dia')['unique_visitors'].sum().reset_index()
    df_in = df[df['Zona'] == z_in].groupby('fecha_dia')['unique_visitors'].sum().reset_index()
    if df_out.empty or df_in.empty: return pd.DataFrame()
    
    m = pd.merge(df_out, df_in, on='fecha_dia', suffixes=('_out', '_in'))
    m['ratio_atraccion'] = (m['unique_visitors_in'] / m['unique_visitors_out'] * 100).fillna(0)
    m['Zona'] = z_in 
    return m


def construir_figura_bi(df, df_hist, metrica, titulo, zonas_ordenadas, color_map, tipo='bar', offset_dias=0):
    fig = go.Figure()
    if df.empty: 
        return fig.update_layout(title="Sin datos", xaxis=dict(visible=False), yaxis=dict(visible=False))

    df = df.sort_values('fecha_dia')
    fechas_unicas = sorted(df['fecha_dia'].unique())

    _MESES_ES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    usar_meses = len(fechas_unicas) > 60
    if usar_meses:
        _agg = 'sum' if tipo == 'bar' else 'mean'
        df = df.copy()
        df['fecha_dia'] = df['fecha_dia'].dt.to_period('M').dt.to_timestamp()
        df = df.groupby(['fecha_dia', 'Zona'])[metrica].agg(_agg).reset_index()
        df_hist = pd.DataFrame()
        fechas_unicas = sorted(df['fecha_dia'].unique())
        tickvals = fechas_unicas
        ticktext = [f"{_MESES_ES[pd.to_datetime(f).month - 1]} {pd.to_datetime(f).year}" for f in fechas_unicas]
        angulo_x = 0
    else:
        tickvals = fechas_unicas
        ticktext = [formato_fecha_es(pd.to_datetime(f)) for f in fechas_unicas]
        angulo_x = -90 if len(fechas_unicas) > 10 else 0

    has_historical = not df_hist.empty and offset_dias > 0

    for zona in zonas_ordenadas:
        df_z = df[df['Zona'] == zona].copy()
        if df_z.empty: continue
        color_zona = color_map.get(zona, '#34495e')
        
        hist_dict = {}
        df_z_hist = pd.DataFrame()
        if has_historical:
            df_z_hist = df_hist[df_hist['Zona'] == zona].copy()
            if not df_z_hist.empty:
                df_z_hist['fecha_alineada'] = df_z_hist['fecha_dia'] + pd.Timedelta(days=offset_dias)
                hist_dict = dict(zip(df_z_hist['fecha_alineada'], df_z_hist[metrica]))

        hover_texts = []
        for _, row in df_z.iterrows():
            f, v = row['fecha_dia'], row[metrica]
            v_hist = hist_dict.get(f, None)
            txt = f"<b>{zona}</b><br>Actual: <b>{v:,.1f}</b>"
            if v_hist is not None:
                delta = v - v_hist
                pct = (delta / v_hist * 100) if v_hist > 0 else 0
                flecha = "▲" if delta > 0 else ("▼" if delta < 0 else "◼")
                color_flecha = "#27ae60" if delta > 0 else ("#e74c3c" if delta < 0 else "#7f8c8d")
                txt += f"<br>Anterior: {v_hist:,.1f}<br>Evolución: <b style='color:{color_flecha}'>{flecha} {pct:+.1f}%</b>"
            hover_texts.append(txt)
        
        if tipo == 'bar':
            if not df_z_hist.empty:
                df_z_hist = df_z_hist.sort_values('fecha_alineada')
                fig.add_trace(go.Bar(x=df_z_hist['fecha_alineada'], y=df_z_hist[metrica], name=f"{zona} (Ant.)", marker_color=color_zona, opacity=0.15, marker_line_width=1, marker_line_color=color_zona, hoverinfo='skip', showlegend=False, customdata=[zona]*len(df_z_hist)))
            bar_text = [f"{int(round(v)):,}" if pd.notna(v) and v > 0 else "" for v in df_z[metrica]]
            fig.add_trace(go.Bar(x=df_z['fecha_dia'], y=df_z[metrica], name=zona, marker_color=color_zona, hoverinfo='text', hovertext=hover_texts, opacity=0.9, customdata=[zona]*len(df_z), text=bar_text, textposition='inside', insidetextanchor='middle', constraintext='none', textfont=dict(size=10, color='white', family='Arial Black, Arial, sans-serif')))
        else:
            if not df_z_hist.empty:
                df_z_hist = df_z_hist.sort_values('fecha_alineada')
                fig.add_trace(go.Scatter(x=df_z_hist['fecha_alineada'], y=df_z_hist[metrica], name=f"{zona} (Ant.)", mode='lines', line=dict(color=color_zona, width=1.5, dash='dot'), hoverinfo='skip', showlegend=False, opacity=0.4, customdata=[zona]*len(df_z_hist)))
            fig.add_trace(go.Scatter(x=df_z['fecha_dia'], y=df_z[metrica], name=zona, mode='lines+markers', line=dict(color=color_zona, width=3, shape='spline'), marker=dict(size=7), hoverinfo='text', hovertext=hover_texts, customdata=[zona]*len(df_z)))
            if len(df_z) > 2:
                y_num = df_z[metrica].fillna(df_z[metrica].mean()).values
                coef = np.polyfit(np.arange(len(y_num)), y_num, 1)
                trend = np.polyval(coef, np.arange(len(y_num)))
                fig.add_trace(go.Scatter(
                    x=df_z['fecha_dia'], y=trend,
                    mode='lines', line=dict(color=color_zona, width=1.5, dash='dash'),
                    opacity=0.45, showlegend=False, hoverinfo='skip',
                    customdata=[zona] * len(df_z)
                ))

        if len(df_z) > 2:
            m, s = df_z[metrica].mean(), df_z[metrica].std()
            if pd.notna(s) and s > 0:
                df_z['z'] = (df_z[metrica] - m) / s
                p_pos = df_z[df_z['z'] > 2.2]
                if not p_pos.empty: 
                    fig.add_trace(go.Scatter(x=p_pos['fecha_dia'], y=p_pos[metrica], mode='markers', marker=dict(color='#27ae60', size=12, symbol='circle-open', line=dict(width=3)), showlegend=False, hoverinfo='skip', customdata=[zona]*len(p_pos)))
                p_neg = df_z[(df_z['z'] < -2.2) | (df_z[metrica] == 0)]
                if not p_neg.empty: 
                    fig.add_trace(go.Scatter(x=p_neg['fecha_dia'], y=p_neg[metrica], mode='markers', marker=dict(color='#e74c3c', size=12, symbol='x-open', line=dict(width=3)), showlegend=False, hoverinfo='skip', customdata=[zona]*len(p_neg)))

    fig.update_layout(title=dict(text=titulo, font=dict(size=15, color='#2c3e50', family='Arial, sans-serif')), plot_bgcolor='white', hovermode='x unified', margin=dict(t=45, b=45, l=40, r=20), legend=dict(orientation="h", y=1.1, x=1, xanchor='right'), barmode='group' if tipo == 'bar' else None, clickmode='event+select', dragmode=False)
    fig.update_xaxes(tickvals=tickvals, ticktext=ticktext, showgrid=True, gridcolor='#f2f2f2', tickangle=angulo_x)
    fig.update_yaxes(showgrid=True, gridcolor='#f2f2f2', rangemode='tozero')
    return fig

def crear_tarjeta_metrica(df, df_hist, col_y, titulo, offset, ubi, id_sufijo, tipo='bar'):
    zonas = ordenar_zonas(df['Zona'].unique())
    fig = construir_figura_bi(df, df_hist, col_y, titulo, zonas, obtener_mapa_colores(zonas), tipo, offset)
    gid = f"{ubi}-{col_y}-{id_sufijo}"
    cfg = {**_GRAPH_CONFIG, 'toImageButtonOptions': {**_GRAPH_CONFIG['toImageButtonOptions'], 'filename': gid}}
    return dbc.Card([
        dbc.CardHeader([
            dbc.Button(html.I(className="fas fa-expand-arrows-alt"), id={"type": "btn-expand", "index": gid}, color="link", className="p-0 text-muted float-end ms-2", style={"textDecoration": "none"}),
        ], className="bg-white border-0 py-1"),
        dbc.CardBody(dcc.Graph(id={"type": "bi-graph", "index": gid}, figure=fig, config=cfg, style={"height": "350px"}), className="p-1")
    ], className="border-0 shadow-sm rounded-4 h-100")

def _parse_hourly(val):
    """Parse hourly_visits JSON array of 24 ints."""
    if val is None:
        return None
    if isinstance(val, float) and np.isnan(val):
        return None
    try:
        parsed = json.loads(str(val))
        if isinstance(parsed, list) and len(parsed) == 24:
            return [float(v) for v in parsed]
    except Exception:
        pass
    return None


_DIAS_MAP_HEAT = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
_ORDEN_DIAS_HEAT = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']


def crear_mapa_calor_horario(df_zona, zona_nombre):
    """Hour × day-of-week heatmap with values annotated in each cell."""
    if 'hourly_visits' not in df_zona.columns:
        return None
    rows = []
    for _, row in df_zona.iterrows():
        horas = _parse_hourly(row['hourly_visits'])
        if horas is None:
            continue
        fecha_ref = row['fecha_dia'] if 'fecha_dia' in row.index else row['fecha']
        dia = _DIAS_MAP_HEAT.get(pd.to_datetime(fecha_ref).dayofweek, '')
        for h, v in enumerate(horas):
            rows.append({'dia_semana': dia, 'hora': h, 'visitas': v})
    if not rows:
        return None
    df_ex = pd.DataFrame(rows)
    pivot = df_ex.groupby(['hora', 'dia_semana'])['visitas'].mean().unstack(fill_value=0)
    pivot = pivot.reindex(columns=[d for d in _ORDEN_DIAS_HEAT if d in pivot.columns], fill_value=0)
    if pivot.empty:
        return None
    z_vals = pivot.values.tolist()
    z_max = float(pivot.values.max())
    threshold = z_max * 0.55 if z_max > 0 else 1
    hora_labels = [f"{h:02d}:00" for h in pivot.index]
    dias_labels = pivot.columns.tolist()
    annotations = []
    for i, hora_lbl in enumerate(hora_labels):
        for j, dia in enumerate(dias_labels):
            v = pivot.values[i, j]
            txt_color = 'white' if v > threshold else '#2c3e50'
            annotations.append(dict(
                x=dia, y=hora_lbl,
                text=f"<b>{int(round(v))}</b>",
                showarrow=False,
                font=dict(size=12, color=txt_color),
                xref='x', yref='y',
            ))
    fig = go.Figure(go.Heatmap(
        z=z_vals,
        x=dias_labels,
        y=hora_labels,
        colorscale='Reds',
        zmin=0,
        zmax=z_max if z_max > 0 else 1,
        hovertemplate='%{x} · %{y}<br>Visitas: <b>%{z:.0f}</b><extra></extra>',
        colorbar=dict(thickness=14, tickfont=dict(size=11)),
        xgap=3,
        ygap=3,
    ))
    fig.update_layout(
        title=dict(text=f"Visitas por hora — {zona_nombre}", font=dict(size=14, color='#2c3e50', family='Arial, sans-serif')),
        plot_bgcolor='white',
        paper_bgcolor='white',
        margin=dict(t=50, b=50, l=65, r=60),
        xaxis=dict(side='bottom', tickfont=dict(size=12), showgrid=False),
        yaxis=dict(autorange='reversed', tickfont=dict(size=10), showgrid=False),
        annotations=annotations,
        height=650,
    )
    return fig


def _seccion_uv_rolling(df_z, df_zh, cols_uv, multi_mes, zona, color_zona, ubi=''):
    """UV rolling KPIs — simple number cards when single period, monthly bar chart when multi-month."""
    if not multi_mes:
        _COLOR = {'uv_7d': '#0052CC', 'uv_28d': '#17A2B8'}
        _LABEL = {'uv_7d': '7 días', 'uv_28d': '28 días'}
        uv_cards = []
        for col in cols_uv:
            serie = df_z.sort_values('fecha_dia')[col].dropna()
            val = float(serie.iloc[-1]) if not serie.empty else 0.0
            color = _COLOR.get(col, '#34495e')
            label = _LABEL.get(col, col)
            uv_cards.append(dbc.Col(
                dbc.Card(dbc.CardBody([
                    html.P(f"Visitantes únicos · {label}",
                           className="fw-bold mb-1",
                           style={"fontSize": "0.65rem", "letterSpacing": "0.5px",
                                  "textTransform": "uppercase", "color": "#6c757d"}),
                    html.H4(f"{val:,.0f}", className="fw-bold mb-0", style={"color": color}),
                ], className="text-center py-3 px-2"),
                className="border-0 shadow-sm rounded-4 h-100"),
                xs=6, xl=4, className="mb-2"
            ))
        return html.Div([
            html.Small("Visitantes únicos rolling", className="text-muted text-uppercase fw-bold d-block mt-3 mb-2"),
            dbc.Row(uv_cards)
        ])
    else:
        colores_uv = {'uv_7d': '#0052CC', 'uv_28d': '#17A2B8'}
        fig = go.Figure()
        for col in cols_uv:
            meses = sorted(df_z['fecha_dia'].dt.to_period('M').unique())
            labels, vals = [], []
            for mes in meses:
                df_mes = df_z[df_z['fecha_dia'].dt.to_period('M') == mes]
                serie = df_mes.sort_values('fecha_dia')[col].dropna() if col in df_mes.columns else pd.Series([], dtype=float)
                if not serie.empty:
                    labels.append(str(mes))
                    vals.append(float(serie.iloc[-1]))
            if vals:
                bar_labels = [f"<b>{int(v):,}</b>" for v in vals]
                fig.add_trace(go.Bar(
                    x=labels, y=vals,
                    name=obtener_titulo_intuitivo(col),
                    marker_color=colores_uv.get(col, '#7f8c8d'),
                    opacity=0.85,
                    text=bar_labels,
                    textposition='inside',
                    insidetextanchor='middle',
                    constraintext='none',
                    textfont=dict(size=11, color='white', family='Arial Black, Arial, sans-serif'),
                ))
        fig.update_layout(
            title=dict(text=f"Visitantes únicos rolling por mes — {zona}", font=dict(size=13, color='#2c3e50', family='Arial, sans-serif')),
            plot_bgcolor='white', barmode='group',
            margin=dict(t=40, b=40, l=40, r=20),
            legend=dict(orientation="h", y=1.12, x=1, xanchor='right'),
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=True, gridcolor='#f2f2f2'),
            height=260,
        )
        gid = f"{ubi}-uv-rolling-{zona}"
        return dbc.Card([
            dbc.CardHeader([
                dbc.Button(html.I(className="far fa-square"), id={"type": "btn-select-graph", "index": gid}, color="link", className="p-0 float-end", style={"textDecoration": "none", "fontSize": "0.95rem", "color": "#adb5bd"}),
            ], className="bg-white border-0 py-1"),
            dbc.CardBody(
                dcc.Graph(id={"type": "bi-graph", "index": gid}, figure=fig, config=_GRAPH_CONFIG, style={"height": "260px"}),
                className="p-1"
            )
        ], className="border-0 shadow-sm rounded-4 mt-3")


def crear_tarjeta_kpi_global(titulo, val_actual, val_hist, es_tiempo=False, es_ratio=False):
    suffix = "%" if es_ratio else (" min" if es_tiempo else "")
    decimals = 2 if es_ratio else (1 if es_tiempo else 0)
    
    txt_actual = f"{val_actual:,.{decimals}f}{suffix}"
    txt_hist = f"{val_hist:,.{decimals}f}{suffix}" if val_hist is not None else "-"

    delta_html = html.Span("Sin comparativa activa", className="small text-muted fw-bold")
    if val_hist is not None and val_hist > 0:
        delta = val_actual - val_hist
        pct = (delta / val_hist) * 100
        # Semáforo supersensible a 0.01 para ratios
        color = "text-success" if delta > 0.01 else ("text-danger" if delta < -0.01 else "text-muted")
        flecha = "▲" if delta > 0.01 else ("▼" if delta < -0.01 else "◼")
        
        valor_evol = f"{delta:+.2f} pp" if es_ratio else f"{pct:+.1f}%"
        delta_html = html.Span(f"{flecha} {valor_evol} vs Ant. ({txt_hist})", className=f"small fw-bold {color}")

    return dbc.Card(dbc.CardBody([
        html.H6(titulo, className="text-muted text-uppercase small fw-bold mb-2", style={"fontSize": "0.7rem"}),
        html.H4(txt_actual, className="fw-bold mb-1 text-dark"),
        html.Div(delta_html, className="mt-1", style={"fontSize": "0.75rem"})
    ]), className="border-0 shadow-sm rounded-4 text-center h-100")

def generar_panel_bi_completo(df_actual, df_hist, comparativa, fechas_filtro=None):
    if df_actual.empty: return dbc.Alert("No hay datos disponibles en el rango seleccionado.", color="warning", className="rounded-4")

    offset = {'wow': 7, 'mom': 28, 'yoy': 365}.get(comparativa, 0)

    if fechas_filtro:
        fechas_set = set(pd.to_datetime(fechas_filtro).normalize())
        df_actual = df_actual[df_actual['fecha'].dt.normalize().isin(fechas_set)]
        if df_actual.empty:
            return dbc.Alert("Ningún dato coincide con los días seleccionados.", color="info", className="rounded-4")

    df_actual['fecha_dia'] = df_actual['fecha'].dt.normalize()
    if not df_hist.empty: df_hist['fecha_dia'] = df_hist['fecha'].dt.normalize()
    multi_mes = df_actual['fecha_dia'].dt.to_period('M').nunique() > 1

    paneles = []
    for ubi in df_actual['Ubicación'].unique():
        df_u = df_actual[df_actual['Ubicación'] == ubi].copy()
        df_h = df_hist[df_hist['Ubicación'] == ubi].copy() if not df_hist.empty else pd.DataFrame()
        
        zonas_presentes = ordenar_zonas(df_u['Zona'].unique())
        mapa_colores = obtener_mapa_colores(zonas_presentes)
        cintas_kpis_zonas = []
        
        for zona in zonas_presentes:
            df_z = df_u[df_u['Zona'] == zona]
            df_zh = df_h[df_h['Zona'] == zona] if not df_h.empty else pd.DataFrame()

            val_tv = df_z['total_visits'].sum() if 'total_visits' in df_z.columns else 0
            val_uv = df_z['unique_visitors'].sum() if 'unique_visitors' in df_z.columns else 0
            val_nv = df_z['new_visitors'].sum() if 'new_visitors' in df_z.columns else 0
            val_dt = df_z['dwell_time'].mean() if 'dwell_time' in df_z.columns else 0

            hist_tv = df_zh['total_visits'].sum() if not df_zh.empty and 'total_visits' in df_zh.columns else None
            hist_uv = df_zh['unique_visitors'].sum() if not df_zh.empty and 'unique_visitors' in df_zh.columns else None
            hist_nv = df_zh['new_visitors'].sum() if not df_zh.empty and 'new_visitors' in df_zh.columns else None
            hist_dt = df_zh['dwell_time'].mean() if not df_zh.empty and 'dwell_time' in df_zh.columns else None

            color_zona = mapa_colores.get(zona, '#34495e')

            cinta_hijos = [
                html.H6([html.I(className="fas fa-bullseye me-2", style={"color": color_zona}), f"RENDIMIENTO DE ZONA: {zona}"], className="fw-bold mb-3 text-dark text-uppercase small"),
                dbc.Row([
                    dbc.Col(crear_tarjeta_kpi_global("Visitas Totales", val_tv, hist_tv), xs=6, xl=3, className="mb-2"),
                    dbc.Col(crear_tarjeta_kpi_global("Visitantes", val_uv, hist_uv), xs=6, xl=3, className="mb-2"),
                    dbc.Col(crear_tarjeta_kpi_global("Nuevos Visitantes", val_nv, hist_nv), xs=6, xl=3, className="mb-2"),
                    dbc.Col(crear_tarjeta_kpi_global("Estancia Media", val_dt, hist_dt, es_tiempo=True), xs=6, xl=3, className="mb-2"),
                ])
            ]
            cols_uv = [c for c in ['uv_7d', 'uv_28d'] if c in df_z.columns]
            if cols_uv:
                uv_block = _seccion_uv_rolling(df_z, df_zh, cols_uv, multi_mes, zona, color_zona, ubi)
                if uv_block:
                    cinta_hijos.append(uv_block)
            cinta = html.Div(cinta_hijos, className="mb-4 p-3 bg-light rounded-4 border-start border-4 shadow-sm", style={"borderLeftColor": f"{color_zona} !important"})
            
            cintas_kpis_zonas.append(cinta)
            
        # --- SECCIÓN REACTIVA DE FUNNEL (Ratio de Atracción) ---
        seccion_funnel = []
        if len(zonas_presentes) > 1:
            kpis_funnel = []
            graficos_funnel = []
            for i in range(len(zonas_presentes) - 1):
                z_out, z_in = zonas_presentes[i], zonas_presentes[i+1]
                df_r_act = preparar_df_ratio(df_u, z_out, z_in)
                df_r_hist = preparar_df_ratio(df_h, z_out, z_in) if not df_h.empty else pd.DataFrame()
                
                if not df_r_act.empty:
                    v_ratio = df_r_act['ratio_atraccion'].mean()
                    h_ratio = df_r_hist['ratio_atraccion'].mean() if not df_r_hist.empty else None
                    
                    titulo_f = f"Atracción: {z_out} → {z_in}"
                    kpis_funnel.append(dbc.Col(crear_tarjeta_kpi_global(titulo_f, v_ratio, h_ratio, es_ratio=True), xs=12, md=6, className="mb-3"))
                    
                    card_g = crear_tarjeta_metrica(df_r_act, df_r_hist, 'ratio_atraccion', f"Evolución {titulo_f}", offset, ubi, f"funnel-{i}", 'line')
                    graficos_funnel.append(dbc.Col(card_g, xs=12, xl=6, className="mb-4"))

            if kpis_funnel:
                seccion_funnel = [
                    html.Div(className="d-flex justify-content-between align-items-end border-bottom pb-2 mb-3 mt-4", children=[
                        html.H5([html.I(className="fas fa-filter me-2 text-primary"), "Conversión y Atracción (Funnel)"], className="fw-bold mb-0 text-dark"),
                        
                        # --- BOTÓN TRIGEADOR LLM ---
                        dbc.Button([html.I(className="fas fa-magic me-2"), "Consultar Benchmark AI"], 
                                   id={"type": "btn-ai-benchmark", "index": ubi}, 
                                   color="dark", size="sm", className="fw-bold rounded-pill shadow-sm")
                    ]),
                    
                    # --- TARJETA RECEPTORA DEL LLM (Oculta por defecto) ---
                    html.Div(id={"type": "card-ai-benchmark", "index": ubi}, className="mb-4"),
                    
                    dbc.Row(kpis_funnel),
                    dbc.Row(graficos_funnel)
                ]
        # ---------------------------------------------------------

        df_u['Zona'] = df_u['Zona'].fillna('')
        m_ext = df_u['Zona'].str.lower().str.contains('calle|exterior')
        
        agg = {'total_visits': 'sum', 'unique_visitors': 'sum', 'new_visitors': 'sum', 'dwell_time': 'mean'}
        for col in df_u.columns:
            if ('7d' in col.lower() or '28d' in col.lower()) and col not in agg:
                agg[col] = 'mean'
                
        df_int = df_u[~m_ext].groupby(['fecha_dia', 'Zona']).agg({k: v for k, v in agg.items() if k in df_u.columns}).reset_index() if not df_u[~m_ext].empty else pd.DataFrame()
        df_ext = df_u[m_ext].groupby(['fecha_dia', 'Zona']).agg({k: v for k, v in agg.items() if k in df_u.columns}).reset_index() if not df_u[m_ext].empty else pd.DataFrame()
        
        df_hi, df_he = pd.DataFrame(), pd.DataFrame()
        if not df_h.empty:
            df_h['Zona'] = df_h['Zona'].fillna('')
            m_hex = df_h['Zona'].str.lower().str.contains('calle|exterior')
            df_hi = df_h[~m_hex].groupby(['fecha_dia', 'Zona']).agg({k: v for k, v in agg.items() if k in df_h.columns}).reset_index() if not df_h[~m_hex].empty else pd.DataFrame()
            df_he = df_h[m_hex].groupby(['fecha_dia', 'Zona']).agg({k: v for k, v in agg.items() if k in df_h.columns}).reset_index() if not df_h[m_hex].empty else pd.DataFrame()

        cards = []
        metricas_bar = ['total_visits', 'unique_visitors', 'new_visitors']
        for c in metricas_bar:
            if c in df_u.columns:
                t = obtener_titulo_intuitivo(c)
                if not df_int.empty: cards.append(crear_tarjeta_metrica(df_int, df_hi, c, f"{t} (Int)", offset, ubi, 'int', 'bar'))
                if not df_ext.empty: cards.append(crear_tarjeta_metrica(df_ext, df_he, c, f"{t} (Ext)", offset, ubi, 'ext', 'bar'))

        metricas_line = [c for c in agg.keys() if c in df_u.columns and c not in metricas_bar]
        for c in metricas_line:
            t = obtener_titulo_intuitivo(c)
            if not df_int.empty: cards.append(crear_tarjeta_metrica(df_int, df_hi, c, f"{t} (Int)", offset, ubi, 'int', 'line'))
            if not df_ext.empty: cards.append(crear_tarjeta_metrica(df_ext, df_he, c, f"{t} (Ext)", offset, ubi, 'ext', 'line'))

        rows = []
        for i in range(0, len(cards), 2):
            col1 = dbc.Col(cards[i], xs=12, xl=6, className="mb-4")
            col2 = dbc.Col(cards[i+1], xs=12, xl=6, className="mb-4") if i+1 < len(cards) else dbc.Col(width=6)
            rows.append(dbc.Row([col1, col2]))

        heatmap_cols = []
        for zona_hm in zonas_presentes:
            df_zona_hm = df_u[df_u['Zona'] == zona_hm]
            fig_hm = crear_mapa_calor_horario(df_zona_hm, zona_hm)
            if fig_hm is not None:
                hm_gid = f"{ubi}-heatmap-{zona_hm}"
                card_hm = dbc.Card([
                    dbc.CardHeader([
                        dbc.Button(html.I(className="fas fa-expand-arrows-alt"),
                                   id={"type": "btn-expand", "index": hm_gid},
                                   color="link", className="p-0 text-muted float-end ms-2",
                                   style={"textDecoration": "none"}),
                        dbc.Button(html.I(className="far fa-square"),
                                   id={"type": "btn-select-graph", "index": hm_gid},
                                   color="link", className="p-0 float-end",
                                   style={"textDecoration": "none", "fontSize": "0.95rem", "color": "#adb5bd"}),
                    ], className="bg-white border-0 py-1"),
                    dbc.CardBody(
                        dcc.Graph(id={"type": "bi-graph", "index": hm_gid},
                                  figure=fig_hm, config=_GRAPH_CONFIG,
                                  style={"height": "660px"}),
                        className="p-1"
                    )
                ], className="border-0 shadow-sm rounded-4 h-100")
                heatmap_cols.append(dbc.Col(card_hm, xs=12, xl=6, className="mb-4"))

        seccion_heatmap = []
        if heatmap_cols:
            seccion_heatmap = [
                html.Div([
                    html.H5([html.I(className="fas fa-th me-2 text-primary"), "Intensidad Horaria por Día de la Semana"],
                            className="fw-bold mb-0 text-dark"),
                ], className="d-flex align-items-center border-bottom pb-2 mb-3 mt-4"),
                dbc.Row(heatmap_cols)
            ]

        paneles.append(html.Div([
            html.H4([html.I(className="fas fa-map-marker-alt me-2 text-danger"), ubi], className="fw-bold mb-4 mt-3 text-secondary border-bottom pb-2"),
            html.Div(cintas_kpis_zonas),
            html.Div(seccion_funnel),
            html.Hr(className="text-muted my-4"),
            html.Div(rows),
            html.Div(seccion_heatmap)
        ]))
        
    return html.Div(paneles)