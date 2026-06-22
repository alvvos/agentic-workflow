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
        "data": {"id": "quality-gate", "label": "Agente 1", "sub": "Quality Gate"},
        "position": {"x": 300, "y": 140},
        "classes": "implementado",
    },
    {
        "data": {"id": "feature-router", "label": "Agente 2", "sub": "Feature Router"},
        "position": {"x": 300, "y": 240},
        "classes": "implementado",
    },
    {
        "data": {"id": "context-scout", "label": "Agente 3", "sub": "Context Scout"},
        "position": {"x": 300, "y": 340},
        "classes": "implementado",
    },
    {
        "data": {"id": "feature-eval", "label": "Agente 4", "sub": "Feature Eval"},
        "position": {"x": 300, "y": 440},
        "classes": "implementado",
    },
    {
        "data": {"id": "smoke-test", "label": "Agente 5", "sub": "Smoke Test"},
        "position": {"x": 300, "y": 540},
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
            "text-valign": "top",
            "text-halign": "center",
            "font-size": "10px",
            "font-weight": "bold",
            "width": "80px",
            "height": "44px",
            "shape": "round-rectangle",
            "background-color": "#ffffff",
            "border-width": "2px",
            "border-color": "#dee2e6",
            "color": "#6c757d",
            "padding": "6px",
        },
    },
    {
        "selector": "node[sub]",
        "style": {
            "label": "data(label)",
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
        "desc": "Captura los location_uuids existentes antes del upsert y los compara con los entrantes. Cualquier UUID nuevo dispara el pipeline de onboarding.",
        "pendiente": False,
    },
    "quality-gate": {
        "titulo": "Agente 1 — Quality Gate",
        "archivo": "src/onboarding/quality_gate.py",
        "desc": "Valida pais_codigo, dirección y coordenadas. Geocodifica con Nominatim si faltan lat/lon. Anula coordenadas fuera del bounding box del país.",
        "pendiente": False,
    },
    "feature-router": {
        "titulo": "Agente 2 — Feature Router",
        "archivo": "src/onboarding/feature_router.py",
        "desc": "Decide qué fuentes de datos aplican según país, ciudad y tenant: weather (lat/lon), festivos (por país), Ticketmaster (ES/MX/US/FR/DE/GB), agenda_es (ES), cruceros (Málaga), Esri (ESRI_KEY + coords).",
        "pendiente": False,
    },
    "context-scout": {
        "titulo": "Agente 3 — Context Scout",
        "archivo": "src/onboarding/context_scout.py",
        "desc": "Evalúa un catálogo curado de fuentes de datos abiertas (INE, SEPE, INEGI, ONS…) usando Claude para decidir cuáles aplican a la isócrona de la ubicación. Registra las seleccionadas en feature_registry (status='incompleto') y feature_flags (status='contexto'). El timer mensual las rellena automáticamente cuando el ingestor esté disponible.",
        "pendiente": False,
    },
    "feature-eval": {
        "titulo": "Agente 4 — Feature Evaluator",
        "archivo": "src/onboarding/feature_eval.py",
        "desc": "Walk-forward WMAPE automático (horizonte 21d, 3 splits) sobre features con status='con_cobertura' que aún no tienen decisión para esta ubicación. Auto-activa (status='active') las que mejoran WMAPE en ≥ 0.5 pp. Si la ubicación tiene menos de 50 días de historial, aplaza la evaluación sin bloquear el pipeline.",
        "pendiente": False,
    },
    "smoke-test": {
        "titulo": "Agente 5 — Smoke Test",
        "archivo": "src/onboarding/smoke_test.py",
        "desc": "4 checks de solo lectura antes de declarar la ubicación operativa: (1) activa=TRUE y lat/lon presentes, (2) ≥30 días en fact_visitas, (3) features activas con cobertura en store_features_ext, (4) al menos una zona visible en dim_zonas.",
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
                                            "height": "620px",
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
