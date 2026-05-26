import ast
import calendar
import uuid
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

# ── Paleta corporativa ──────────────────────────────────────────────────────
C_PRIMARY = '#0052CC'
C_DARK    = '#1e272e'
C_GRAY    = '#6c757d'
C_LGRAY   = '#dee2e6'
C_LIGHT   = '#f8f9fa'
C_SUCCESS = '#28A745'
C_DANGER  = '#DC3545'
C_WARN    = '#f39c12'
C_EXT     = '#2980b9'
C_INT     = '#e67e22'
C_CAJA    = '#8e44ad'
C_OTRO    = '#7f8c8d'

MESES_ES = {1:'Enero',2:'Febrero',3:'Marzo',4:'Abril',5:'Mayo',6:'Junio',
            7:'Julio',8:'Agosto',9:'Septiembre',10:'Octubre',11:'Noviembre',12:'Diciembre'}
MESES_CORTO = {1:'Ene',2:'Feb',3:'Mar',4:'Abr',5:'May',6:'Jun',
               7:'Jul',8:'Ago',9:'Sep',10:'Oct',11:'Nov',12:'Dic'}
DIAS_ES = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
DIAS_CORTO = ['L','M','X','J','V','S','D']


# ── Utilidades de zona ──────────────────────────────────────────────────────

def _color_zona(zona):
    z = str(zona).lower()
    if 'caja' in z:                        return C_CAJA
    if 'tienda' in z:                      return C_INT
    if 'exterior' in z or 'calle' in z:    return C_EXT
    return C_OTRO

def _ordenar_zonas(zonas):
    def _peso(z):
        zl = str(z).lower()
        if 'exterior' in zl or 'calle' in zl: return 1
        if 'tienda' in zl:                    return 2
        if 'caja' in zl:                      return 3
        return 4
    return sorted(zonas, key=_peso)

def _zona_exterior(zonas):
    for z in _ordenar_zonas(zonas):
        zl = str(z).lower()
        if 'exterior' in zl or 'calle' in zl:
            return z
    return None

def _zona_interior(zonas):
    for z in _ordenar_zonas(zonas):
        if 'tienda' in str(z).lower():
            return z
    return None

def _parsear_horas(val):
    try:
        r = ast.literal_eval(val) if isinstance(val, str) else val
        return r if isinstance(r, list) and len(r) == 24 else [0]*24
    except Exception:
        return [0]*24

def _fmt(v, dec=0):
    if pd.isna(v):
        return '-'
    if dec == 0:
        return f"{int(v):,}".replace(',', '.')
    return f"{v:,.{dec}f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def _uid():
    return uuid.uuid4().hex[:8]

def _interpolar_hex(t):
    r = int(248 - t * 248)
    g = int(249 - t * 167)
    b = int(250 - t * 46)
    return f'#{r:02x}{g:02x}{b:02x}'


# ── Serialización de figuras Plotly ─────────────────────────────────────────

def _fig_html(fig):
    return pio.to_html(
        fig, include_plotlyjs=False, full_html=False,
        config={'displayModeBar': False, 'responsive': True}
    )


def _ymax_padded(*series, factor=1.18):
    """Ymax con margen para etiquetas outside en barras."""
    flat = [v for s in series for v in s if v is not None and not pd.isna(v) and v > 0]
    return max(flat) * factor if flat else 1


def _bar_height(n_grupos, n_series=1, base=260, per_group=14, mn=280, mx=520):
    """Altura dinámica según número de grupos × series."""
    return max(mn, min(mx, base + n_grupos * per_group * max(n_series, 1)))


# ── Bloque editable ─────────────────────────────────────────────────────────

def _editable(texto, clase_extra=''):
    uid = _uid()
    return f'''<div class="editable-wrapper {clase_extra}">
  <button class="btn-edit" onclick="toggleEdit('{uid}')" title="Editar">
    <i class="fas fa-pencil"></i>
  </button>
  <div id="ed-{uid}" class="editable-text" contenteditable="false">{texto}</div>
</div>'''


# ── Tarjeta KPI ─────────────────────────────────────────────────────────────

def _kpi_card(label, value, foot='', color=C_PRIMARY):
    return f'''<div class="kpi-card" style="border-left-color:{color}">
  <div class="kpi-label">{label}</div>
  <div class="kpi-value" style="color:{color}">{value}</div>
  {'<div class="kpi-foot">' + foot + '</div>' if foot else ''}
</div>'''


# ── Section header ──────────────────────────────────────────────────────────

def _section_header(num, titulo, subtitulo=''):
    sub_html = f'<div style="font-size:.85rem;color:{C_GRAY};margin-top:4px">{subtitulo}</div>' if subtitulo else ''
    return f'''<div class="section-header">
  <div class="section-num">{num}</div>
  <div>
    <div style="font-size:1.3rem;font-weight:700;color:{C_DARK}">{titulo}</div>
    {sub_html}
  </div>
</div>'''


# ── Tabla resumen por zona ───────────────────────────────────────────────────

def _tabla_zonas(resumen):
    filas = ''
    for i, row in enumerate(resumen):
        zona, tv, uv, nv, dt = row
        bg = '#ecf3ff' if i % 2 == 0 else 'white'
        color = _color_zona(zona)
        filas += f'''<tr style="background:{bg}">
  <td style="font-weight:700;color:{color};padding:8px 12px">{zona}</td>
  <td style="text-align:right;padding:8px 12px">{tv}</td>
  <td style="text-align:right;padding:8px 12px">{uv}</td>
  <td style="text-align:right;padding:8px 12px">{nv}</td>
  <td style="text-align:right;padding:8px 12px">{dt}</td>
</tr>'''
    return f'''<div class="chart-block" style="overflow-x:auto;margin-bottom:24px">
<table style="width:100%;border-collapse:collapse;font-size:.88rem">
  <thead>
    <tr style="background:{C_PRIMARY};color:white">
      <th style="padding:10px 12px;text-align:left">Zona</th>
      <th style="padding:10px 12px;text-align:right">Visitas totales</th>
      <th style="padding:10px 12px;text-align:right">Visitantes únicos</th>
      <th style="padding:10px 12px;text-align:right">Nuevos visitantes</th>
      <th style="padding:10px 12px;text-align:right">Estancia media</th>
    </tr>
  </thead>
  <tbody>{filas}</tbody>
</table>
</div>'''


