# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Agentic Workflow** is a real-time retail analytics and forecasting dashboard built with Dash (Python). It ingests location-based visitor flow data from the Aitanna API, performs anomaly detection, generates ML forecasts, and provides interactive visualizations across WoW/MoM/YoY time-window comparisons.

Multi-tenant: data is scoped by organization → location → zone hierarchy defined in `src/data/todas_las_ubicaciones.json`.

## Running

```bash
pip install -r requirements.txt
playwright install chromium   # first time only — downloads ~150 MB Chromium headless
# Create .env with AITANNA_API_KEY=<your_key>
python app.py         # dev server at http://localhost:8052
gunicorn --workers 4 --bind 0.0.0.0:8000 app:server  # production
```

No test suite exists beyond a placeholder at `src/services/test.py`. Use `src/lab/laboratorio_ml.ipynb` for interactive ML experimentation.

## Architecture

### Data Flow

1. **Ingestion** (`src/data_ingestion/sincronizador.py`): Reads zone UUIDs from `todas_las_ubicaciones.json`, hits Aitanna API for daily visitor stats using `ThreadPoolExecutor(max_workers=5)`. Persists to `data/raw/dataset_{session_id}.csv`.

2. **Enrichment** (`src/data_processing/constructor_master.py`): Attaches Spanish holiday flags and historical weather (Open-Meteo API) per date.

3. **Feature Engineering** (`src/data_processing/feature_engineering.py`): Day-of-week, is-weekend, is-holiday, lag-1/7/14d visitor counts, 7/14d rolling averages, weather interaction flags.

4. **Reporting** — multiple output paths from the enriched dataset:
   - `src/reporting/health_check.py`: Executive multi-zone summary with period deltas
   - `src/data_processing/data_radar.py`: Calendar grid with anomaly coloring
   - `src/reporting/generador_operativo.py`: Excel export per location
   - `src/reporting/generador_pptx.py`: PowerPoint export

5. **Forecasting** (`src/services/ml_predictivo.py`): XGBoost trained on 85/15 train/val split with early stopping (20 rounds). Predicts N days forward for a selected zone.

### Callback Architecture (`app.py`)

- `serve_layout()` builds the full page dynamically (multi-tenant dropdowns are populated at request time)
- `master_reactive_analytics()` is the master callback: global filters + time window + comparison mode → BI content, audit grid, executive summary
- Session ID scopes CSV files; `MODO_DESARROLLO = True` uses `"local_dev"` instead of UUID

### Known Issue

`app.py` line 17 imports `from src.models.anomalys import generar_panel_bi_completo` but `src/models/` does not exist. This causes a runtime error if the BI panel callback is reached. The module is WIP.

## Conventions

- All date columns named `'fecha'` (Spanish); use `pd.Timestamp` for filtering
- Time offsets via `pd.Timedelta()`, not raw integers
- Imports use absolute `src.*` paths (no relative imports)
- API calls wrapped in try-except for graceful degradation; empty DataFrames checked before aggregations
- Dash Bootstrap Components with LUX theme; color constants: primary `#0052CC`, danger `#DC3545`, success `#28A745`

---

## Session Handoff — 2026-05-12

### Context

Álvaro is preparing the forecasting engine to integrate Esri geospatial data. The motivation: the current XGBoost model suffers from "spatial blindness" — it reverts to the mean and under-reacts to extreme traffic peaks caused by the external spatial context (pedestrian catchment area, competitor landscape, commercial density). A proposal was sent to Mario at Esri to evaluate endpoints, costs and licences for automating the spatial analysis.

### What was built — commit `b8e7f7d`

