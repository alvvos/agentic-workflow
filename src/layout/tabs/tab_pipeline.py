import dash_bootstrap_components as dbc
import dash_cytoscape as cyto
from dash import dcc, html

# ── Definición estática del grafo ─────────────────────────────────────────────

_NODES = [
    {
        "data": {"id": "trigger", "label": "Trigger", "sub": "sync_noche"},
        "position": {"x": 300, "y": 40},
        "classes": "implementado",
    },
    {
        "data": {"id": "quality-gate", "label": "Quality Gate\nAgente 1", "sub": "Quality Gate"},
        "position": {"x": 300, "y": 155},
        "classes": "implementado",
    },
    {
        "data": {
            "id": "feature-router",
            "label": "Feature Router\nAgente 2",
            "sub": "Feature Router",
        },
        "position": {"x": 300, "y": 270},
        "classes": "implementado",
    },
    {
        "data": {"id": "context-scout", "label": "Context Scout\nAgente 3", "sub": "Context Scout"},
        "position": {"x": 300, "y": 385},
        "classes": "implementado",
    },
    {
        "data": {"id": "feature-eval", "label": "Feature Eval\nAgente 4", "sub": "Feature Eval"},
        "position": {"x": 300, "y": 500},
        "classes": "implementado",
    },
    {
        "data": {"id": "smoke-test", "label": "Smoke Test\nAgente 5", "sub": "Smoke Test"},
        "position": {"x": 300, "y": 615},
        "classes": "implementado",
    },
]

_EDGES = [
    {"data": {"source": "trigger", "target": "quality-gate"}, "classes": "implementado"},
    {"data": {"source": "quality-gate", "target": "feature-router"}, "classes": "implementado"},
    {"data": {"source": "feature-router", "target": "context-scout"}, "classes": "implementado"},
    {"data": {"source": "context-scout", "target": "feature-eval"}, "classes": "implementado"},
    {"data": {"source": "feature-eval", "target": "smoke-test"}, "classes": "implementado"},
]

_STYLESHEET = [
    {
        "selector": "node",
        "style": {
            "label": "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "text-wrap": "wrap",
            "text-max-width": "120px",
            "font-size": "10px",
            "font-weight": "bold",
            "width": "140px",
            "height": "58px",
            "shape": "round-rectangle",
            "background-color": "#ffffff",
            "border-width": "2px",
            "border-color": "#dee2e6",
            "color": "#6c757d",
            "padding": "6px",
        },
    },
    {
        "selector": ".implementado",
        "style": {
            "background-color": "#eef4ff",
            "border-color": "#0052CC",
            "color": "#0052CC",
        },
    },
    {
        "selector": ".pendiente",
        "style": {
            "background-color": "#f8f9fa",
            "border-color": "#ced4da",
            "border-style": "dashed",
            "color": "#adb5bd",
        },
    },
    {
        "selector": ".estado-ok",
        "style": {
            "background-color": "#f0fff4",
            "border-color": "#28A745",
            "border-style": "solid",
            "color": "#28A745",
        },
    },
    {
        "selector": ".estado-fail",
        "style": {
            "background-color": "#fff5f5",
            "border-color": "#DC3545",
            "border-style": "solid",
            "color": "#DC3545",
        },
    },
    {
        "selector": ".estado-running",
        "style": {
            "background-color": "#fff8e1",
            "border-color": "#fd7e14",
            "border-style": "solid",
            "color": "#fd7e14",
        },
    },
    {
        "selector": ":selected",
        "style": {"border-width": "3px", "overlay-opacity": 0.1},
    },
    {
        "selector": "edge",
        "style": {
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "target-arrow-color": "#ced4da",
            "line-color": "#ced4da",
            "width": 1.5,
            "arrow-scale": 1.1,
        },
    },
    {
        "selector": "edge.implementado",
        "style": {
            "line-color": "#0052CC",
            "target-arrow-color": "#0052CC",
            "opacity": 0.5,
        },
    },
]

# ── Descripciones por nodo (panel de detalle) ─────────────────────────────────