# ── Mapa de calor CSS ────────────────────────────────────────────────────────

def _calendario_css(df_ref, year, month):
    df_ref = df_ref.copy()
    df_ref['fecha_d'] = pd.to_datetime(df_ref['fecha']).dt.date
    por_dia = df_ref.groupby('fecha_d')['total_visits'].sum()

    primer_dia = pd.Timestamp(year, month, 1)
    n_dias_mes = calendar.monthrange(year, month)[1]
    ultimo_dia = pd.Timestamp(year, month, n_dias_mes)

    todos_vals = [por_dia.get(d.date(), 0) for d in pd.date_range(primer_dia, ultimo_dia)]
    maxv = max(todos_vals) if todos_vals else 1
    minv = min(v for v in todos_vals if v > 0) if any(v > 0 for v in todos_vals) else 0

    header_cells = ''.join(f'<div class="cal-header">{d}</div>' for d in DIAS_CORTO)

    offset = primer_dia.dayofweek
    celdas = '<div class="cal-empty"></div>' * offset

    for day_num in range(1, n_dias_mes + 1):
        fecha_d = pd.Timestamp(year, month, day_num).date()
        v = int(por_dia.get(fecha_d, 0))
        if v > 0 and maxv > minv:
            t = max(0.0, min(1.0, (v - minv) / (maxv - minv)))
        else:
            t = 0.0
        if v > 0:
            bg = _interpolar_hex(t)
            txt_color = 'white' if t > 0.52 else C_DARK
            label = f'{day_num}<br><small style="font-size:.65rem">{_fmt(v)}</small>'
        else:
            bg = '#f0f0f0'
            txt_color = C_GRAY
            label = str(day_num)
        celdas += f'<div class="cal-cell" style="background:{bg};color:{txt_color}">{label}</div>'

    total_cells = offset + n_dias_mes
    tail = (7 - total_cells % 7) % 7
    celdas += '<div class="cal-empty"></div>' * tail

    return f'''<div style="margin-bottom:16px">
  <div class="cal-grid">{header_cells}{celdas}</div>
</div>'''


# ── Portada ──────────────────────────────────────────────────────────────────

def _html_portada(titulo, periodo_str, ubicaciones, fecha_gen):
    ubi_items = ''.join(f'<li style="margin:4px 0;font-size:1rem;color:rgba(255,255,255,.9)">{u}</li>' for u in ubicaciones)
    return f'''<div style="background:linear-gradient(135deg,#0052CC 0%,#003d99 100%);
              min-height:100vh;display:flex;flex-direction:column;
              justify-content:center;padding:60px;box-sizing:border-box;
              page-break-after:always">
  <div style="font-size:.85rem;font-weight:700;letter-spacing:2px;
              color:rgba(255,255,255,.6);text-transform:uppercase;margin-bottom:16px">
    Informe de análisis de afluencia
  </div>
  <h1 style="font-size:3.5rem;font-weight:700;color:white;margin:0 0 16px;line-height:1.15">{titulo}</h1>
  <div style="font-size:1.25rem;color:rgba(255,255,255,.75);margin-bottom:40px">{periodo_str}</div>
  <div style="width:60px;height:4px;background:rgba(255,255,255,.4);margin-bottom:32px"></div>
  <div style="font-size:.75rem;font-weight:700;text-transform:uppercase;
              letter-spacing:1.5px;color:rgba(255,255,255,.55);margin-bottom:12px">
    Emplazamientos analizados
  </div>
  <ul style="list-style:none;padding:0;margin:0 0 48px">{ubi_items}</ul>
  <div style="font-size:.8rem;color:rgba(255,255,255,.45);font-style:italic">
    Generado el {fecha_gen} &nbsp;·&nbsp; Uso interno · Información confidencial
  </div>
</div>'''


# ── Sección 1 — Visión global ────────────────────────────────────────────────

