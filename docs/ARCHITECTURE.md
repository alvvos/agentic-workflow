# ARCHITECTURE — Agentic Workflow

**Stack:** Python 3.12 · Dash/Plotly · PostgreSQL 16 (Docker) · XGBoost · Prefect 3 · gunicorn
**Última revisión:** 2026-06-30 · Versión en producción: v2.2.47

---

## Visión general

Panel de analítica retail multi-tenant en tiempo real. Ingiere datos de flujo de visitantes desde la API de Aitanna, enriquece con señales externas (clima, eventos, cruceros, calendario comercial), entrena modelos XGBoost por zona y expone predicciones y KPIs a través de un dashboard Dash con chatbot Claude integrado.

**Tenants actuales:**
- Miniso ES — 4 tiendas (Madrid Gran Vía, Málaga Muelle 1, Valencia Bonaire, Tenerife CC Nivaria⚠)
- Barceló Hotels — 1 propiedad (Barceló Corales Villas)
- Sam's Club MX, Kiosko MX, The Phone House ES — sin ubicaciones activas aún

---

## Stack de producción

| Componente | Detalle |
|---|---|
| Servidor | Google Cloud VM · IP `34.175.22.17` · puertos 80/443 |
| Process manager | systemd · servicio `agentic-workflow` |
| App server | gunicorn 1 worker (prod) · `127.0.0.1:8000` · timeout 300s |
| Base de datos | PostgreSQL 16 en Docker Compose · puerto 5433 (local) |
| Deploy | `~/deploy.sh <versión>` vía SSH · git tags semver |
| Timers nocturnos | `agentic-sync-noche` (02:00 diario) · `agentic-sync-mensual` (día 1, 03:00) |

---

## Árbol de entrada — `app.py`

```
app.py
├── src/core/config.py          — instancia Dash, MODO_DESARROLLO, .env
├── src/core/auth.py            — /login, /logout, before_request (cookie session)
├── src/core/pdf_endpoint.py    — /api/html-to-pdf (Playwright headless)
├── src/layout/main_layout.py   — serve_layout() dinámica por request
│   ├── src/layout/sidebar.py   — dropdowns de org/ubicación
│   └── src/layout/tabs/
│       ├── tab_pm.py           — Panel PM (tab principal)
│       ├── tab_bi.py           — BI comparativo (WoW/MoM/YoY)
│       ├── tab_ml.py           — Forecasting XGBoost (admin)
│       ├── tab_prediccion_cliente.py — Predicción (vista cliente)
│       ├── tab_reportes.py     — Exportación Excel/PDF
│       └── tab_admin.py        — Panel administración
└── src/callbacks/
    ├── filtros.py              — dropdowns, toggle sidebar, ventana temporal
    ├── sync.py                 — sincronización background (botón manual)
    ├── analytics.py            — master_reactive_analytics() — callback principal
    ├── exports.py              — Excel/PDF download
    ├── resumen_exportacion.py  — resumen exportable
    ├── chat_callbacks.py       — callbacks del asistente IA
    ├── admin.py                — gestión de usuarios/org (admin only)
    └── estado_callbacks.py     — health/status indicators
```

**`serve_layout()`** se llama en cada request (no en startup) — los dropdowns de org/ubicación se pueblan frescos según el usuario autenticado.

**`master_reactive_analytics()`** es el callback maestro: filtra globales + ventana temporal + modo comparación → genera contenido BI, grid de auditoría y resumen ejecutivo.

---

## Flujo de datos completo

```
Aitanna API
    │  (sincronizador.py — diario @ 02:00 vía sync_noche.py)
    ▼
fact_visitas (PostgreSQL)
    │
    ▼
queries.py → get_df_enriquecido(location_uuid, session_id)
    ├── JOIN clima         (store_features_ext ← open_meteo.py)
    ├── JOIN festivos      (pais_codigo de dim_organizaciones)
    ├── JOIN supercalendario (config_calendario de dim_organizaciones)
    └── JOIN features activas (feature_flags WHERE status='active')
    ▼
DataFrame enriquecido (en memoria, por request)
    ├── health_check.py → Panel PM, sección Eventos, sección Cruceros
    ├── data_radar.py   → Calendario grid con colores de anomalía
    └── ml_predictivo.py → ejecutar_auditoria_predictiva()
            ├── JOIN geo (store_geo_snapshots — temporal join por fecha)
            ├── Train XGBoost (85/15, early stopping 20 rounds)
            ├── Cache model_registry (invalida si features cambió o >7 días)
            └── Predicciones N días + métricas WMAPE/MAE/accuracy
```

