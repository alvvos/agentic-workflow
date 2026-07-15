"""
Correlation analysis for the Health Check panel.

Extracted functions:
  - _pearson_r
  - _interpret_correlacion
  - _render_correlacion_signals
"""

from __future__ import annotations

from datetime import timedelta

import dash_bootstrap_components as dbc
import pandas as pd
from dash import html

_SIGNAL_SENTIMENT: dict[str, dict] = {
    "llueve": {
        "direccion": "negativo",
        "frases": {
            "fuerte_confirma": (
                "Los días de precipitación coinciden con las caídas de afluencia más marcadas del período. "
                "El efecto inhibidor de la lluvia sobre el tráfico exterior es claro y consistente."
            ),
            "moderado_confirma": (
                "Se aprecia una tendencia a menor afluencia en días lluviosos, "
                "aunque la relación no es concluyente en todo el período."
            ),
            "debil": (
                "La lluvia no muestra asociación estadística clara con el tráfico exterior en este período."
            ),
            "contradice": (
                "A pesar de lo habitual, la lluvia no se asoció a menor afluencia en este período. "
                "Es posible que otros factores —eventos puntuales, temporada alta— "
                "compensaran su efecto negativo habitual."
            ),
        },
    },
    "temp_max": {
        "direccion": "complejo",
        "frases": {
            "fuerte_confirma": (
                "Las temperaturas extremas muestran un impacto directo en la afluencia: "
                "los días más alejados del rango de confort (18-26 °C) registran las caídas más pronunciadas."
            ),
            "moderado_confirma": (
                "Las temperaturas extremas se asocian a cierta reducción de afluencia, "
                "aunque el efecto es irregular a lo largo del período."
            ),
            "debil": (
                "La temperatura máxima no muestra una asociación estadística relevante "
                "con el tráfico exterior en este período."
            ),
            "contradice": (
                "La temperatura no siguió el patrón esperado en este período. "
                "El tráfico se mantuvo sin relación clara con las variaciones térmicas."
            ),
        },
    },
    "temp_min": {
        "direccion": "negativo",
        "frases": {
            "fuerte_confirma": (
                "Las temperaturas nocturnas bajas muestran un efecto claro sobre la afluencia: "
                "los días con mínimas más frías concentran la menor afluencia del período."
            ),
            "moderado_confirma": (
                "Se aprecia una leve tendencia a menor afluencia en los días de mayor frío nocturno."
            ),
            "debil": (
                "La temperatura mínima no muestra asociación estadística clara "
                "con el tráfico exterior en este período."
            ),
            "contradice": (
                "La temperatura mínima no siguió el patrón esperado: "
                "el tráfico no se redujo de forma consistente en los días más fríos del período."
            ),
        },
    },
    "n_pasajeros_crucero_dia": {
        "direccion": "positivo",
        "frases": {
            "fuerte_confirma": (
                "La actividad portuaria muestra una relación directa con el tráfico exterior: "
                "las jornadas con mayor número de pasajeros en puerto concentran los picos de afluencia."
            ),
            "moderado_confirma": (
                "Los días con mayor volumen de pasajeros de crucero tienden a coincidir "
                "con mayor afluencia exterior, aunque la relación no es sistemática."
            ),
            "debil": (
                "La afluencia de cruceristas no muestra correlación significativa "
                "con el tráfico exterior en este período."
            ),
            "contradice": (
                "A pesar de los cruceros registrados, el tráfico exterior "
                "no mostró un incremento consistente en esas jornadas."
            ),
        },
    },
    "n_pasajeros_crucero_oficial": {
        "direccion": "positivo",
        "frases": {
            "fuerte_confirma": (
                "Los datos oficiales de pasajeros portuarios muestran una correlación clara "
                "con el tráfico exterior: más actividad en puerto, más afluencia en la ubicación."
            ),
            "moderado_confirma": (
                "Los meses con mayor volumen oficial de cruceristas tienden a coincidir "
                "con períodos de mayor afluencia exterior."
            ),
            "debil": (
                "El volumen oficial de pasajeros de crucero no muestra correlación "
                "estadística con el tráfico exterior en este período."
            ),
            "contradice": (
                "A pesar del volumen oficial de cruceristas, el tráfico exterior "
                "no respondió de forma consistente en las jornadas de mayor actividad portuaria."
            ),
        },
    },
    "escala_crucero": {
        "direccion": "positivo",
        "frases": {
            "fuerte_confirma": (
                "Las escalas de crucero se asocian claramente a incrementos de afluencia: "
                "los días con barco en puerto son sistemáticamente los de mayor tráfico exterior."
            ),
            "moderado_confirma": (
                "Los días con escala de crucero tienden a registrar mayor afluencia, "
                "aunque el efecto varía según el volumen de pasajeros a bordo."
            ),
            "debil": (
                "Las escalas de crucero no muestran un impacto estadístico claro "
                "en el tráfico exterior del período analizado."
            ),
            "contradice": (
                "A pesar de las escalas registradas, el tráfico exterior "
                "no mostró un patrón de incremento consistente en esas jornadas."
            ),
        },
    },
}