def _sec_vision_global(df, zonas, periodo_str):
    z_ext = _zona_exterior(zonas)
    z_int = _zona_interior(zonas)
    df_e = df[df['Zona'] == z_ext] if z_ext else df
    df_i = df[df['Zona'] == z_int] if z_int else pd.DataFrame()

    total_v  = int(df_e['total_visits'].sum())
    n_dias   = df_e['fecha'].dt.date.nunique() if not df_e.empty else df['fecha'].dt.date.nunique()
    avg_day  = total_v / max(n_dias, 1)
    uv_dia   = df_e['unique_visitors'].mean() if not df_e.empty else df['unique_visitors'].mean()
    nv_total = int(df_e['new_visitors'].sum()) if 'new_visitors' in df_e.columns else 0
    dt_media = (df_i['dwell_time'].mean() if not df_i.empty and 'dwell_time' in df_i.columns
                else df['dwell_time'].mean() if 'dwell_time' in df.columns else 0)
    n_zonas  = len(zonas)

    intro_txt = (f"Durante el periodo {periodo_str} se registraron <strong>{_fmt(total_v)}</strong> visitas totales "
                 f"en <strong>{n_zonas}</strong> zona{'s' if n_zonas != 1 else ''}, "
                 f"con una media de <strong>{_fmt(int(avg_day))}</strong> visitas por día.")

    kpis = ''.join([
        _kpi_card('Visitas totales', _fmt(total_v), 'Todas las entradas (incl. recurrentes)', C_EXT),
        _kpi_card('Visitantes', f'{uv_dia:.0f}', 'Personas distintas · media/día', C_INT),
        _kpi_card('Nuevos visitantes', _fmt(nv_total), 'Primera visita registrada', C_SUCCESS),
        _kpi_card('Estancia media', f'{dt_media/60:.1f} min' if pd.notna(dt_media) and dt_media > 0 else '-',
                  z_int or 'Interior', C_CAJA),
    ])

    resumen_rows = []
    for zona in _ordenar_zonas(zonas):
        dz = df[df['Zona'] == zona]
        tv = _fmt(dz['total_visits'].sum())
        uv_m = f"{dz['unique_visitors'].mean():.0f}" if 'unique_visitors' in dz.columns else '-'
        nv   = _fmt(dz['new_visitors'].sum()) if 'new_visitors' in dz.columns else '-'
        dt_z = dz['dwell_time'].mean() if 'dwell_time' in dz.columns else float('nan')
        dt_s = f"{dt_z/60:.1f} min" if pd.notna(dt_z) and dt_z > 0 else '-'
        resumen_rows.append((zona, tv, uv_m, nv, dt_s))

    df['YearMes'] = df['fecha'].dt.to_period('M').astype(str)
    meses_ord = sorted(df['YearMes'].unique())

    fig_barras = go.Figure()
    all_vals_barras = []
    for z in _ordenar_zonas(zonas):
        df_z = df[df['Zona'] == z].groupby('YearMes')['total_visits'].sum()
        vals = [int(df_z.get(m, 0)) for m in meses_ord]
        all_vals_barras.extend(vals)
        fig_barras.add_trace(go.Bar(name=z, x=meses_ord, y=vals, marker_color=_color_zona(z),
                                    cliponaxis=False))
    fig_barras.update_layout(
        barmode='group', title_text='Tráfico total por mes y zona',
        legend=dict(orientation='h', yanchor='bottom', y=-0.3),
        margin=dict(t=60, b=60, l=40, r=20),
        height=_bar_height(len(meses_ord), len(zonas)),
        plot_bgcolor='white', paper_bgcolor='white',
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor='#f0f0f0', range=[0, _ymax_padded(all_vals_barras)]),
    )

    df['diaw'] = df['fecha'].dt.dayofweek
    df_ext_all = df[df['Zona'] == z_ext] if z_ext else df
    por_dia = df_ext_all.groupby('diaw')['unique_visitors'].mean()
    vals_dia = [float(por_dia.get(d, 0)) for d in range(7)]
    max_idx = vals_dia.index(max(vals_dia)) if any(v > 0 for v in vals_dia) else 0
    colores_dia = [C_PRIMARY if i == max_idx else '#a8c4e8' for i in range(7)]

    fig_dow = go.Figure(go.Bar(
        x=DIAS_CORTO, y=vals_dia,
        marker_color=colores_dia,
        text=[f'{v:.0f}' for v in vals_dia], textposition='outside',
        cliponaxis=False,
    ))
    fig_dow.update_layout(
        title_text='Patrón por día de la semana (media visitantes únicos)',
        margin=dict(t=60, b=40, l=40, r=20), height=320,
        plot_bgcolor='white', paper_bgcolor='white',
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor='#f0f0f0', range=[0, _ymax_padded(vals_dia)]),
    )

    return f'''{_section_header('1', 'Visión Global del Periodo', periodo_str)}
{_editable(intro_txt, 'mb-3')}
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:28px">
  {kpis}
</div>
{_tabla_zonas(resumen_rows)}
<div class="chart-block" style="margin-bottom:28px">{_fig_html(fig_barras)}</div>
<div class="chart-block" style="margin-bottom:48px">{_fig_html(fig_dow)}</div>'''


# ── Sección 2 — Análisis mes a mes ──────────────────────────────────────────

def _bloque_2a(df_ubi, zonas, nombre_mes, year, mes):
    z_ext = _zona_exterior(zonas)
    z_int = _zona_interior(zonas)
    df_e = df_ubi[df_ubi['Zona'] == z_ext] if z_ext else df_ubi
    df_i = df_ubi[df_ubi['Zona'] == z_int] if z_int else pd.DataFrame()

    tv   = int(df_e['total_visits'].sum())
    uv   = df_e['unique_visitors'].mean() if not df_e.empty else df_ubi['unique_visitors'].mean()
    nv   = int(df_e['new_visitors'].sum()) if 'new_visitors' in df_e.columns else 0
    dt   = (df_i['dwell_time'].mean() if not df_i.empty and 'dwell_time' in df_i.columns
            else df_ubi['dwell_time'].mean() if 'dwell_time' in df_ubi.columns else float('nan'))

    intro = (f"En {nombre_mes} se acumularon <strong>{_fmt(tv)}</strong> visitas, "
             f"con una media de <strong>{uv:.0f}</strong> visitantes únicos al día.")

    kpis = ''.join([
        _kpi_card('Visitas totales', _fmt(tv), 'Todas las entradas (incl. recurrentes)', C_EXT),
        _kpi_card('Visitantes únicos', f'{uv:.0f}', 'Personas distintas · media/día', C_INT),
        _kpi_card('Nuevos visitantes', _fmt(nv), 'Primera visita', C_SUCCESS),
        _kpi_card('Estancia media',
                  f'{dt/60:.1f} min' if pd.notna(dt) and dt > 0 else '-',
                  z_int or 'Interior', C_CAJA),
    ])

    df_ubi = df_ubi.copy()
    df_ubi['dia'] = df_ubi['fecha'].dt.day
    dias_unicos = sorted(df_ubi['dia'].unique())

    fig = go.Figure()
    all_vals_2a = []
    for z in _ordenar_zonas(zonas):
        dz = df_ubi[df_ubi['Zona'] == z].groupby('dia')['total_visits'].sum()
        vals = [int(dz.get(d, 0)) for d in dias_unicos]
        all_vals_2a.extend(vals)
        fig.add_trace(go.Bar(name=z, x=dias_unicos, y=vals, marker_color=_color_zona(z),
                             cliponaxis=False))
    fig.update_layout(
        barmode='group', title_text=f'Tráfico diario por zona — {nombre_mes}',
        legend=dict(orientation='h', yanchor='bottom', y=-0.3),
        margin=dict(t=60, b=60, l=40, r=20),
        height=_bar_height(len(dias_unicos), len(zonas)),
        plot_bgcolor='white', paper_bgcolor='white',
        xaxis=dict(title='Día del mes', showgrid=False),
        yaxis=dict(gridcolor='#f0f0f0', range=[0, _ymax_padded(all_vals_2a)]),
    )

    return f'''<h4 style="font-size:.95rem;font-weight:700;color:{C_PRIMARY};margin:20px 0 10px;
              border-left:3px solid {C_PRIMARY};padding-left:10px">2.A — KPIs y Evolución Diaria</h4>
{_editable(intro, 'mb-3')}
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px">
  {kpis}
</div>
<div class="chart-block" style="margin-bottom:20px">{_fig_html(fig)}</div>'''