---

## Flujo de ingesta nocturna

### `scripts/sync_noche.py` — ejecución diaria @ 02:00

```
Fase 0: actualizar_arbol_ubicaciones.py  → dim_organizaciones, dim_ubicaciones, dim_zonas
Fase A: sincronizador.py                 → fact_visitas (incremental, Aitanna API)
Fase B: prefetch/run_all.py              → store_features_ext, store_calendario_org
    ├── weather.py      — Open-Meteo (clima histórico + forecast)
    ├── ticketmaster.py — eventos TM → store_calendario_org (evento_key tm_*)
    ├── open_holidays.py — festivos públicos → store_calendario_org
    ├── agenda_es.py    — agenda cultural → store_calendario_org
    └── thesportsdb.py  — eventos deportivos → store_calendario_org
    (cruceros: excluido de sync_noche — mensual)
```

### `scripts/sync_mensual.py` — ejecución día 1 @ 03:00

Loop data-driven: lee `feature_flags JOIN feature_registry`, agrupa por `source` y llama a cada ingestor UNA vez con el lote de jobs asignados (`SyncJob(feature_key, location_uuid, periodicidad)`). Añadir una fuente nueva = 1 import + 1 entrada en `_build_ingestores()`. Geo/Esri se audita al final por separado (escribe en `store_geo_snapshots`, no en `store_features_ext`).

Los parámetros específicos por fuente/ubicación (e.g., `port_authority` para Puertos del Estado, `iata` para AENA) se leen de `location_source_config` (PK: `location_uuid, source`; columna `params JSONB`). Ver `docs/source_params_contract.md`.

```
_cargar_jobs("mensual")  → {source: [SyncJob, ...]}
_build_ingestores()       → {source: fn(jobs, fecha) → int}
loop source in jobs:
    if source in ingestores → ingestor(jobs, fecha)  # n filas escritas
    else → log "sin ingestor — N jobs pendientes"
Geo/Esri: listar_estado() (audit only)
```

Fuentes mensuales actualmente registradas: `puertos_estado` (n_pasajeros_crucero_oficial via Puertos del Estado XLSX oficial), `metro_madrid` (validaciones por estación, Excel Metro Madrid — feature_key: `afluencia_metro_{slug}`).

**Ingestores mensual pendientes de conectar a `sync_mensual.py`:** `aena`, `cercanias_renfe`, `metro_barcelona`, `metro_bilbao`, `metro_sevilla`, `metro_valencia`, `ine_eoh`. Los stubs están en `src/data_ingestion/mensual/` con la misma interfaz `sync(jobs, fecha)`.

---

## Pipeline de onboarding de ubicaciones

Cada UUID nuevo detectado por `actualizar_arbol_ubicaciones.py` lanza un subflow Prefect visible en la UI.

```
sync_noche.py → Fase 0: actualizar_arbol_ubicaciones
                    │ nuevos UUIDs detectados
                    ▼
            onboard_nuevas_ubicaciones (flow Prefect)
                    │
                    ▼ por cada UUID
            onboarding_ubicacion (subflow)
                ├── Agente 1: quality-gate    (validar lat/lon, geocodificar, bbox)
                ├── Agente 2: feature-router  (qué fuentes aplican por país/ciudad)
                ├── Agente 3: context-scout   (Claude descubre fuentes abiertas → feature_registry)
                ├── Agente 4: feature-eval    (walk-forward WMAPE → auto-activa features)
                └── Agente 5: smoke-test      (4 checks lectura: activa, visitas, cobertura, zonas)
```

**Archivos:** `src/onboarding/pipeline.py` (orquestador Prefect), `src/onboarding/quality_gate.py`, `feature_router.py`, `context_scout.py`, `feature_eval.py`, `smoke_test.py`, `_eval_core.py` (núcleo walk-forward, importable en producción sin depender de `src/lab/`).

**Context Scout (Agente 3):** evalúa un catálogo curado usando escala de directitud A→D (A=cuenta personas reales, B=actividad observable, C=índice sectorial, D=macro). No incluye señales D si ya hay una A o B. Prioriza AENA (pasajeros aeropuerto) e INE pernoctaciones hoteleras sobre ICM y SEPE. Devuelve JSON; incluye strip defensivo de markdown code fences antes de `json.loads()`.

**Despliegue del servidor Prefect:** `scripts/serve_flows.py` — sirve `onboard_nuevas_ubicaciones` como deployment en `http://127.0.0.1:4200`. Gestionado por systemd `prefect-flows.service`.

