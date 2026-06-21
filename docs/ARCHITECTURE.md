# ARCHITECTURE — Agentic Workflow

**Stack:** Python 3.12 · Dash/Plotly · PostgreSQL 16 (Docker) · XGBoost · gunicorn  
**Última revisión:** 2026-06-21 · Versión en producción: v2.2.18

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

```
Fase A: cruceros.py  → store_features_ext (n_pasajeros_crucero_dia, Málaga)
Fase B: geo.py       → listar_estado (Esri — pendiente de contrato)
```

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
feature_lab.ipynb  →  walk-forward WMAPE evaluation
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
- `contexto` → se muestra en el panel (ej. ev_rank), nunca al modelo
- `inactive` → oculto

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

### Geo (Esri)
- `src/data_ingestion/esri_client.py` — `fetch_enrich()` real + mock (si no hay `ESRI_KEY`)
- `src/data_processing/geo_enrichment.py` — `get_geo_vals()`, `enriquecer_con_geo()`, `GEO_FEATURE_COLS` (47 features)
- `src/reporting/geo_panel.py` — Panel visual geo (tarjetas AIS + mapa)
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
| `scripts/sync_mensual.py` | Orquestador mensual (cruceros + estado geo) |
| `scripts/enriquecer_esri.py` | Enriquecimiento one-shot con Esri |
| `scripts/mock_showroom_features.py` | Genera datos mock para demo/showroom |
| `scripts/seed_crucero_llamadas.py` | Seed de escalas de crucero históricas |
| `src/lab/ingest_features.py` | Ingesta ICM (INE) + calendario escolar |
| `src/lab/eval_features.py` | Evaluación WMAPE walk-forward de features |
| `src.data_ingestion.actualizar_arbol_ubicaciones` | Sync árbol Aitanna → PostgreSQL |