def _bloque_2b(df_ubi, nombre_mes):
    if 'hourly_visits' not in df_ubi.columns:
        return ''
    df_ubi = df_ubi.copy()
    df_ubi['hourly_array'] = df_ubi['hourly_visits'].apply(_parsear_horas)
    horas_tot = [0] * 24
    for arr in df_ubi['hourly_array']:
        horas_tot = [a + b for a, b in zip(horas_tot, arr)]

    rango = list(range(6, 24))
    vals  = [horas_tot[h] for h in rango]
    if sum(vals) == 0:
        return ''

    cats = [f'{h:02d}:00' for h in rango]
    max_v = max(vals)
    intensidades = [v / max_v if max_v > 0 else 0 for v in vals]
    colores = [f'rgba(0,82,204,{0.3 + 0.7*t:.2f})' for t in intensidades]

    h_max_idx = vals.index(max(vals))
    activos = [i for i, v in enumerate(vals) if v > 0]
    h_min_idx = min(activos, key=lambda i: vals[i]) if activos else 0

    texto_hora = (f"Hora pico: <strong>{rango[h_max_idx]:02d}:00</strong> "
                  f"({_fmt(vals[h_max_idx])} visitas acumuladas) &nbsp;·&nbsp; "
                  f"Menor actividad: <strong>{rango[h_min_idx]:02d}:00</strong>")

    fig = go.Figure(go.Bar(
        x=cats, y=vals,
        marker_color=colores,
        text=[_fmt(v) if v > 0 else '' for v in vals],
        textposition='outside', textfont=dict(size=9),
        cliponaxis=False,
    ))
    fig.update_layout(
        title_text=f'Distribución horaria acumulada — {nombre_mes}',
        margin=dict(t=60, b=60, l=40, r=20), height=340,
        plot_bgcolor='white', paper_bgcolor='white',
        xaxis=dict(title='Hora', showgrid=False, tickangle=-45),
        yaxis=dict(gridcolor='#f0f0f0', range=[0, _ymax_padded(vals)]),
    )

    return f'''<h4 style="font-size:.95rem;font-weight:700;color:{C_PRIMARY};margin:24px 0 10px;
              border-left:3px solid {C_PRIMARY};padding-left:10px">2.B — Distribución Horaria</h4>
<div class="chart-block" style="margin-bottom:12px">{_fig_html(fig)}</div>
{_editable(texto_hora, 'mb-3')}'''


def _bloque_2c(df_ubi, zonas, nombre_mes, year, mes):
    z_ext = _zona_exterior(zonas)
    df_ref = df_ubi[df_ubi['Zona'] == z_ext].copy() if z_ext else df_ubi.copy()

    df_ref['diaw'] = pd.to_datetime(df_ref['fecha']).dt.dayofweek
    por_dia = df_ref.groupby('diaw')['total_visits'].sum()
    if not por_dia.empty and por_dia.sum() > 0:
        dia_max = int(por_dia.idxmax())
        texto_max = (f"Mayor afluencia: <strong>{DIAS_ES[dia_max]}</strong> "
                     f"({_fmt(int(por_dia[dia_max]))} visitas acumuladas en el mes)")
    else:
        texto_max = 'Sin datos suficientes para determinar el día de mayor afluencia.'

    cal_html = _calendario_css(df_ref, year, mes)

    return f'''<h4 style="font-size:.95rem;font-weight:700;color:{C_PRIMARY};margin:24px 0 10px;
              border-left:3px solid {C_PRIMARY};padding-left:10px">2.C — Mapa de Actividad Semanal</h4>
<div style="max-width:560px;margin-bottom:12px">{cal_html}</div>
{_editable(texto_max, 'mb-3')}'''