---

## Feature pipeline

```
Fuente externa
    │
    ▼
store_features_ext / store_calendario_org
    │
    ▼
feature_registry (status: incompleto → con_cobertura)
    │   _promote_if_covered() al final de cada ingesta
    ▼
┌──────────────────────────────────────────┐
│ Ruta A (manual): feature_lab.ipynb       │
│ Ruta B (auto):   Agente 4 feature-eval   │
│   walk-forward WMAPE, umbral -0.5pp      │
└──────────────────────────────────────────┘
    │
    ▼
feature_flags (status: inactive → active / contexto)
    │   decisión por ubicación
    ▼
queries.get_active_ext_features(location_uuid, fecha_min, fecha_max)
    │   fillna(0.0), sin ffill
    ▼
ml_predictivo.py → vector de training XGBoost
```

**Estados `feature_flags.status`:**
- `active` → entra al modelo ML
- `contexto` → visible en panel "Señal del contexto exterior", **no** entra al modelo. `_render_senal_contexto_modal()` usa `IN ('active', 'contexto')` para mostrarlas. Caso de uso: datos de metro.
- `inactive` → evaluada, no mejora el modelo

---

## Componentes secundarios

### Chatbot (`src/chatbot/`)
- `client.py` — Claude API (streaming)
- `tools.py` — herramientas: `get_forecast`, `get_kpis`, `get_events`, `get_ev_ranks`, etc. (14 tools)
- `cache.py` — caché de respuestas en `cache_responses`
- `history.py` — conversaciones en `chat_conversaciones` + `chat_mensajes`
- `mcp_server.py` — servidor MCP (exposición de tools a Claude)
- `mentions.py` — detección de @ubicación en mensajes
- `streaming.py` — SSE para respuestas en tiempo real

### Shared modules (`src/core/`)
- `src/core/theme.py` — constantes de color (`C_PRIMARY`, `C_SUCCESS`, `C_DANGER`, `C_AMBER`, `C_DARK`, `C_MUTED`, `C_GRID`), `CFG_GRAPH`, `PALETA_PM`. Elimina duplicación de constantes en 5+ ficheros.
- `src/core/utils.py` — arrays de calendario ES (`MESES_ES`, `MESES_ES_FULL`, `DIAS_SEMANA_ES`, `DIAS_CORTO`). Fuente única compartida entre reporting, callbacks y geo_panel.

### Arquitectura DB-driven de render (`health_check.py`, `geo_panel.py`)

El capa de render es completamente data-driven desde v2.2.47. **No hay dicts hardcodeados en Python**; toda decisión de label/color/icono/routing viene de la DB:

- `_load_feature_meta(conn, location_uuid)` — query única a `feature_registry` devuelve `{feature_key: {label, sublabel, color, icon_cls, agg_fn, display_mode, notas}}`. El campo `display_mode` controla el componente de render: `'yoy'` (gráfico tendencia) · `'events_count'` (contador mensual) · `'cruceros'` (tabla escalas) · `'calendario'` (grid calendario) · `'hidden'`.
- `_load_zone_meta(conn)` — query a `zone_type_registry` para estilos por tipo de zona.
- `_load_narrative_meta(conn)` — query a `narrative_category_registry` + `alert_level_registry` para categorías y niveles de la narrativa ejecutiva.
- `_load_norm_tipo(conn)` — query a `feature_registry WHERE canonical_type IS NOT NULL` reemplaza `_NORM_TIPO` Python dict (ej. `tm_concierto → concierto`).
- `_load_geo_meta(conn)` en `geo_panel.py` — query a `poi_category_registry` para estilos de POIs.

**Contrato de escalabilidad:** añadir una señal nueva = `INSERT INTO feature_registry` + `INSERT INTO feature_flags`. Cero cambios en Python.

### Geo (Esri)
- `src/data_ingestion/esri_client.py` — `fetch_enrich()` real + mock (si no hay `ESRI_KEY`)
- `src/data_processing/geo_enrichment.py` — `get_geo_vals()`, `enriquecer_con_geo()`, `GEO_FEATURE_COLS` (47 features)
- `src/reporting/geo_panel.py` — Panel visual geo (tarjetas AIS + mapa). POIs leídos de `location_pois` DB (no hardcodeados).
- `scripts/enriquecer_esri.py` — script one-shot para enriquecer ubicaciones

### Auth
- `src/core/auth.py` — cookie-based session, SHA-256 passwords
- `users.json` → se upsertea en `dim_usuarios` en cada arranque
- Roles: `admin` (acceso total) / `user` (panel cliente, sin tab ML ni admin)

