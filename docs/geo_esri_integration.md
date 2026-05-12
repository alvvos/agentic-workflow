# Geospatial Integration Layer — API Reference

Preparatory architecture for injecting Esri-derived geospatial features into the XGBoost forecasting model (`ml_predictivo.py`). Designed to eliminate spatial blindness in the current predictor, which today reverts to the mean and under-reacts to extreme traffic peaks caused by external spatial context.

---

## Architecture Overview

```
Esri (Network Analysis / Business Analyst / POI / Census)
        │
        ▼
src/data/geo_features.json          ← versioned snapshot store (per location_uuid)
        │
        ▼
src/data_processing/geo_enrichment.py   ← temporal lookup API
        │
        ├─── Training path ──────────────────────────────────────────────►
        │    get_geo_vals(location_uuid, fecha=<historical_date>)
        │    → snapshot valid at that date (avoids data leakage)
        │
        └─── Prediction path ────────────────────────────────────────────►
             get_geo_vals(location_uuid, fecha=None)
             → active snapshot (current state of the world)
```

The model consumes geospatial features as **static scalars per location**, injected into the feature matrix at training and prediction time. Because these scalars evolve (competitors open/close, population shifts, mobility changes), the store is versioned with temporal intervals rather than a simple key-value lookup.

---

## Feature Catalogue

Defined in `GEO_FEATURE_COLS` inside `geo_enrichment.py`. This list is the **single source of truth** — adding a feature here propagates automatically to training, prediction, and pipeline enrichment.

| Feature | Block | Source (Esri) | Unit |
|---|---|---|---|
| `poblacion_5min` | Isochrone | Network Analysis | persons |
| `poblacion_10min` | Isochrone | Network Analysis | persons |
| `poblacion_15min` | Isochrone | Network Analysis | persons |
| `densidad_comercial_score` | Commercial density | Business Analyst | [0.0 – 1.0] |
| `indice_movilidad_peatonal` | Mobility | Heat Map layer | [0.0 – 1.0] |
| `dist_transporte_min_m` | POI | Routing + POI layer | metres |
| `n_competidores_500m` | POI | POI layer | integer |
| `dist_competidor_cercano_m` | POI | Routing + POI layer | metres |
| `renta_media_cp` | Sociodemographic | Postal code polygon (INE/INEGI) | € / local currency |
| `poblacion_cp` | Sociodemographic | Postal code polygon (INE/INEGI) | persons |

---

## Feature Store — `src/data/geo_features.json`

### Structure

```json
{
  "_meta": { ... },
  "<location_uuid>": [
    {
      "valid_from": "YYYY-MM-DD",
      "valid_to":   "YYYY-MM-DD | null",
      "poblacion_5min": <number | null>,
      "poblacion_10min": <number | null>,
      "poblacion_15min": <number | null>,
      "densidad_comercial_score": <number | null>,
      "indice_movilidad_peatonal": <number | null>,
      "dist_transporte_min_m": <number | null>,
      "n_competidores_500m": <integer | null>,
      "dist_competidor_cercano_m": <number | null>,
      "renta_media_cp": <number | null>,
      "poblacion_cp": <integer | null>
    },
    ...
  ]
}
```

### Rules

- Each location is an **ordered list of snapshots**, sorted by `valid_from`.
- `valid_to: null` marks the **active snapshot** (open-ended, no closing date).
- Intervals must not overlap for the same location.
- Keys starting with `_` are reserved for metadata and are ignored by the lookup engine.
- Individual fields within a snapshot can be `null` if that data block has not been delivered yet. The model silently ignores null features.

### Adding a new Esri snapshot

When Esri delivers updated data, **do not overwrite** the previous entry. Close it and append a new one:

```json
"67034276-0d01-4c90-a363-fa75699a19a4": [
  {
    "valid_from": "2024-01-01",
    "valid_to":   "2025-05-31",
    "poblacion_10min": 12500,
    "n_competidores_500m": 3,
    ...
  },
  {
    "valid_from": "2025-06-01",
    "valid_to":   null,
    "poblacion_10min": 14200,
    "n_competidores_500m": 5,
    ...
  }
]
```

On the next model training run, historical rows from before `2025-06-01` will automatically pick up the first snapshot and rows from after will pick up the second. No code change required.

---

## Python API — `src/data_processing/geo_enrichment.py`

### `GEO_FEATURE_COLS`

```python
GEO_FEATURE_COLS: list[str]
```

Module-level constant. Ordered list of all geospatial feature names. Import this wherever feature lists need to stay in sync with the store schema.

---

### `get_geo_vals(location_uuid, fecha=None)`

Returns a flat dictionary of geospatial scalars for a location at a given point in time.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `location_uuid` | `str` | UUID of the location as defined in `todas_las_ubicaciones.json` |
| `fecha` | `str \| pd.Timestamp \| None` | Target date for the lookup. `None` returns the active snapshot (latest). |