| File | Status | Description |
|---|---|---|
| `src/data/geo_features.json` | New | Versioned geospatial feature store. One entry per `location_uuid`, structured as a list of temporal snapshots with `valid_from` / `valid_to`. All 30 location UUIDs pre-registered with `null` values, ready to receive Esri data. |
| `src/data_processing/geo_enrichment.py` | New | Public API: `get_geo_vals(uuid, fecha)`, `get_geo_features_activos(uuid, fecha)`, `enriquecer_con_geo(df)`. File-level mtime cache. Exports `GEO_FEATURE_COLS`, `GEO_FEATURES_BACKDATABLE`, `GEO_FEATURES_DINAMICAS`. |
| `src/data_ingestion/ingesta_geo.py` | New | `ingestar_snapshot_esri()`: atomic ingestion of an Esri delivery applying back-date policy. `listar_estado_geo()`: audit which locations have data and which features are pending. |
| `src/services/ml_predictivo.py` | Modified | Temporal join in training (each historical row gets the geo snapshot valid at its date). Latest snapshot for prediction. Graceful degradation: if store is empty, model trains exactly as before. |
| `docs/geo_esri_integration.md` | New | Full API reference for the integration layer. |
| `.gitignore` | Modified | Added `!geo_features.json` exception — the file was being silently ignored by the existing `*.json` rule. |

### Feature catalogue (`GEO_FEATURE_COLS`)

**Backdatable** (structural, slow-changing — back-dated to `2024-01-01` on first Esri delivery):
`poblacion_5min`, `poblacion_10min`, `poblacion_15min`, `dist_transporte_min_m`, `renta_media_cp`, `poblacion_cp`

**Dynamic** (fast-changing — only registered from Esri delivery date, never back-dated):
`densidad_comercial_score`, `indice_movilidad_peatonal`, `n_competidores_500m`, `dist_competidor_cercano_m`

### Key architectural decisions made

**Temporal snapshots, not flat scalars.** Geo features evolve (competitors open/close, population shifts). The store is append-only — snapshots are closed with `valid_to` but never deleted. Historical training rows get the snapshot valid at their date; this prevents data leakage.

**Back-date policy.** Structural features (population, transport distance, demographics) can be back-dated because today's value is a honest approximation of 2024's value. Dynamic features (competitor count, commercial density) cannot — back-dating them would tell the model the past had the same competitive context as today.

**Two snapshots on first Esri delivery.** `ingestar_snapshot_esri()` automatically creates:
1. `[2024-01-01 → delivery_date - 1]` — structural features only (back-dated)
2. `[delivery_date → open]` — all features including dynamic ones

**Graceful degradation is non-negotiable.** While all values are `null`, `geo_features_activos` is empty and the model runs identically to the pre-integration baseline.

### Errors and corrections during this session

- **Static scalars → temporal snapshots.** Initial implementation treated geo features as a flat dict (one value per location, no time dimension). Álvaro flagged this immediately: geo data changes over time, so static scalars would mean retraining with stale context. Refactored the entire store to versioned snapshots before any commit.
- **`*.json` gitignore rule.** `geo_features.json` was being silently ignored by git. Detected before commit and fixed with an explicit exception in `.gitignore`.
- **Import mismatch in `constructor_master.py`.** The code reads `loc.get('latitude', ...)` but the JSON field is `lat`. Pre-existing bug, not introduced here, but noted — worth fixing when touching that file.

### Pending changes NOT in this commit

The following pre-existing modifications are staged locally but not committed — they are unrelated to the geo integration:

- `app.py` — port changed from `8052` to `8051`
- `reporte.html` — deleted
- `requirements.txt` — modified

### Next steps for the next session

1. **Meet with Mario (Esri)** — evaluate Network Analysis, Business Analyst and POI endpoints, costs and licensing options.
2. **First Esri delivery** — call `ingestar_snapshot_esri(location_uuid, valores, fecha_entrega)` for each location. The back-date policy is already implemented and will fire automatically.
3. **Validate model impact** — compare accuracy/WMAPE before and after geo features on locations with extreme traffic peaks (Malaga Muelle 1, Madrid Gran Via). These are the locations where the spatial blindness is most visible.
4. **Scalability** — current architecture trains a model per zone per request (on-demand, no persistence). This works at the current scale but will not hold as tenant count grows or as Esri data adds training overhead. Next step: serialize trained models with `model.save_model()`, build a simple model registry keyed by `(location_uuid, zone_uuid, training_date)`, retrain on a schedule or on geo data update.
5. **Ingestion script** — integrate `ingesta_geo.py` into a scheduled pipeline or a one-shot CLI that consumes Esri output (CSV or GeoJSON) and calls `ingestar_snapshot_esri()` per location.