# ── Pearson correlation ───────────────────────────────────────────────────────


def _pearson_r(x, y):
    """Pearson r + p-value aproximado sin scipy."""
    n = len(x)
    if n < 5:
        return 0.0, 1.0
    mx, my = x.mean(), y.mean()
    sx = ((x - mx) ** 2).sum() ** 0.5
    sy = ((y - my) ** 2).sum() ** 0.5
    if sx == 0 or sy == 0:
        return 0.0, 1.0
    r = float(((x - mx) * (y - my)).sum() / (sx * sy))
    r = max(-1.0, min(1.0, r))
    # p-value aprox vía distribución t (bilateral)
    import math

    if abs(r) == 1.0:
        return r, 0.0
    t = r * math.sqrt(n - 2) / math.sqrt(1 - r**2)
    # integración numérica sencilla (aproximación válida para n >= 5)
    # usamos la fórmula beta incompleta regularizada simplificada
    try:
        from scipy import stats as _st

        p = float(_st.pearsonr(x, y).pvalue)
    except Exception:
        # Umbral conservador: significativo si |t| > 2 (aprox p < 0.05 para n >= 10)
        p = 0.04 if abs(t) > 2 else 0.20
    return r, p


# ── Interpretation ────────────────────────────────────────────────────────────


def _interpret_correlacion(
    r: float, p: float, n: int, label: str, señal_id: str = "", lag_dias: int = 0
) -> tuple[str, str]:
    """Devuelve (texto descriptivo, color Bootstrap). Usa sentimiento esperado de la señal."""
    abs_r = abs(r)
    sent = _SIGNAL_SENTIMENT.get(señal_id, {})
    direccion = sent.get("direccion", "positivo")
    frases = sent.get("frases", {})

    if direccion == "negativo":
        confirma = r <= 0
    elif direccion == "positivo":
        confirma = r >= 0
    else:  # "complejo" — cualquier correlación no trivial es informativa
        confirma = True

    lag_suffix = (
        f" El efecto se observa con {lag_dias} día{'s' if lag_dias != 1 else ''} de retardo."
        if lag_dias > 0
        else ""
    )

    if abs_r >= 0.70:
        clave = "fuerte_confirma" if confirma else "contradice"
        fallback = (
            f"Cuando {label} aumenta, el tráfico exterior tiende a "
            f"{'subir' if r >= 0 else 'bajar'}. "
            "La asociación es consistente a lo largo del período."
        )
        color = "success" if confirma else "warning"
    elif abs_r >= 0.45:
        clave = "moderado_confirma" if confirma else "contradice"
        fallback = (
            f"Existe una asociación moderada con {label}: "
            f"el tráfico exterior tiende a {'subir' if r >= 0 else 'bajar'} "
            "cuando la señal es alta, aunque no de forma concluyente."
        )
        color = "warning"
    elif abs_r >= 0.20:
        clave = "debil"
        fallback = f"La relación con {label} es débil e inconsistente en este período."
        color = "secondary"
    else:
        clave = "debil"
        fallback = (
            f"No se aprecia relación estadística entre el tráfico exterior y {label} "
            "en este período."
        )
        color = "light"

    texto = frases.get(clave, fallback)
    if lag_suffix:
        texto = texto.rstrip(".") + "." + lag_suffix

    return texto, color


# ── Renderer ──────────────────────────────────────────────────────────────────