def _bloque_2d(df_ubi, zonas, nombre_mes):
    z_ext = _zona_exterior(zonas)
    z_int = _zona_interior(zonas)
    if not z_ext or not z_int:
        return ''

    df_e = df_ubi[df_ubi['Zona'] == z_ext].copy()
    df_i = df_ubi[df_ubi['Zona'] == z_int].copy()
    if df_e.empty or df_i.empty:
        return ''

    df_e['fecha_d'] = pd.to_datetime(df_e['fecha']).dt.date
    df_i['fecha_d'] = pd.to_datetime(df_i['fecha']).dt.date
    uv_e = df_e.groupby('fecha_d')['unique_visitors'].sum().reset_index(name='ext')
    uv_i = df_i.groupby('fecha_d')['unique_visitors'].sum().reset_index(name='int')
    merged = pd.merge(uv_e, uv_i, on='fecha_d')
    merged = merged[merged['ext'] > 0]
    if merged.empty:
        return ''

    merged['ratio'] = (merged['int'] / merged['ext'] * 100).round(1)
    ratio_medio = merged['ratio'].mean()
    ratio_max   = merged['ratio'].max()
    ratio_min   = merged['ratio'].min()

    color_ratio = C_SUCCESS if ratio_medio >= 50 else (C_WARN if ratio_medio >= 25 else C_DANGER)

    kpis = ''.join([
        _kpi_card('Ratio medio de atracción', f'{ratio_medio:.1f}%',
                  '≥50% óptimo · ≥25% aceptable', color_ratio),
        _kpi_card('Ratio máximo registrado', f'{ratio_max:.1f}%', 'Mejor día del mes', C_SUCCESS),
        _kpi_card('Ratio mínimo registrado', f'{ratio_min:.1f}%', 'Día más bajo del mes', C_DANGER),
    ])

    cats = [d.strftime('%d') for d in merged['fecha_d']]
    fig = go.Figure(go.Scatter(
        x=cats, y=merged['ratio'].tolist(),
        mode='lines+markers',
        line=dict(color=C_PRIMARY, width=2),
        marker=dict(size=5, color=C_PRIMARY),
        fill='tozeroy', fillcolor='rgba(0,82,204,.08)',
    ))
    fig.add_hline(y=50, line_dash='dot', line_color=C_SUCCESS,
                  annotation_text='50% (óptimo)', annotation_position='top right')
    fig.add_hline(y=25, line_dash='dot', line_color=C_WARN,
                  annotation_text='25% (mínimo)', annotation_position='top right')
    fig.update_layout(
        title_text=f'Evolución diaria del ratio exterior → interior — {nombre_mes} (%)',
        margin=dict(t=60, b=40, l=40, r=20), height=300,
        plot_bgcolor='white', paper_bgcolor='white',
        xaxis=dict(title='Día del mes', showgrid=False),
        yaxis=dict(gridcolor='#f0f0f0', ticksuffix='%'),
    )

    nivel = 'alta' if ratio_medio >= 50 else ('moderada' if ratio_medio >= 25 else 'baja')
    interp = (f"De cada 100 personas que pasan por {z_ext}, {int(ratio_medio)} acceden a {z_int} "
              f"(ratio medio {ratio_medio:.1f}%, conversión {nivel}).")

    return f'''<h4 style="font-size:.95rem;font-weight:700;color:{C_PRIMARY};margin:24px 0 10px;
              border-left:3px solid {C_PRIMARY};padding-left:10px">2.D — Ratio de Atracción</h4>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:20px">
  {kpis}
</div>
<div class="chart-block" style="margin-bottom:12px">{_fig_html(fig)}</div>
{_editable(interp, 'mb-3')}'''


def _bloque_2e(df_ubi):
    cols_disponibles = [c for c in ['uv_7d', 'uv_28d', 'freq_7d', 'freq_28d']
                        if c in df_ubi.columns]
    if not cols_disponibles:
        return ''

    etiquetas = {
        'uv_7d':    ('Visitantes únicos 7d', 'Rolling 7 días', C_INT),
        'uv_28d':   ('Visitantes únicos 28d', 'Rolling 28 días', C_INT),
        'freq_7d':  ('Frecuencia retorno 7d', 'Veces por semana', C_OTRO),
        'freq_28d': ('Frecuencia retorno 28d', 'Veces al mes', C_OTRO),
    }

    kpis = ''
    for col in cols_disponibles:
        v = df_ubi[col].mean() if col.startswith('freq') else df_ubi[col].sum()
        val_str = f'{v:.2f}x' if col.startswith('freq') else _fmt(v)
        etiq, foot, color = etiquetas[col]
        kpis += _kpi_card(etiq, val_str, foot, color)

    n_cols = len(cols_disponibles)
    grid_cols = f'repeat({min(n_cols, 4)}, 1fr)'

    return f'''<h4 style="font-size:.95rem;font-weight:700;color:{C_PRIMARY};margin:24px 0 10px;
              border-left:3px solid {C_PRIMARY};padding-left:10px">2.E — KPIs de Fidelización</h4>
<div style="display:grid;grid-template-columns:{grid_cols};gap:16px;margin-bottom:20px">
  {kpis}
</div>'''


def _sec_mes_a_mes(df, zonas, ubicaciones):
    df = df.copy()
    df['Año'] = df['fecha'].dt.year
    df['Mes']  = df['fecha'].dt.month

    meses_presentes = sorted(
        df[['Año', 'Mes']].drop_duplicates().itertuples(index=False),
        key=lambda r: (r.Año, r.Mes)
    )

    bloques = []
    idx_global = 1

    for registro in meses_presentes:
        year, mes = registro.Año, registro.Mes
        nombre_mes = f'{MESES_ES[mes]} {year}'
        df_mes = df[(df['Año'] == year) & (df['Mes'] == mes)].copy()
        if df_mes.empty:
            continue

        for ubi in sorted(df_mes['Ubicación'].unique()):
            df_ubi = df_mes[df_mes['Ubicación'] == ubi].copy()
            zonas_ubi = _ordenar_zonas(df_ubi['Zona'].unique().tolist())
            ubi_label = f' &nbsp;·&nbsp; {ubi}' if len(ubicaciones) > 1 else ''

            cabecera = f'''<div style="background:{C_LIGHT};border-radius:8px;
                          padding:16px 20px;margin:40px 0 20px;
                          border-left:5px solid {C_PRIMARY}">
  <div style="display:flex;align-items:center;gap:12px">
    <div style="background:{C_PRIMARY};color:white;border-radius:50%;
                width:32px;height:32px;display:flex;align-items:center;
                justify-content:center;font-weight:700;font-size:.85rem;flex-shrink:0">
      2.{idx_global}
    </div>
    <div style="font-size:1.1rem;font-weight:700;color:{C_DARK}">
      {nombre_mes}{ubi_label}
    </div>
  </div>
</div>'''

            contenido = (
                _bloque_2a(df_ubi, zonas_ubi, nombre_mes, year, mes) +
                _bloque_2b(df_ubi, nombre_mes) +
                _bloque_2c(df_ubi, zonas_ubi, nombre_mes, year, mes) +
                _bloque_2d(df_ubi, zonas_ubi, nombre_mes) +
                _bloque_2e(df_ubi)
            )

            bloques.append(cabecera + contenido)
            idx_global += 1

    return _section_header('2', 'Análisis Mes a Mes') + '\n'.join(bloques)