NODE_INFO = {
    "trigger": {
        "titulo": "Trigger",
        "archivo": "src/data_ingestion/actualizar_arbol_ubicaciones.py",
        "desc": html.Div(
            [
                html.P(
                    "Detecta ubicaciones nuevas en el árbol Aitanna y dispara el pipeline de onboarding.",
                    className="small text-muted mb-2",
                ),
                html.Ul(
                    [
                        html.Li(
                            "Se ejecuta en la Fase 0 de sync_noche.py (02:00 diario)",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Compara UUIDs entrantes con dim_ubicaciones y captura los nuevos",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Lanza onboard_nuevas_ubicaciones() como subflow Prefect por cada UUID nuevo",
                            className="small text-muted",
                        ),
                    ],
                    className="ps-3 mb-0",
                ),
            ]
        ),
        "pendiente": False,
    },
    "quality-gate": {
        "titulo": "Agente 1 — Quality Gate",
        "archivo": "src/onboarding/quality_gate.py",
        "desc": html.Div(
            [
                html.P(
                    [
                        html.Span("Único agente bloqueante. ", className="fw-semibold text-danger"),
                        "Si falla, el pipeline se detiene para esa ubicación.",
                    ],
                    className="small mb-2",
                ),
                html.Ul(
                    [
                        html.Li(
                            "Datos mínimos: pais_codigo en lista de soporte y dirección presente",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Geocodificación: si lat/lon son NULL → consulta Nominatim y escribe las coordenadas en DB",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Bounding box: coordenadas fuera del bbox del país se anulan (protege contra errores de la API)",
                            className="small text-muted",
                        ),
                    ],
                    className="ps-3 mb-2",
                ),
                html.P(
                    "Países soportados: ES · MX · US · FR · DE · GB · IT · PT",
                    className="small text-muted fst-italic mb-0",
                ),
            ]
        ),
        "pendiente": False,
    },
    "feature-router": {
        "titulo": "Agente 2 — Feature Router",
        "archivo": "src/onboarding/feature_router.py",
        "desc": html.Div(
            [
                html.P(
                    [
                        html.Span("Nunca bloquea el pipeline. ", className="fw-semibold"),
                        "Decide qué fuentes de enriquecimiento aplican a esta ubicación.",
                    ],
                    className="small text-muted mb-2",
                ),
                html.Ul(
                    [
                        html.Li(
                            "Por país: festivos (12 países) · Ticketmaster (ES/MX/US/FR/DE/GB) · agenda_es (solo ES)",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Por ciudad: cruceros activado únicamente en Málaga",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Por infraestructura: weather y Esri requieren lat/lon; Esri además ESRI_KEY",
                            className="small text-muted",
                        ),
                        html.Li(
                            "thesportsdb: activo para todas las ubicaciones sin excepción",
                            className="small text-muted",
                        ),
                    ],
                    className="ps-3 mb-0",
                ),
            ]
        ),
        "pendiente": False,
    },
    "context-scout": {
        "titulo": "Agente 3 — Context Scout",
        "archivo": "src/onboarding/context_scout.py",
        "desc": html.Div(
            [
                html.P(
                    "Usa Claude (claude-sonnet-4-6) para evaluar un catálogo curado de fuentes abiertas "
                    "y seleccionar las aplicables a la isócrona de la ubicación.",
                    className="small text-muted mb-2",
                ),
                html.Ul(
                    [
                        html.Li(
                            "Catálogo incluye: INE, SEPE, INEGI, ONS, Destatis, INSEE y otras fuentes por país",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Criterios de selección: granularidad ≤ provincial · cobertura ≥ 2024 · "
                            "acceso programático · sin redundancia con fuentes ya activas",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Registra en feature_registry (status=incompleto) y feature_flags (status=contexto)",
                            className="small text-muted",
                        ),
                        html.Li(
                            "El timer mensual rellena los datos cuando el ingestor correspondiente esté implementado",
                            className="small text-muted",
                        ),
                    ],
                    className="ps-3 mb-0",
                ),
            ]
        ),
        "pendiente": False,
    },
    "feature-eval": {
        "titulo": "Agente 4 — Feature Evaluator",
        "archivo": "src/onboarding/feature_eval.py",
        "desc": html.Div(
            [
                html.P(
                    "Walk-forward WMAPE automático sobre features con cobertura disponible "
                    "y sin decisión previa para esta ubicación.",
                    className="small text-muted mb-2",
                ),
                html.Ul(
                    [
                        html.Li(
                            "Solo evalúa features con status='con_cobertura' que aún no tienen flag",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Parámetros: horizonte 21 días · 3 splits de validación cruzada",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Umbral: mejora media ≥ 0.5pp en WMAPE → status='active'; por debajo → 'inactive'",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Si fact_visitas tiene < 50 días, la evaluación se aplaza sin bloquear el pipeline",
                            className="small text-muted",
                        ),
                    ],
                    className="ps-3 mb-0",
                ),
            ]
        ),
        "pendiente": False,
    },
    "smoke-test": {
        "titulo": "Agente 5 — Smoke Test",
        "archivo": "src/onboarding/smoke_test.py",
        "desc": html.Div(
            [
                html.P(
                    [
                        html.Span("Solo lectura — no bloquea. ", className="fw-semibold"),
                        "Diagnóstico final antes de declarar la ubicación operativa.",
                    ],
                    className="small text-muted mb-2",
                ),
                html.Ol(
                    [
                        html.Li(
                            "Ubicación: activa=TRUE y lat/lon presentes en dim_ubicaciones",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Visitas: ≥ 30 días en fact_visitas (historial mínimo para el modelo)",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Cobertura: cada feature con status='active' tiene datos en store_features_ext",
                            className="small text-muted",
                        ),
                        html.Li(
                            "Zonas: al menos una zona visible (hidden=FALSE) en dim_zonas",
                            className="small text-muted",
                        ),
                    ],
                    className="ps-3 mb-0",
                ),
            ]
        ),
        "pendiente": False,
    },
}


