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
                "La lluvia tiene un efecto muy claro sobre el tráfico en esta ubicación: "
                "los días de precipitación son consistentemente los de menor afluencia. "
                "Esto es habitual en zonas exteriores o de paso, donde los transeúntes "
                "evitan salir o acortan su recorrido cuando llueve."
            ),
            "moderado_confirma": (
                "En los días de lluvia se aprecia una tendencia a menor afluencia, "
                "aunque el efecto no es igual de intenso en todo el período. "
                "Es probable que otros factores como eventos puntuales o temporadas "
                "hayan amortiguado el impacto en algunos momentos."
            ),
            "debil": (
                "La lluvia no parece haber afectado significativamente al tráfico "
                "en este período. Puede deberse a que la zona tiene zonas cubiertas, "
                "a que el volumen de visitantes habituales es constante independientemente "
                "del tiempo, o simplemente a que no llovió lo suficiente para marcar diferencia."
            ),
            "contradice": (
                "Aunque lo habitual es que la lluvia reduzca la afluencia, "
                "en este período no se ha observado esa relación. "
                "Es posible que eventos especiales, campañas comerciales u otros "
                "factores atrajeron visitantes incluso en los días de peor tiempo."
            ),
        },
    },
    "temp_max": {
        "direccion": "complejo",
        "frases": {
            "fuerte_confirma": (
                "Las temperaturas extremas muestran un impacto directo sobre la afluencia. "
                "Tanto el calor intenso como el frío pronunciado tienden a alejar a las "
                "personas de la calle. Los días más alejados del rango confortable (entre "
                "18 y 26 grados) coinciden con las caídas de tráfico más marcadas del período."
            ),
            "moderado_confirma": (
                "Hay una tendencia visible a menor afluencia en los días de temperatura "
                "extrema, aunque el efecto no es uniforme a lo largo del período. "
                "Otros factores como el día de la semana o eventos locales pueden "
                "haber compensado el impacto del calor o el frío en algunos momentos."
            ),
            "debil": (
                "La temperatura máxima no parece haber influido de forma relevante "
                "en el tráfico exterior durante este período. "
                "La afluencia se mantuvo relativamente estable al margen de las "
                "variaciones térmicas registradas."
            ),
            "contradice": (
                "La temperatura no siguió el patrón esperado en este período. "
                "El tráfico no mostró una relación clara con las subidas o "
                "bajadas de temperatura, lo que sugiere que otros factores "
                "tuvieron más peso en el comportamiento de la afluencia."
            ),
        },
    },
    "temp_min": {
        "direccion": "negativo",
        "frases": {
            "fuerte_confirma": (
                "Las noches frías tienen un efecto claro sobre el tráfico al día siguiente: "
                "los días con temperaturas mínimas más bajas concentran la menor afluencia "
                "del período. El frío nocturno puede ser un indicador de días "
                "más fríos en general, lo que desincentiva la salida a la calle."
            ),
            "moderado_confirma": (
                "Se aprecia cierta tendencia a menor afluencia en los días de mayor "
                "frío nocturno, aunque la relación no es constante. "
                "El efecto puede variar según la época del año o si coincide "
                "con fines de semana u otras variables."
            ),
            "debil": (
                "La temperatura mínima no muestra un vínculo claro con el tráfico "
                "exterior en este período. La afluencia no varió de forma consistente "
                "en función de las temperaturas nocturnas registradas."
            ),
            "contradice": (
                "A pesar de que el frío suele reducir la afluencia, en este período "
                "el tráfico no bajó de forma consistente en los días más fríos. "
                "Es posible que otros factores, como campañas específicas o "
                "temporadas de alta demanda, hayan sostenido la afluencia."
            ),
        },
    },
    "n_pasajeros_crucero_dia": {
        "direccion": "positivo",
        "frases": {
            "fuerte_confirma": (
                "Hay una relación muy clara entre la llegada de cruceros y el tráfico "
                "en la zona: los días con más pasajeros en el puerto son también "
                "los de mayor afluencia exterior. Los turistas de crucero suponen "
                "un aporte significativo y medible al tráfico de esta ubicación."
            ),
            "moderado_confirma": (
                "Los días con mayor volumen de pasajeros de crucero tienden a "
                "coincidir con más afluencia en la zona, aunque la relación "
                "no es siempre proporcional. El perfil del crucero, el número "
                "de horas en puerto o la climatología del día pueden hacer variar el impacto."
            ),
            "debil": (
                "El número de pasajeros de crucero no muestra una relación clara "
                "con el tráfico exterior en este período. Es posible que los "
                "cruceristas visiten otras zonas de la ciudad o que la muestra "
                "de datos aún no sea suficiente para detectar el patrón."
            ),
            "contradice": (
                "A pesar de los cruceros registrados, el tráfico exterior "
                "no aumentó de forma consistente en esas jornadas. "
                "Puede ser que los pasajeros se concentraran en otras zonas "
                "o que factores como el clima o el día de la semana "
                "limitaran su desplazamiento hasta esta ubicación."
            ),
        },
    },
    "n_pasajeros_crucero_oficial": {
        "direccion": "positivo",
        "frases": {
            "fuerte_confirma": (
                "Los datos oficiales de pasajeros portuarios confirman una relación "
                "directa con el tráfico exterior: cuanto mayor es la actividad en el "
                "puerto, mayor es la afluencia registrada en esta ubicación. "
                "El turismo de crucero es un factor de impacto real y cuantificable."
            ),
            "moderado_confirma": (
                "Los períodos con mayor volumen oficial de cruceristas tienden a "
                "coincidir con más afluencia exterior, aunque la relación no es "
                "perfectamente proporcional. Otros factores pueden moderar "
                "o amplificar el efecto según el momento del año."
            ),
            "debil": (
                "El volumen oficial de pasajeros de crucero no muestra una correlación "
                "significativa con el tráfico exterior en este período. "
                "La latencia de los datos oficiales (aproximadamente 25 días) "
                "puede dificultar la detección del efecto en ventanas cortas de análisis."
            ),
            "contradice": (
                "A pesar del volumen oficial de cruceristas, el tráfico exterior "
                "no respondió de forma consistente en los períodos de mayor actividad portuaria. "
                "Vale tener en cuenta que estos datos tienen una latencia de unos 25 días, "
                "lo que puede desplazar temporalmente la señal respecto al impacto real."
            ),
        },
    },
    "escala_crucero": {
        "direccion": "positivo",
        "frases": {
            "fuerte_confirma": (
                "Los días con barco en puerto son de forma sistemática los de mayor "
                "tráfico exterior en este período. La escala de crucero actúa como "
                "un catalizador claro: los pasajeros que desembarcan se distribuyen "
                "por la zona y generan un pico de afluencia bien identificable."
            ),
            "moderado_confirma": (
                "Los días con escala de crucero tienden a registrar más afluencia "
                "que los días sin barco, aunque el incremento no es siempre igual. "
                "El tamaño del barco, el tiempo disponible en tierra y "
                "la climatología del día pueden hacer que el efecto varíe bastante."
            ),
            "debil": (
                "Las escalas de crucero no muestran un impacto claro en el tráfico "
                "exterior durante este período. Puede que el número de escalas sea "
                "bajo, que los pasajeros se concentren en otras zonas, o que "
                "la distancia al puerto limite su llegada hasta esta ubicación."
            ),
            "contradice": (
                "A pesar de las escalas registradas, el tráfico exterior "
                "no mostró un patrón de incremento en esas jornadas. "
                "Esto puede deberse a que los pasajeros optaron por rutas o "
                "zonas diferentes, o a que otros factores negativos (tiempo, "
                "día de semana, etc.) limitaron el efecto esperado."
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
        f" El mejor ajuste se obtiene mirando lo que pasó {lag_dias} día{'s' if lag_dias != 1 else ''} antes, "
        f"lo que sugiere que esta señal anticipa el movimiento del tráfico con algo de adelanto."
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
                                    "Sin datos",
                                    className="fw-bold text-muted",
                                    style={"fontSize": "0.80rem"},
                                ),
                                width=3,
                                className="text-end d-flex align-items-center justify-content-end",
                            ),
                        ],
                        className="g-1 align-items-center",
                    ),
                    html.P(
                        "No hay suficientes registros en el período seleccionado para calcular "
                        "si esta señal tiene relación con el tráfico. Prueba a ampliar el rango de fechas.",
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
        movimiento = "bajó" if delta_pct < 0 else "subió"
        delta_color = "#DC3545" if delta_pct < 0 else "#28A745"
        delta_header = html.P(
            [
                html.Span(
                    f"El tráfico exterior {movimiento} un {abs(delta_pct):.0f}% "
                    f"respecto a la {periodo_label} anterior. ",
                    style={"fontWeight": "600", "color": delta_color},
                ),
                html.Span(
                    "A continuación se analiza qué factores externos pueden "
                    "explicar ese movimiento:",
                    className="text-muted",
                ),
            ],
            className="mb-2",
            style={"fontSize": "0.88rem"},
        )
    else:
        delta_header = html.P(
            "Análisis de factores externos que pueden estar influyendo en el tráfico exterior:",
            className="text-muted mb-2",
            style={"fontSize": "0.88rem"},
        )

    return html.Div(
        [
            delta_header,
            html.Div(items, style={"maxHeight": "380px", "overflowY": "auto"}),
        ]
    )