# ── Sección 3 — Conclusiones ─────────────────────────────────────────────────

def _calcular_conclusiones(df, zonas):
    conclusiones = []
    COLS_PALETA = [C_EXT, C_INT, C_PRIMARY, C_SUCCESS, C_WARN, C_CAJA, C_DANGER]

    z_ext = _zona_exterior(zonas)
    z_int = _zona_interior(zonas)
    df_e = df[df['Zona'] == z_ext].copy() if z_ext else df.copy()
    df_i = df[df['Zona'] == z_int].copy() if z_int else pd.DataFrame()
    df_e['fecha'] = pd.to_datetime(df_e['fecha'])

    # 1. Volumen global
    total = int(df_e['total_visits'].sum())
    n_dias = df_e['fecha'].dt.date.nunique()
    avg_day = total / max(n_dias, 1)
    conclusiones.append(('Volumen de afluencia',
        f"Durante el periodo se registraron <strong>{_fmt(total)}</strong> visitas totales, "
        f"con una media de <strong>{_fmt(int(avg_day))}</strong> visitas por día."))

    # 2. Distribución mensual
    df_e['YM'] = df_e['fecha'].dt.to_period('M')
    por_mes = df_e.groupby('YM')['total_visits'].sum()
    if len(por_mes) > 1:
        mes_max = por_mes.idxmax()
        mes_min = por_mes.idxmin()
        conclusiones.append(('Distribución mensual',
            f"<strong>{MESES_ES[mes_max.month]}</strong> fue el mes de mayor actividad "
            f"({_fmt(int(por_mes[mes_max]))} visitas). "
            f"<strong>{MESES_ES[mes_min.month]}</strong> registró la menor afluencia "
            f"({_fmt(int(por_mes[mes_min]))} visitas)."))

    # 3. Patrón semanal
    df_e['diaw'] = df_e['fecha'].dt.dayofweek
    por_dia = df_e.groupby('diaw')['total_visits'].mean()
    if not por_dia.empty:
        dia_max = int(por_dia.idxmax())
        dias_finde = [d for d in [5, 6] if d in por_dia.index]
        entre_sem = por_dia[[d for d in [0,1,2,3,4] if d in por_dia.index]].mean()
        fin_sem = por_dia[dias_finde].mean() if dias_finde else float('nan')
        if not np.isnan(fin_sem) and entre_sem > 0:
            ratio_fw = fin_sem / entre_sem
            if ratio_fw > 1.1:
                patron = f"El fin de semana genera {ratio_fw:.1f}x la afluencia media laboral."
            elif ratio_fw < 0.9:
                patron = f"El perfil es marcadamente laboral: entre semana {1/ratio_fw:.1f}x más visitas que en fin de semana."
            else:
                patron = "La afluencia se distribuye de manera homogénea a lo largo de toda la semana."
        else:
            patron = ''
        conclusiones.append(('Patrón semanal',
            f"El <strong>{DIAS_ES[dia_max]}</strong> concentra la mayor afluencia media del periodo "
            f"({_fmt(int(por_dia[dia_max]))} visitas/día). {patron}"))

    # 4. Ratio de atracción
    if z_ext and z_int and not df_i.empty:
        df_i2 = df_i.copy()
        df_i2['fecha'] = pd.to_datetime(df_i2['fecha'])
        df_e['fd'] = df_e['fecha'].dt.date
        df_i2['fd'] = df_i2['fecha'].dt.date
        uv_e = df_e.groupby('fd')['unique_visitors'].sum()
        uv_i = df_i2.groupby('fd')['unique_visitors'].sum()
        merged = pd.merge(uv_e, uv_i, left_index=True, right_index=True, suffixes=('_e','_i'))
        merged = merged[merged['unique_visitors_e'] > 0]
        if not merged.empty:
            ratio = (merged['unique_visitors_i'] / merged['unique_visitors_e'] * 100).mean()
            nivel = 'alta' if ratio >= 50 else ('moderada' if ratio >= 25 else 'baja')
            accion = ('Mantener la propuesta de valor en escaparate y acciones de fidelización.' if ratio >= 50
                      else 'Reforzar la señalización exterior y activar acciones de captación en puerta.' if ratio >= 25
                      else 'Se recomienda revisar la visibilidad del establecimiento y activar campañas de captación.')
            conclusiones.append(('Ratio de atracción exterior → interior',
                f"De cada 100 personas que pasan por la zona exterior, {int(ratio)} acceden al interior "
                f"(ratio {ratio:.1f}%, conversión {nivel}). {accion}"))

    # 5. Captación vs. fidelización
    if 'new_visitors' in df_e.columns and 'unique_visitors' in df_e.columns:
        nv = int(df_e['new_visitors'].sum())
        uv_t = df_e['unique_visitors'].sum()
        if uv_t > 0 and nv > 0:
            pct = nv / uv_t * 100
            tipo = ('alta captación de nuevos clientes' if pct > 60
                    else 'equilibrio entre captación y fidelización' if pct > 40
                    else 'base de clientes fidelizada con alta recurrencia')
            conclusiones.append(('Captación vs. fidelización',
                f"El <strong>{pct:.1f}%</strong> de los visitantes únicos son nuevos "
                f"({_fmt(nv)} primeras visitas). Perfil de {tipo}."))

    # 6. Comportamiento en el interior
    if not df_i.empty and 'dwell_time' in df_i.columns:
        df_i3 = df_i.copy()
        dt = df_i3['dwell_time'].mean()
        dt_min = dt / 60 if pd.notna(dt) and dt > 0 else 0
        if dt_min > 0:
            nivel_dt = ('alta implicación con el espacio' if dt_min > 15
                        else 'exploración moderada' if dt_min > 8
                        else 'visita transaccional de corta duración')
            recom = ('El tiempo de permanencia es favorable para la conversión.' if dt_min >= 8
                     else 'Oportunidad de mejora en la experiencia de compra para prolongar la estancia.')
            conclusiones.append(('Comportamiento en el interior',
                f"La estancia media en {z_int} es de <strong>{dt_min:.1f} min</strong>, "
                f"indicador de {nivel_dt}. {recom}"))

    # 7. Tendencia del periodo
    df_trend = df_e.sort_values('fecha')
    n = len(df_trend)
    if n >= 30:
        tercio = n // 3
        v1 = df_trend.iloc[:tercio]['total_visits'].mean()
        v3 = df_trend.iloc[-tercio:]['total_visits'].mean()
        if v1 > 0:
            var_pct = (v3 - v1) / v1 * 100
            if var_pct > 10:
                tend = f"tendencia ascendente (<strong>+{var_pct:.1f}%</strong>): la afluencia ha mejorado hacia el cierre del periodo."
            elif var_pct < -10:
                tend = f"tendencia descendente (<strong>{var_pct:.1f}%</strong>): la afluencia ha disminuido en la segunda parte del periodo."
            else:
                tend = f"comportamiento estable (variación del {var_pct:+.1f}% entre el inicio y el cierre del periodo)."
            conclusiones.append(('Evolución temporal', f"Se detecta una {tend}"))

    return conclusiones, COLS_PALETA