def _default_detail():
    return html.Div(
        [
            html.P(
                "Haz clic en un nodo para ver los detalles.",
                className="text-muted small fst-italic mt-3",
            )
        ]
    )


def build_tab_pipeline():
    return dcc.Tab(
        label="Pipeline",
        value="tab-pipeline",
        className="fw-bold",
        children=[
            html.Div(
                [
                    dcc.Interval(id="interval-pipeline", interval=30_000, n_intervals=0),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Div(
                                        [
                                            html.H5(
                                                [
                                                    html.I(
                                                        className="fas fa-project-diagram me-2 text-primary"
                                                    ),
                                                    "Pipeline de onboarding",
                                                ],
                                                className="fw-bold text-dark mb-0",
                                            ),
                                            html.P(
                                                "Agentes · estado basado en últimas ejecuciones Prefect",
                                                className="text-muted small mb-3",
                                            ),
                                        ]
                                    ),
                                    cyto.Cytoscape(
                                        id="cytoscape-pipeline",
                                        layout={"name": "preset"},
                                        style={
                                            "width": "100%",
                                            "height": "700px",
                                            "border": "1px solid #dee2e6",
                                            "borderRadius": "12px",
                                            "background": "#fafbfc",
                                        },
                                        elements=_NODES + _EDGES,
                                        stylesheet=_STYLESHEET,
                                        userZoomingEnabled=True,
                                        userPanningEnabled=True,
                                        minZoom=0.5,
                                        maxZoom=2.0,
                                    ),
                                    html.Div(
                                        [
                                            html.Span(
                                                className="badge me-2",
                                                style={
                                                    "background": "#eef4ff",
                                                    "color": "#0052CC",
                                                    "border": "2px solid #0052CC",
                                                },
                                                children="Implementado",
                                            ),
                                            html.Span(
                                                className="badge me-2",
                                                style={
                                                    "background": "#f0fff4",
                                                    "color": "#28A745",
                                                    "border": "2px solid #28A745",
                                                },
                                                children="OK",
                                            ),
                                            html.Span(
                                                className="badge me-2",
                                                style={
                                                    "background": "#fff5f5",
                                                    "color": "#DC3545",
                                                    "border": "2px solid #DC3545",
                                                },
                                                children="Fallido",
                                            ),
                                            html.Span(
                                                className="badge me-2",
                                                style={
                                                    "background": "#f8f9fa",
                                                    "color": "#adb5bd",
                                                    "border": "2px dashed #ced4da",
                                                },
                                                children="Pendiente",
                                            ),
                                        ],
                                        className="mt-2",
                                    ),
                                ],
                                xs=12,
                                lg=8,
                                className="mb-4 mb-lg-0",
                            ),
                            dbc.Col(
                                [
                                    html.Div(id="pipeline-node-detail", children=_default_detail()),
                                ],
                                xs=12,
                                lg=4,
                            ),
                        ]
                    ),
                ],
                className="p-3",
            )
        ],
    )