**Returns** `dict[str, float | int | None]`

Keys are exactly `GEO_FEATURE_COLS`. Values are `None` if the location has no snapshot for the requested date, or if the field was not populated in that snapshot.

**Behaviour**

- `fecha=None` → returns the snapshot with `valid_to=null`. If no open-ended snapshot exists, falls back to the most recent closed one.
- `fecha=<date>` → returns the snapshot whose `[valid_from, valid_to]` interval contains that date. Returns all-`None` if no interval matches.

**Examples**

```python
from src.data_processing.geo_enrichment import get_geo_vals

# Latest snapshot — use for future date prediction
vals = get_geo_vals("67034276-0d01-4c90-a363-fa75699a19a4")
# → {"poblacion_10min": 14200, "n_competidores_500m": 5, ...}

# Historical snapshot — use during model training
vals = get_geo_vals("67034276-0d01-4c90-a363-fa75699a19a4", fecha="2024-08-15")
# → {"poblacion_10min": 12500, "n_competidores_500m": 3, ...}

# Location with no data populated
vals = get_geo_vals("3c73b012-fa57-4023-8d76-7b0e60cd6fbc")
# → {"poblacion_5min": None, "poblacion_10min": None, ...}
```

---

### `get_geo_features_activos(location_uuid, fecha=None)`

Returns only the feature names that have a non-null value for a given location and date.

**Parameters** — same as `get_geo_vals`.

**Returns** `list[str]`

Subset of `GEO_FEATURE_COLS` where the value is not `None`. Empty list if no data has been populated for this location — in which case the model trains and predicts exactly as it did before geo integration.

**Example**

```python
from src.data_processing.geo_enrichment import get_geo_features_activos

# All null (store not yet populated)
get_geo_features_activos("3c73b012-fa57-4023-8d76-7b0e60cd6fbc")
# → []

# Partially populated (only isochrone block delivered so far)
get_geo_features_activos("67034276-0d01-4c90-a363-fa75699a19a4")
# → ["poblacion_5min", "poblacion_10min", "poblacion_15min"]
```

---

### `enriquecer_con_geo(df, col_location_id="location_id", col_fecha="fecha")`

Temporal join of geospatial scalars onto a multi-location DataFrame. Intended for the BI/reporting pipeline (`feature_engineering.py`).

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `df` | `pd.DataFrame` | — | Input DataFrame |
| `col_location_id` | `str` | `"location_id"` | Column name containing the location UUID |
| `col_fecha` | `str` | `"fecha"` | Column name containing the date. If absent from `df`, uses the active snapshot for all rows. |

**Returns** `pd.DataFrame`

Original DataFrame with additional columns for each geospatial feature that has at least one non-null value in the join result. Columns with all-null results are not added. The join is a left join — rows with no matching snapshot receive `NaN`.

**Example**

```python
from src.data_processing.geo_enrichment import enriquecer_con_geo

df_enriched = enriquecer_con_geo(df_master, col_location_id="location_id", col_fecha="fecha")
```

---

## Integration with the Forecasting Model

The integration in `ml_predictivo.py` follows two distinct paths to prevent data leakage:

### Training path

```python
# Each historical training row receives the geo snapshot valid at its date.
# A training row from 2024-03-10 will NOT see geo data delivered in 2025.
geo_rows = pd.DataFrame(
    [get_geo_vals(location_uuid, fecha) for fecha in train['fecha']],
    index=train.index
)
geo_features_activos = [c for c in GEO_FEATURE_COLS if geo_rows[c].notna().any()]
for col in geo_features_activos:
    train[col] = geo_rows[col].values
```

### Prediction path

```python
# Future dates use the current state of the world (active snapshot, no date argument).
geo_vals_pred = get_geo_vals(location_uuid)

# Applied inside the autoregressive loop:
row = pd.DataFrame([{
    ...temporal and weather features...,
    **{col: geo_vals_pred[col] for col in geo_features_activos}
}])
```

### Graceful degradation

`geo_features_activos` is derived from actual non-null values. When all values are `null` (i.e., Esri data has not been delivered yet), this list is empty and the `features` list passed to XGBoost is identical to the pre-integration baseline. The model runs unchanged.

---

## Cache

The store file is read once per Python process and cached in memory. The cache is invalidated automatically when the file's modification timestamp changes, so updating `geo_features.json` with new Esri data does not require restarting the application.

---

## Adding a New Feature

1. Add the field name to `GEO_FEATURE_COLS` in `geo_enrichment.py`.
2. Add the field to `_meta.schema` in `geo_features.json` (documentation only).
3. Add `"new_feature": null` to all existing snapshot objects in `geo_features.json`.
4. No changes required in `ml_predictivo.py` — the training and prediction loops derive the active feature list dynamically from `GEO_FEATURE_COLS`.