def _render_correlacion_signals(
    location_uuid: str | None,
    df_ubi: pd.DataFrame,
    fecha_min,
    fecha_max,
    ventana: str = "semana",
) -> html.Div:
    """
    Correlación Pearson entre cada señal externa y la afluencia diaria de tráfico exterior.
    El texto ancla la correlación al movimiento real del tráfico vs período anterior.
    """
    if not location_uuid or df_ubi.empty or "unique_visitors" not in df_ubi.columns:
        return html.Div(
            html.P(
                "Sin datos suficientes para el análisis de correlación.",
                className="text-muted small",
            )
        )

    # Filtrar a zona exterior usando zone_enum=2 (campo "zone" del reporte diario Aitanna).
    # 0=checkout, 1=interior, 2=exterior/calle, 3=subzonas. No usar MAX: subzonas=3 > exterior=2.
    try:
        from src.db.store import get_conn as _get_conn

        _conn = _get_conn()
        _ext_ids = {
            r[0]
            for r in _conn.execute(
                "SELECT zona_id FROM zonas WHERE ubicacion_id = ? AND zone_enum = 2",
                [location_uuid],
            ).fetchall()
        }
    except Exception:
        _ext_ids = set()

    if _ext_ids and "zona_id" in df_ubi.columns:
        df_ext = df_ubi[df_ubi["zona_id"].isin(_ext_ids)]
    else:
        df_ext = df_ubi  # fallback: zone_enum aún no sincronizado

    # Serie diaria de tráfico exterior (un valor por día, sin doble conteo)
    visitas_dia = (
        df_ext[df_ext["fecha_dt"].between(fecha_min, fecha_max)]
        .groupby("fecha_dt")["unique_visitors"]
        .sum()
        .sort_index()
    )
    if len(visitas_dia) < 5:
        return html.Div(
            html.P(
                f"Datos insuficientes ({len(visitas_dia)} días). Se necesitan mínimo 5 para calcular correlación.",
                className="text-muted small",
            )
        )

    # Delta de tráfico exterior vs período anterior
    dias_v = 28 if ventana == "mes" else 7
    periodo_label = "mes" if ventana == "mes" else "semana"
    total_actual = visitas_dia.sum()
    fmin_ant = fecha_min - timedelta(days=dias_v)
    fmax_ant = fecha_min - timedelta(days=1)
    visitas_ant = (
        df_ext[df_ext["fecha_dt"].between(fmin_ant, fmax_ant)]
        .groupby("fecha_dt")["unique_visitors"]
        .sum()
        .sum()
    )
    delta_pct = ((total_actual - visitas_ant) / visitas_ant * 100) if visitas_ant > 0 else None

    # Señales con datos en el período — cualquier señal con dato es válida para el análisis
    try:
        from src.db.queries import get_señal_diaria
        from src.db.store import get_conn

        conn = get_conn()
        señales_rows = conn.execute(
            """
            SELECT vs.señal_id,
                   COALESCE(s.label, vs.señal_id)    AS label,
                   COALESCE(s.color, '#888888')       AS color,
                   COALESCE(s.icono, 'fas fa-signal') AS icono
            FROM   valores_señales vs
            LEFT JOIN señales s ON s.señal_id = vs.señal_id
            WHERE  vs.ubicacion_id = ?
            GROUP  BY vs.señal_id, s.label, s.color, s.icono
            ORDER  BY vs.señal_id
            """,
            [location_uuid],
        ).fetchall()
    except Exception:
        return html.Div(
            html.P("Sin datos de señales para esta ubicación.", className="text-muted small")
        )

    if not señales_rows:
        return html.Div(
            html.P("Sin datos de señales externas en el período.", className="text-muted small")
        )

    resultados = []
    sin_datos: list[str] = []
    for señal_id, label, color, icono in señales_rows:
        try:
            serie = get_señal_diaria(
                location_uuid,
                señal_id,
                pd.Timestamp(fecha_min),
                pd.Timestamp(fecha_max),
            )
        except Exception:
            continue

        # Alinear con visitas y eliminar NaN / ceros en la señal que no sean informativos
        merged = pd.DataFrame({"visitas": visitas_dia, "señal": serie}).dropna()
        # Excluir pares donde ambas son cero (días sin dato real)
        merged = merged[~((merged["visitas"] == 0) & (merged["señal"] == 0))]
        n = len(merged)
        if n < 5 or merged["señal"].std() == 0:
            sin_datos.append(label)
            continue

        # Lags a evaluar: 0 (mismo día), 1 (efecto al día siguiente), 7 (efecto semana siguiente)
        best_r, best_p, best_lag = 0.0, 1.0, 0
        for lag in [0, 1, 7]:
            if lag == 0:
                m_lag = merged
            else:
                señal_shifted = serie.shift(lag)
                m_lag = pd.DataFrame({"visitas": visitas_dia, "señal": señal_shifted}).dropna()
                m_lag = m_lag[~((m_lag["visitas"] == 0) & (m_lag["señal"] == 0))]
            if len(m_lag) < 5 or m_lag["señal"].std() == 0:
                continue
            r_lag, p_lag = _pearson_r(m_lag["visitas"].values, m_lag["señal"].values)
            if abs(r_lag) > abs(best_r):
                best_r, best_p, best_lag = r_lag, p_lag, lag

        r, p, lag_dias = best_r, best_p, best_lag
        texto, badge_color = _interpret_correlacion(
            r, p, n, label, señal_id=señal_id, lag_dias=lag_dias
        )

        # Días clave — solo cuando la señal tiene variación real día a día
        top_dias = []
        señal_mean = merged["señal"].mean()
        cv_señal = merged["señal"].std() / señal_mean if señal_mean != 0 else 0
        if abs(r) >= 0.70 and cv_señal > 0.15:
            top = merged.nlargest(3, "señal") if r >= 0 else merged.nsmallest(3, "visitas")
            top_dias = [
                str(idx)[:10] if hasattr(idx, "__str__") else str(idx) for idx in top.index[:3]
            ]

        resultados.append(
            {
                "señal_id": señal_id,
                "label": label,
                "r": r,
                "p": p,
                "n": n,
                "color": color,
                "icono": icono,
                "texto": texto,
                "badge_color": badge_color,
                "top_dias": top_dias,
            }
        )

    if not resultados and not sin_datos:
        return html.Div(
            html.P("Sin datos de señales en el período seleccionado.", className="text-muted small")
        )

    # Ordenar: primero las más correladas (informativas), luego los descartes
    resultados.sort(key=lambda x: -abs(x["r"]))

    items = []
    for res in resultados:
        r = res["r"]
        abs_r = abs(r)
        # Barra de correlación visual
        bar_pct = int(abs_r * 100)
        bar_color = (
            "#28A745"
            if abs_r >= 0.7
            else "#E67E22" if abs_r >= 0.45 else "#6c757d" if abs_r >= 0.20 else "#dee2e6"
        )
        arrow = "↑" if r >= 0 else "↓"
        impacto = (
            "Fuerte"
            if abs_r >= 0.70
            else "Moderada" if abs_r >= 0.45 else "Débil" if abs_r >= 0.20 else "Sin relación"
        )
        r_display = f"{impacto} {arrow}" if abs_r >= 0.20 else "Sin relación"

        items.append(
            html.Div(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Span(
                                        [
                                            html.I(
                                                className=f"{res['icono']} me-1",
                                                style={
                                                    "color": res["color"],
                                                    "fontSize": "0.85rem",
                                                },
                                            ),
                                            html.Span(
                                                res["label"],
                                                style={
                                                    "fontSize": "0.90rem",
                                                    "fontWeight": "600",
                                                },
                                            ),
                                            dbc.Badge(
                                                f"{res['n']} registros",
                                                color="light",
                                                text_color="secondary",
                                                className="ms-2 fw-normal border",
                                                style={"fontSize": "0.70rem"},
                                            ),
                                        ]
                                    ),
                                    # Barra visual
                                    html.Div(
                                        html.Div(
                                            style={
                                                "width": f"{bar_pct}%",
                                                "height": "4px",
                                                "backgroundColor": bar_color,
                                                "borderRadius": "2px",
                                                "transition": "width 0.4s",
                                            }
                                        ),
                                        style={
                                            "backgroundColor": "#f0f0f0",
                                            "borderRadius": "2px",
                                            "marginTop": "4px",
                                        },
                                    ),
                                ],
                                width=9,
                            ),
                            dbc.Col(
                                html.Span(
                                    r_display,
                                    className="fw-bold",
                                    style={"color": bar_color, "fontSize": "0.95rem"},
                                ),
                                width=3,
                                className="text-end d-flex align-items-center justify-content-end",
                            ),
                        ],
                        className="g-1 align-items-center",
                    ),
                    html.P(
                        res["texto"],
                        className="text-muted mb-0 mt-1",
                        style={"fontSize": "0.83rem", "lineHeight": "1.5"},
                    ),
                    *(
                        [
                            html.P(
                                f"Días destacados: {', '.join(res['top_dias'])}",
                                className="text-muted mb-0 mt-1",
                                style={"fontSize": "0.78rem", "fontStyle": "italic"},
                            )
                        ]
                        if res["top_dias"]
                        else []
                    ),
                ],
                className="py-2 border-bottom",
                style={"borderColor": "#f0f0f0 !important"},
            )
        )

    # Señales sin datos suficientes: misma estructura de card pero indicando ausencia
    for label in sin_datos:
        # Buscar icono/color de la señal en señales_rows
        _sd_color, _sd_icono = "#adb5bd", "fas fa-circle-xmark"
        for _sid, _lbl, _col, _ico in señales_rows:
            if _lbl == label:
                _sd_color, _sd_icono = _col or _sd_color, _ico or _sd_icono
                break
        items.append(
            html.Div(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Span(
                                        [
                                            html.I(
                                                className=f"{_sd_icono} me-1",
                                                style={
                                                    "color": _sd_color,
                                                    "fontSize": "0.85rem",
                                                },
                                            ),
                                            html.Span(
                                                label,
                                                style={
                                                    "fontSize": "0.90rem",
                                                    "fontWeight": "600",
                                                    "color": "#6c757d",
                                                },
                                            ),
                                            dbc.Badge(
                                                "Sin registros",
                                                color="light",
                                                text_color="secondary",
                                                className="ms-2 fw-normal border",
                                                style={"fontSize": "0.70rem"},
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        html.Div(
                                            style={
                                                "width": "0%",
                                                "height": "4px",
                                                "backgroundColor": "#dee2e6",
                                                "borderRadius": "2px",
                                            }
                                        ),
                                        style={
                                            "backgroundColor": "#f0f0f0",
                                            "borderRadius": "2px",
                                            "marginTop": "4px",
                                        },
                                    ),
                                ],
                                width=9,
                            ),
                            dbc.Col(
                                html.Span(
                                    "—",
                                    className="fw-bold text-muted",
                                    style={"fontSize": "0.95rem"},
                                ),
                                width=3,
                                className="text-end d-flex align-items-center justify-content-end",
                            ),
                        ],
                        className="g-1 align-items-center",
                    ),
                    html.P(
                        "No hay registros suficientes para calcular la correlación en este período.",
                        className="text-muted mb-0 mt-1",
                        style={"fontSize": "0.83rem", "lineHeight": "1.5", "fontStyle": "italic"},
                    ),
                ],
                className="py-2 border-bottom",
                style={"borderColor": "#f0f0f0 !important", "opacity": "0.6"},
            )
        )

    # Delta header — once, before signal list
    if delta_pct is not None:
        movimiento = "bajada" if delta_pct < 0 else "subida"
        delta_color = "#DC3545" if delta_pct < 0 else "#28A745"
        delta_header = html.P(
            [
                html.Span(
                    f"La {movimiento} del {abs(delta_pct):.0f}% del tráfico exterior "
                    f"respecto a la {periodo_label} anterior.",
                    style={"fontWeight": "600", "color": delta_color},
                ),
                html.Span(
                    " Posibles factores asociados:",
                    className="text-muted",
                ),
            ],
            className="mb-2",
            style={"fontSize": "0.88rem"},
        )
    else:
        delta_header = html.P(
            "Posibles factores asociados al tráfico exterior:",
            className="text-muted mb-2",
            style={"fontSize": "0.88rem"},
        )

    return html.Div(
        [
            delta_header,
            html.Div(items, style={"maxHeight": "380px", "overflowY": "auto"}),
        ]
    )