### Render guard (`assets/render_guard.js`)
Overlay que espera a que todos los gráficos Plotly terminen de renderizar antes de mostrar el contenido. Usa `MutationObserver` + `plotly_afterplot`. Paneles monitorizados: `panel-ejecutivo-content`, `bi-dynamic-content`, `pred-publica-content`. Fallback: 800ms sin gráficos o 15s hard ceiling.

---

## Interfaces clave (no inventar)

```python
# DB
from src.db.store import get_conn
conn = get_conn()

# Datos enriquecidos para forecasting
from src.db.queries import get_df_enriquecido
df = get_df_enriquecido(location_uuid, session_id='')

# Forecasting
from src.services.ml_predictivo import ejecutar_auditoria_predictiva
res = ejecutar_auditoria_predictiva(df, loc_uuid, zone_uuid, fecha_hoy, horizonte_dias)
# res = {'status': 'success', 'grafica': {...}, 'metricas': {...}}

# Panel ejecutivo
from src.reporting.health_check import generar_mensajes_salud
salud = generar_mensajes_salud(df, loc_uuid, dias_ventana=7)

# Árbol de ubicaciones
from src.db.queries import get_zones_for_loc, get_active_locations
zonas = get_zones_for_loc(location_uuid)         # list[dict]
locs  = get_active_locations()                   # list[dict], filtra lat/lon IS NOT NULL

# Ingesta geo Esri
from src.data_ingestion.ingesta_geo import ingestar_snapshot_esri
ingestar_snapshot_esri(location_uuid, valores_dict, fecha_entrega='YYYY-MM-DD')
```

---

## Variables de entorno (`.env`)

| Variable | Descripción |
|---|---|
| `AITANNA_API_KEY` | API key de Aitanna |
| `ESRI_KEY` | API key ArcGIS Location Platform (si ausente, `esri_client.py` usa mock) |
| `ANTHROPIC_API_KEY` | Clave Claude API (chatbot) |
| `DB_HOST` / `DB_PORT` | PostgreSQL host/port (default: `localhost`/`5432`) |
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | Credenciales PostgreSQL |
| `DB_POOL_MAX` | Tamaño máximo del pool (default: 10) |
| `MODO_DESARROLLO` | `True` → usa `session_id='local_dev'` fijo |

---

## Bugs conocidos / trampas

1. **`src/models/anomalys.py`** — importado en `analytics.py` pero está WIP. Si el callback BI llega al panel de anomalías, RuntimeError. No usar esa ruta.

2. **`constructor_master.py`** — lee `loc.get('latitude', ...)` pero el JSON/DB usa `lat`. Bug pre-existente. Corregir al tocar ese archivo.

3. **NetworkServiceArea (Esri)** — devuelve "Internal error". Usar siempre `RingBuffer` (400/800/1200m).

4. **`empleados_por_hogar` (TOTOCCME)** — valores anómalos (19/19/42/1). No usar en modelo hasta verificar con doc AIS.

5. **Tenerife CC Nivaria** — sin coordenadas en `dim_ubicaciones`. Excluida de todo prefetch. Geocodificar con `python -m src.data_ingestion.actualizar_arbol_ubicaciones geo`.

6. **Módulo `src.data_processing.fuentes_eventos.*`** — duplica funcionalidad de `src.data_ingestion.prefetch.*`. La fuente canónica para prefetch son los scripts en `prefetch/`.

---

## Scripts y herramientas

| Script | Propósito |
|---|---|
| `scripts/sync_noche.py` | Orquestador nocturno (Fase 0 árbol + Fase A Aitanna + Fase B contexto) |
| `scripts/sync_mensual.py` | Loop data-driven mensual — un ingestor por source (cruceros + otros cuando estén listos) |
| `scripts/serve_flows.py` | Sirve flows Prefect como deployments (onboarding-lote → UI Prefect) |
| `scripts/enriquecer_esri.py` | Enriquecimiento Esri one-shot |
| `scripts/mock_showroom_features.py` | Genera datos mock para demo/showroom |
| `scripts/seed_crucero_llamadas.py` | Seed de escalas de crucero históricas |
| `src/lab/ingest_features.py` | Ingesta ICM (INE) + calendario escolar |
| `src/lab/eval_features.py` | Evaluación WMAPE walk-forward de features (también usada por Agente 4) |
| `src.data_ingestion.actualizar_arbol_ubicaciones` | Sync árbol Aitanna → PostgreSQL + trigger onboarding |
