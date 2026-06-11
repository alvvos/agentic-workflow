# Feature Pipeline — Marco de producción

Documento de referencia sobre cómo una feature externa entra al sistema, gana cobertura y queda activa en el modelo.

---

## Visión general

```
Fuente externa
     │
     ▼
store_features_ext          ← tabla de series temporales (fecha, location, feature_key, value)
     │
     ▼
feature_registry            ← catálogo global: incompleto → con_cobertura
     │
     ▼
feature_lab.ipynb           ← evaluación WMAPE walk-forward por ubicación
     │
     ▼
feature_flags               ← decisión por ubicación: inactive → active
     │
     ▼
queries.get_active_ext_features()   ← consumido por el modelo
```

---

## 1. Tablas involucradas

### `feature_registry` — catálogo global

| columna     | tipo    | descripción |
|-------------|---------|-------------|
| feature_key | PK text | identificador canónico de la feature |
| source      | text    | origen: `ine`, `open_meteo`, `esri`, `academic_calendar`, `cruceros` |
| categoria   | text    | `macroeconomia`, `clima`, `calendario`, `eventos` |
| status      | text    | `incompleto` o `con_cobertura` |
| notas       | text    | descripción, metodología, caveats |

**`feature_registry` es la fuente de verdad.** Tiene ON DELETE CASCADE hacia:
- `store_features_ext`
- `feature_flags`
- `feature_eval_results`

Borrar una feature del registro la elimina de toda la base de datos.

### `store_features_ext` — series temporales

Granularidad: 1 fila por `(fecha, location_uuid, feature_key)`.

Regla de escritura:
- **Features mensuales** (e.g., ICM de INE): se expanden a todos los días del mes en el momento de la ingesta. Cada día del mes tiene su propio registro con el mismo valor.
- **Features de evento** (e.g., cruceros): 1 fila únicamente los días con datos. Los días sin fila tienen valor implícito 0.

Nunca se usa `ffill`. La lectura siempre aplica `fillna(0.0)` para los días sin dato.

### `feature_flags` — decisión por ubicación

| columna       | tipo | descripción |
|---------------|------|-------------|
| feature_key   | PK   | FK → feature_registry |
| location_uuid | PK   | FK → dim_ubicaciones |
| status        | text | `active` o `inactive` |

El modelo solo carga features con `status = 'active'` para la ubicación concreta.

---

## 2. Estados y transiciones

### En `feature_registry`

```
incompleto  ──(ingesta con cobertura completa)──▶  con_cobertura
```

`incompleto`: la feature está registrada pero no hay datos en `store_features_ext` que cubran todos los días de `fact_visitas`. No puede entrar al modelo.

`con_cobertura`: existen datos para todos los días necesarios. Puede ser evaluada en el notebook y activada por ubicación.

La promoción ocurre automáticamente al final de cada script de ingesta (`_promote_if_covered()`): verifica que para cada ubicación no quede ningún día de `fact_visitas` sin un registro en `store_features_ext`.

### En `feature_flags`

```
(no existe)  ──(seed global o decisión manual)──▶  inactive / active
```

Los flags se crean via `seed.seed_feature_flags()` o mediante el notebook tras la evaluación WMAPE.

**Decisiones globales aplicadas en el seed:**
- `open_meteo` (clima): `active` en todas las ubicaciones — cobertura histórica completa desde el primer día, correlación probada.
- `esri` (geo): `inactive` en todas las ubicaciones — pendiente de primera entrega de datos de Esri.
- El resto: sin flag hasta evaluación individual por ubicación.

---

## 3. Scripts de ingesta

### `src/lab/ingest_features.py`

Gestiona ICM (INE) y calendario escolar.

```bash
python src/lab/ingest_features.py                         # todas, últimos 36 meses
python src/lab/ingest_features.py --source ine_icm        # solo ICM
python src/lab/ingest_features.py --source academic_cal --desde 2023-01-01 --hasta 2026-12-31
```

Al terminar llama a `_promote_if_covered()` y actualiza `feature_registry.status` si procede.

### `src/data_ingestion/prefetch/cruceros.py`

Sincroniza previsión de cruceros desde la API WordPress del Puerto de Málaga.

```bash
python -m src.data_ingestion.prefetch.cruceros              # mes anterior + actual + siguiente
python -m src.data_ingestion.prefetch.cruceros --desde 2024-01 --hasta 2026-06
python -m src.data_ingestion.prefetch.cruceros --dry-run    # imprime sin escribir
```

Endpoint: `POST https://www.puertomalaga.com/wp-admin/admin-ajax.php`
`action=get_prevision_turistas_by_date&date=MM/YYYY`

Feature generada: `n_pasajeros_crucero_dia`. Solo se escriben filas para días con escala — los días sin crucero no tienen fila (valor implícito 0 en la lectura).

### `src/data_ingestion/prefetch/` (otros)

- `open_meteo.py`: clima histórico y forecast para todas las ubicaciones activas.
- `supercalendario.py`: festivos, eventos locales, datos de afluencia de `dim_eventos`.

---

## 4. Evaluación en el notebook (`feature_lab.ipynb`)

El notebook hace walk-forward WMAPE: entrena el modelo base, luego lo entrena añadiendo la feature candidata, y compara el error medio sobre múltiples ventanas de evaluación.

Flujo de uso:
1. **Celda de ubicación**: seleccionar una o varias ubicaciones en `loc_sel`.
2. **Celda de features**: se auto-puebla con features en estado `con_cobertura` que aún no tienen decisión (`active`/`inactive`) para las ubicaciones seleccionadas.
3. Ejecutar la evaluación. Resultado: `wmape_delta` negativo = la feature mejora el modelo.
4. Marcar como `active` o `inactive` en `feature_flags` según el resultado.

La consulta de features disponibles excluye automáticamente las que ya tienen flag para **todas** las ubicaciones seleccionadas, para evitar re-evaluar lo ya decidido.

---

## 5. Lectura en el modelo

`src/db/queries.get_active_ext_features(location_uuid, fecha_min, fecha_max)`:

1. Consulta `feature_flags WHERE location_uuid = ? AND status = 'active'`.
2. Para cada feature activa, lee `store_features_ext` en el rango de fechas.
3. Re-indexa al rango completo y aplica `fillna(0.0)` — sin ffill.
4. Devuelve un `dict[feature_key → np.ndarray]` alineado día a día con `fact_visitas`.

---

## 6. Política de relleno

**No se usa `ffill` en ningún punto del sistema.**

| tipo de feature | estrategia de escritura | lectura si falta día |
|-----------------|------------------------|----------------------|
| mensual (ICM)   | expandir a todos los días del mes en ingesta | — (siempre hay fila) |
| diaria con eventos (cruceros, festivos) | escribir solo días con dato | `fillna(0.0)` |
| diaria continua (clima) | un registro por día | `fillna(0.0)` |

La razón: `ffill` propaga el valor del último crucero a todos los días siguientes, haciendo que el modelo no pueda distinguir días con escala de días sin ella.

---

## 7. Añadir una feature nueva

1. Crear el ingestor en `src/data_ingestion/prefetch/` o `src/lab/`.
2. Escribir en `store_features_ext` con la política correcta (expandir si mensual, raw si evento).
3. Registrar en `feature_registry` con `status = 'incompleto'`.
4. Ejecutar el ingestor. Si `_promote_if_covered()` pasa, el status cambia a `con_cobertura`.
5. Abrir `feature_lab.ipynb`, seleccionar ubicaciones, evaluar WMAPE.
6. Actualizar `feature_flags` con la decisión.