def _sec_conclusiones(df, zonas, periodo_str):
    conclusiones, COLS_PALETA = _calcular_conclusiones(df, zonas)

    bloques_html = ''
    for i, (titulo_c, texto_c) in enumerate(conclusiones):
        color = COLS_PALETA[i % len(COLS_PALETA)]
        bloques_html += f'''<div style="display:flex;gap:16px;margin-bottom:20px">
  <div style="width:5px;border-radius:3px;background:{color};flex-shrink:0"></div>
  <div style="flex:1">
    <div style="font-size:.7rem;font-weight:700;text-transform:uppercase;
                letter-spacing:.5px;color:{color};margin-bottom:6px">{titulo_c}</div>
    {_editable(texto_c)}
  </div>
</div>'''

    pie = f'''<div style="text-align:center;margin-top:40px;padding-top:20px;
              border-top:1px solid {C_LGRAY};font-size:.78rem;color:{C_GRAY};font-style:italic">
  Análisis generado automáticamente &nbsp;·&nbsp; Para uso interno
</div>'''

    return _section_header('3', 'Conclusiones y Hallazgos', f'Síntesis automática del periodo · {periodo_str}') + bloques_html + pie


# ── CSS global ────────────────────────────────────────────────────────────────

CSS = f"""
*, *::before, *::after {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       color: {C_DARK}; background: #f4f6f9; margin: 0; padding: 0; font-size: 15px; }}
.container {{ max-width: 1040px; margin: 0 auto; padding: 32px 24px 64px; }}
.editable-wrapper {{ position: relative; padding-right: 36px; }}
.btn-edit {{ position: absolute; top: 4px; right: 4px; opacity: 0.28; background: white;
            border: 1px solid #dee2e6; border-radius: 4px; padding: 2px 7px; cursor: pointer;
            transition: opacity .15s; font-size: .75rem; color: {C_GRAY};
            box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.editable-wrapper:hover .btn-edit {{ opacity: 1; }}
.editable-text.is-editing {{ outline: 2px solid {C_PRIMARY}; border-radius: 4px;
                             padding: 6px; background: #f0f5ff; }}
.mb-3 {{ margin-bottom: 16px; }}
.kpi-card {{ background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.08);
            border-left: 4px solid {C_PRIMARY}; }}
.kpi-label {{ font-size: .65rem; font-weight: 700; color: {C_GRAY}; text-transform: uppercase;
             letter-spacing: .5px; margin-bottom: 4px; }}
.kpi-value {{ font-size: 1.8rem; font-weight: 700; line-height: 1; }}
.kpi-foot {{ font-size: .72rem; color: {C_GRAY}; margin-top: 4px; }}
.section-header {{ display: flex; align-items: flex-start; gap: 16px; margin: 48px 0 24px;
                  padding-bottom: 12px; border-bottom: 3px solid {C_PRIMARY}; }}
.section-num {{ background: {C_PRIMARY}; color: white; border-radius: 50%; width: 36px; height: 36px;
               display: flex; align-items: center; justify-content: center; font-weight: 700;
               font-size: .9rem; flex-shrink: 0; }}
.cal-grid {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; }}
.cal-header {{ font-size: .7rem; font-weight: 700; color: #fff; background: {C_PRIMARY};
              text-align: center; padding: 4px 2px; border-radius: 3px; }}
.cal-cell {{ text-align: center; font-size: .78rem; padding: 6px 2px; border-radius: 4px;
            min-height: 36px; display: flex; align-items: center; justify-content: center;
            flex-direction: column; font-weight: 500; }}
.cal-empty {{ background: #f8f9fa; border-radius: 4px; min-height: 36px; }}
.chart-block {{ background: white; border-radius: 8px; padding: 8px;
               box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
.fab-toolbar {{ position: fixed; bottom: 24px; right: 24px; display: flex; flex-direction: column;
               gap: 8px; z-index: 9999; }}
.fab-btn {{ display: flex; align-items: center; gap: 8px; padding: 10px 18px; border: none;
           border-radius: 28px; font-size: .85rem; font-weight: 600; cursor: pointer;
           box-shadow: 0 4px 12px rgba(0,0,0,.18); transition: transform .12s, opacity .12s; }}
.fab-btn:hover {{ transform: translateY(-2px); opacity: .92; }}
.fab-save {{ background: #fff; color: {C_DARK}; border: 1.5px solid #dee2e6; }}
.fab-pdf  {{ background: {C_PRIMARY}; color: #fff; }}
@media print {{
  .btn-edit, .no-print, .fab-toolbar {{ display: none !important; }}
  .editable-wrapper {{ padding-right: 0 !important; }}
  .section-header {{ page-break-before: always; break-before: page; }}
  .chart-block, .kpi-card, table {{ page-break-inside: avoid; break-inside: avoid; }}
  body {{ background: white !important; font-size: 12px; }}
  .container {{ max-width: 100%; padding: 8px 16px; }}
  .kpi-value {{ font-size: 1.4rem !important; }}
  @page {{ margin: 1.5cm 1.2cm; size: A4; }}
}}
"""

