# FILE_TREE — Agentic Workflow

Árbol anotado del repositorio. Solo archivos relevantes (excluye `__pycache__`, `venv`, `.git`).  
**Última revisión:** 2026-06-21

---

```
agentic-workflow/
│
├── app.py                          Punto de entrada. Registra callbacks, monta layout.
├── users.json                      Usuarios del panel (se upsertea en dim_usuarios al arrancar).
├── requirements.txt
├── pytest.ini
├── CLAUDE.md                       Instrucciones para Claude Code.
│
├── assets/
│   ├── render_guard.js             MutationObserver + plotly_afterplot overlay (anti-flash loader).
│   ├── custom.css                  Estilos globales del panel.
│   └── impresion.css               CSS de impresión (PDF export).
│
├── docs/                           Documentación técnica del proyecto.
│   ├── ARCHITECTURE.md             ← este tipo de doc, arquitectura completa
│   ├── DB_SCHEMA.md                ← schema PostgreSQL completo
│   ├── FILE_TREE.md                ← este archivo
│   ├── feature_pipeline.md         Ciclo de vida de features: ingesta → evaluación → activación
│   ├── context.md                  Handoff de sesión 2026-05-27 (estado Esri, geo panel, chatbot)
│   ├── arquitectura_datos.md       Contexto histórico del paso de CSV/DuckDB a PostgreSQL
│   ├── handoff_supercalendario.md  Fuentes de datos externas planificadas (PredictHQ, INE, DGT)
│   ├── HANDOFF_esri_peticiones_y_piloto_miniso.md  Decisiones del piloto Esri, anatomía peticiones
│   └── servidor.txt                IP/clave SSH del servidor de producción
│
├── scripts/                        Orquestadores y scripts one-shot.
│   ├── sync_noche.py               Timer nocturno: Fase 0 árbol + Fase A Aitanna + Fase B contexto
│   ├── sync_mensual.py             Timer mensual: cruceros + estado geo Esri
│   ├── enriquecer_esri.py          Enriquecimiento Esri one-shot (4 ubicaciones prod)
│   ├── mock_showroom_features.py   Datos mock para demo/showroom
│   ├── seed_crucero_llamadas.py    Seed histórico de escalas de crucero
│   └── launch.sh                   Dev server launcher
│
├── tests/
│   ├── test_arbol_ubicaciones.py
│   ├── test_chatbot_tools.py
│   ├── test_date_filter.py
│   ├── test_sync_guard.py
│   └── test_sync_staleness.py
│
└── src/
    │
    ├── core/
    │   ├── config.py               Instancia Dash (tema LUX), MODO_DESARROLLO, carga .env
    │   ├── auth.py                 Autenticación cookie-based, /login, /logout, before_request
    │   ├── data_master.py          mapa_tiendas: {location_uuid: nombre} — caché global
    │   ├── pdf_endpoint.py         /api/html-to-pdf via Playwright headless
    │   └── utils.py                Helpers compartidos
    │
    ├── db/
    │   ├── store.py                Pool psycopg v3, DDL completo (_apply_ddl), PgConn wrapper
    │   ├── queries.py              get_df_enriquecido(), get_zones_for_loc(), get_active_locations()
    │   │                           get_active_ext_features(), caché de clima
    │   └── seed.py                 Migración one-off JSON/CSV → PostgreSQL + seed_feature_flags()
    │
    ├── layout/
    │   ├── main_layout.py          serve_layout() dinámica — se llama en cada request
    │   ├── sidebar.py              Sidebar: dropdowns org/ubicación, toggle, filtros globales
    │   └── tabs/
    │       ├── tab_pm.py           Panel PM (Performance Monitoring) — tab principal
    │       ├── tab_bi.py           BI comparativo WoW/MoM/YoY
    │       ├── tab_ml.py           Forecasting XGBoost — solo admin
    │       ├── tab_prediccion_cliente.py  Predicción 7 días — vista cliente
    │       ├── tab_reportes.py     Exportación Excel + PDF
    │       └── tab_admin.py        Gestión usuarios/org
    │
    ├── callbacks/
    │   ├── analytics.py            master_reactive_analytics() — callback maestro
    │   ├── filtros.py              Dropdowns, toggle sidebar, ventana temporal
    │   ├── sync.py                 Sincronización background (botón manual)
    │   ├── exports.py              Excel/PDF download
    │   ├── resumen_exportacion.py  Resumen exportable multi-ubicación
    │   ├── chat_callbacks.py       Callbacks del asistente IA
    │   ├── admin.py                CRUD usuarios/org (admin only)
    │   └── estado_callbacks.py     Health/status indicators en el sidebar
    │
    ├── data_ingestion/
    │   ├── sincronizador.py        Aitanna API → fact_visitas (ThreadPoolExecutor 5 workers)
    │   ├── actualizar_arbol_ubicaciones.py  Sync árbol Aitanna → dim_* + geocodificación Nominatim
    │   ├── esri_client.py          fetch_enrich() Esri GeoEnrichment real + mock (sin ESRI_KEY)
    │   ├── ingesta_geo.py          ingestar_snapshot_esri(), listar_estado_geo()
    │   └── prefetch/               Scripts de prefetch de señales externas
    │       ├── _common.py          get_active_locations(), helpers compartidos
    │       ├── run_all.py          Orquestador: lanza todos los prefetch (con skip set)
    │       ├── weather.py          Open-Meteo → store_features_ext (temp_max, temp_min, llueve)
    │       ├── ticketmaster.py     Ticketmaster API → store_calendario_org (tm_concierto, etc.)
    │       ├── open_holidays.py    OpenHolidays API → store_calendario_org (festivos)
    │       ├── agenda_es.py        Agenda cultural ES → store_calendario_org
    │       ├── thesportsdb.py      TheSportsDB → store_calendario_org (eventos deportivos)
    │       └── cruceros.py         Puerto de Málaga → store_features_ext (n_pasajeros_crucero_dia)
    │
    ├── data_processing/
    │   ├── constructor_master.py   Weather + holidays join (ojo: bug `lat` vs `latitude`)
    │   ├── supercalendario.py      9-15 features retail ES+MX: rebajas, Black Friday, etc.
    │   ├── geo_enrichment.py       get_geo_vals(), enriquecer_con_geo(), GEO_FEATURE_COLS (47 vars)
    │   ├── data_radar.py           Calendario grid con colores de anomalía
    │   ├── eventos_client.py       Wrapper para consultas de eventos desde el panel
    │   └── fuentes_eventos/        Módulos de fuentes de eventos (duplican prefetch — usar prefetch)
    │       ├── ticketmaster.py
    │       ├── open_holidays.py
    │       ├── agenda_es.py
    │       └── thesportsdb.py
    │
    ├── reporting/
    │   ├── health_check.py         Panel PM completo: narrativa, eventos, cruceros, radar
    │   │                           generar_mensajes_salud() → Dash children
    │   ├── geo_panel.py            Panel visual geo: tarjetas AIS + mapa + gráficos Esri
    │   ├── ml_dashboard.py         Dashboard de forecasting XGBoost
    │   └── generador_html.py       HTML exportable para PDF
    │
    ├── services/
    │   └── ml_predictivo.py        ejecutar_auditoria_predictiva(): features + XGBoost + métricas
    │                               Incluye temporal join geo, cache model_registry (7 días)
    │
    ├── chatbot/
    │   ├── client.py               Claude API streaming
    │   ├── tools.py                14 herramientas: get_forecast, get_kpis, get_events, get_ev_ranks…
    │   ├── cache.py                Caché de respuestas → cache_responses
    │   ├── history.py              Conversaciones → chat_conversaciones + chat_mensajes
    │   ├── mcp_server.py           Servidor MCP (exposición tools a Claude)
    │   ├── mentions.py             Detección @ubicación en mensajes
    │   ├── streaming.py            SSE para respuestas en tiempo real
    │   └── chat_panel.py           Componente UI del panel del asistente
    │
    ├── models/
    │   └── anomalys.py             ⚠ WIP — RuntimeError si se alcanza esta ruta en analytics
    │
    └── lab/                        Scripts de exploración y evaluación (NO mutan el sistema real)
        ├── academic_calendar.py    Calendario escolar ES/MX
        ├── ine_client.py           Cliente INE (ICM — Índice de Comercio al por Menor)
        ├── ingest_features.py      Ingesta ICM + calendario escolar → store_features_ext
        └── eval_features.py        Evaluación walk-forward WMAPE de features candidatas
```

---

## Archivos de datos (excluidos de git salvo excepciones)

```
src/data/
├── geo_features.json           ← EXCEPCIÓN: en git (via !geo_features.json en .gitignore)
│                               Store de snapshots Esri en JSON (legacy; canónico: store_geo_snapshots)
└── todas_las_ubicaciones.json  Árbol org/loc/zona para seed inicial (se actualiza vía actualizar_arbol)

src/models/registry/            Modelos XGBoost serializados (.ubj) — en .gitignore
data/raw/                       CSVs de sesión legacy (fallback) — en .gitignore
```