def _build_js(server_url):
    pdf_btn_js = ''
    if server_url:
        pdf_btn_js = f"""
function generatePDF() {{
    const btn = document.getElementById('fab-pdf-btn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generando...';
    fetch('{server_url}api/html-to-pdf', {{
        method: 'POST',
        headers: {{'Content-Type': 'text/html; charset=utf-8'}},
        body: document.documentElement.outerHTML
    }})
    .then(r => {{ if (!r.ok) throw new Error(r.status); return r.blob(); }})
    .then(blob => {{
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = document.title.replace(/[^\\w\\s-]/g,'').trim().replace(/\\s+/g,'_') + '.pdf';
        a.click();
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-file-pdf"></i> Descargar PDF';
    }})
    .catch(e => {{
        alert('Error generando PDF: ' + e);
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-file-pdf"></i> Descargar PDF';
    }});
}}"""
    return f"""
function toggleEdit(uid) {{
    const el = document.getElementById('ed-' + uid);
    const btn = el.previousElementSibling;
    const editing = el.contentEditable === 'true';
    el.contentEditable = String(!editing);
    el.classList.toggle('is-editing', !editing);
    btn.innerHTML = !editing
        ? '<i class="fas fa-check" style="color:#28A745"></i>'
        : '<i class="fas fa-pencil"></i>';
    if (!editing) {{ el.focus(); placeCursorAtEnd(el); }}
}}
function placeCursorAtEnd(el) {{
    const range = document.createRange();
    const sel = window.getSelection();
    range.selectNodeContents(el);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
}}
function saveHTML() {{
    const html = document.documentElement.outerHTML;
    const blob = new Blob([html], {{type: 'text/html'}});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = document.title.replace(/[^\\w\\s-]/g,'').trim().replace(/\\s+/g,'_') + '_editado.html';
    a.click();
}}
{pdf_btn_js}
"""


# ── Función pública ───────────────────────────────────────────────────────────

def generar_reporte_html(df, start_date, end_date, org_nombre='', server_url='') -> str:
    """Retorna el HTML completo como string."""
    df = df.copy()
    df['fecha'] = pd.to_datetime(df['fecha'])

    df = df[df['Zona'] != 'SinNombre']
    df = df[~df['Zona'].str.contains(r'\bExtra\b|\bEnd\b|\bexit\b', case=False, na=False, regex=True)]

    zonas_globales = _ordenar_zonas(df['Zona'].unique().tolist())
    ubicaciones    = sorted(df['Ubicación'].unique().tolist())

    periodo_str = (f'{pd.Timestamp(start_date).strftime("%d/%m/%Y")} — '
                   f'{pd.Timestamp(end_date).strftime("%d/%m/%Y")}')
    fecha_gen = pd.Timestamp('today').strftime('%d de %B de %Y')

    titulo_portada = (org_nombre or
                      (ubicaciones[0] if len(ubicaciones) == 1
                       else f'{len(ubicaciones)} Emplazamientos'))

    portada   = _html_portada(titulo_portada, periodo_str, ubicaciones, fecha_gen)
    sec1      = _sec_vision_global(df, zonas_globales, periodo_str)
    sec2      = _sec_mes_a_mes(df, zonas_globales, ubicaciones)
    sec3      = _sec_conclusiones(df, zonas_globales, periodo_str)

    pdf_btn_html = (
        f'<button id="fab-pdf-btn" class="fab-btn fab-pdf" onclick="generatePDF()">'
        f'<i class="fas fa-file-pdf"></i> Descargar PDF</button>'
        if server_url else ''
    )

    fab_toolbar = f'''<div class="fab-toolbar no-print">
  <button class="fab-btn fab-save" onclick="saveHTML()">
    <i class="fas fa-floppy-disk"></i> Guardar HTML
  </button>
  {pdf_btn_html}
</div>'''

    doc = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Informe de afluencia — {titulo_portada}</title>
  <link rel="stylesheet"
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css"
    crossorigin="anonymous">
  <link rel="stylesheet"
    href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css"
    crossorigin="anonymous">
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <style>{CSS}</style>
</head>
<body>

{portada}

<div class="container">
  {sec1}
  {sec2}
  {sec3}
</div>

{fab_toolbar}

<script>{_build_js(server_url)}</script>
</body>
</html>"""

    return doc
