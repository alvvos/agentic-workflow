# DB_SCHEMA — Agentic Workflow

**Motor:** PostgreSQL 16 (Docker Compose)
**Conexión:** `src/db/store.py` → pool psycopg v3, thread-local, autocommit
**DDL:** se aplica automáticamente en el primer `get_conn()` de cada proceso (`_apply_ddl`)
**Última revisión:** 2026-06-30

---

## Cómo conectarse

```python
from src.db.store import get_conn
conn = get_conn()
rows = conn.execute("SELECT ...", [params]).fetchall()
df   = conn.execute("SELECT ...").df()       # → pd.DataFrame
conn.executemany("INSERT ...", list_of_rows)
```

```bash
# Desde terminal en el servidor (descubre el contenedor dinámicamente)
docker exec -i $(docker ps --filter name=postgres --format "{{.Names}}" | head -1) \
  psql -U agentic -d agentic
```

---

## Grupos de tablas

| Grupo | Tablas |
|---|---|
| Dimensiones | `dim_organizaciones`, `dim_ubicaciones`, `dim_zonas`, `dim_usuarios`, `user_org_access` |
| Hechos | `fact_visitas` |
| Features externas | `store_features_ext`, `store_geo_snapshots`, `feature_registry`, `feature_flags`, `feature_eval_results` |
| Calendario/eventos | `store_calendario_org` |
| Modelos ML | `model_registry` |
| Chatbot | `chat_conversaciones`, `chat_mensajes`, `cache_responses` |
| Registros de display | `poi_category_registry`, `zone_type_registry`, `narrative_category_registry`, `alert_level_registry` |

---

## Dimensiones

### `dim_organizaciones`
Clientes/tenants del sistema.

| Columna | Tipo | Descripción |
|---|---|---|
| `org_uuid` | TEXT PK | UUID de la organización |
| `nombre` | TEXT NN | Nombre (ej. "Miniso ES") |
| `pais_codigo` | TEXT NN | Código ISO (ej. "ES", "MX") |
| `config_calendario` | JSONB | Configuración de supercalendario por org |

---

### `dim_ubicaciones`
Tiendas físicas. Fuente de verdad del árbol: se actualiza vía `actualizar_arbol_ubicaciones.py`.

| Columna | Tipo | Descripción |
|---|---|---|
| `location_uuid` | TEXT PK | UUID de la ubicación |
| `org_uuid` | TEXT NN → `dim_organizaciones` | FK organización |
| `nombre` | TEXT NN | Nombre de la tienda |
| `lat` | DOUBLE | Latitud (NULL → excluida de prefetch) |
| `lon` | DOUBLE | Longitud (NULL → excluida de prefetch) |
| `ciudad` | TEXT | Ciudad |
| `provincia` | TEXT | Provincia |
| `pais_codigo` | TEXT NN | Código ISO del país |
| `region_code` | TEXT | Código de región Aitanna |
| `country_code` | TEXT | Código de país Aitanna |
| `codigo_postal` | TEXT | CP |
| `direccion` | TEXT | Dirección completa |
| `activa` | BOOLEAN | Default TRUE; FALSE = no sincronizar |
| `catchment_rings_json` | TEXT | GeoJSON de isócronas (Esri, opcional) |

> `get_active_locations()` filtra `WHERE activa = TRUE AND lat IS NOT NULL AND lon IS NOT NULL`.

---

### `dim_zonas`
Zonas de conteo dentro de cada tienda.

| Columna | Tipo | Descripción |
|---|---|---|
| `zone_uuid` | TEXT PK | UUID de la zona |
| `location_uuid` | TEXT NN → `dim_ubicaciones` | FK tienda |
| `nombre` | TEXT NN | Nombre visible |
| `hidden` | BOOLEAN | Si TRUE, no se muestra en el panel |
| `zone_type` | TEXT | Tipo Aitanna (ej. "entrance") |
| `parent_zone_uuid` | TEXT → `dim_zonas` | FK zona padre (jerarquía) |
| `sort_order` | INT | Orden de presentación |
| `last_zone` | BOOLEAN | TRUE = hoja del árbol (zona de detalle) |

---

### `dim_usuarios`
Usuarios del panel. Se sincroniza desde `users.json` en cada arranque.

| Columna | Tipo | Descripción |
|---|---|---|
| `user_id` | TEXT PK | Nombre de usuario |
| `password_hash` | TEXT NN | Hash SHA-256 de la contraseña |
| `role` | TEXT | `'admin'` o `'user'` |
| `created_at` | TIMESTAMP | Creación |
| `last_login` | TIMESTAMP | Último acceso |

---

### `user_org_access`
Qué organizaciones puede ver cada usuario.

| Columna | Tipo |
|---|---|
| `user_id` | TEXT PK → `dim_usuarios` CASCADE |
| `org_uuid` | TEXT PK → `dim_organizaciones` CASCADE |

---

## Hechos

### `fact_visitas`
Una fila por día y zona. Fuente principal de datos para el modelo y el panel.

| Columna | Tipo | Descripción |
|---|---|---|
| `fecha` | DATE PK | Fecha del dato |
| `zone_uuid` | TEXT PK → `dim_zonas` | Zona |
| `location_uuid` | TEXT NN → `dim_ubicaciones` | Tienda (desnormalizado para índices) |
| `org_uuid` | TEXT NN | Organización (desnormalizado) |
| `total_visits` | INT | Visitas totales |
| `unique_visitors` | INT | Visitantes únicos |
| `new_visitors` | INT | Visitantes nuevos |
| `uv_7d` | DOUBLE | Únicos acumulados 7 días |
| `uv_28d` | DOUBLE | Únicos acumulados 28 días |
| `uv_month` | DOUBLE | Únicos mes |
| `uv_year` | DOUBLE | Únicos año |
| `freq_7d` | DOUBLE | Frecuencia 7 días |
| `freq_28d` | DOUBLE | Frecuencia 28 días |
| `freq_month` | DOUBLE | Frecuencia mensual |
| `freq_year` | DOUBLE | Frecuencia anual |
| `dwell_time_min` | DOUBLE | Tiempo de permanencia (minutos) |
| `dwell_hist` | TEXT | JSON: histograma de permanencia |
| `hourly_visits` | TEXT | JSON: distribución horaria |

**Índice:** `idx_fact_loc_fecha` en `(location_uuid, fecha)`

---

## Features externas

### `store_features_ext`
Serie temporal de cualquier señal externa. Esquema único para todas las fuentes.

| Columna | Tipo | Descripción |
|---|---|---|
| `fecha` | DATE PK | Fecha |
| `location_uuid` | TEXT PK → `dim_ubicaciones` | Tienda |
| `feature_key` | TEXT PK → `feature_registry` CASCADE | Identificador de feature |
| `value` | DOUBLE | Valor numérico |
| `ingested_at` | TIMESTAMP | Cuándo se escribió |

**Regla:** features mensuales (ej. ICM INE) se expanden a todos los días del mes en la ingesta. Features de evento (ej. cruceros) solo tienen fila los días con dato — los días sin fila valen 0 (`fillna(0.0)` en lectura). **Nunca `ffill`.**

---

### `store_geo_snapshots`
Features geoespaciales de Esri, versionadas con periodo de validez.

| Columna | Tipo | Descripción |
|---|---|---|
| `location_uuid` | TEXT PK → `dim_ubicaciones` | Tienda |
| `feature_key` | TEXT PK | Variable Esri (ej. `poblacion_5min`) |
| `valid_from` | DATE PK | Inicio del periodo de validez |
| `value` | DOUBLE | Valor |
| `valid_to` | DATE | Fin del periodo (NULL = activo) |
| `ingested_at` | TIMESTAMP | Cuándo se ingirió |

**Política de backdating:** features estructurales (población, renta) se backdatan a `2024-01-01` en la primera entrega. Features dinámicas (competidores, movilidad) solo desde la fecha de entrega. Los snapshots nunca se borran — se cierran con `valid_to`.

---

### `feature_registry`
Catálogo global de features. **Fuente de verdad**: tiene `ON DELETE CASCADE` hacia `store_features_ext`, `feature_flags` y `feature_eval_results`. Desde v2.2.47 también es la fuente de toda la metadata de display de la capa de render.

| Columna | Tipo | Descripción |
|---|---|---|
| `feature_key` | TEXT PK | Identificador canónico |
| `source` | TEXT NN | Origen: `open_meteo`, `supercalendario`, `predicthq`, `cruceros`, `esri`, `ine`, `academic_calendar` |
| `categoria` | TEXT | `clima`, `calendario`, `eventos`, `macroeconomia` |
| `org_applicability` | JSONB | `"all"` o lista de org UUIDs |
| `location_applicability` | JSONB | NULL (toda la org) o lista de location UUIDs |
| `status` | TEXT | `'incompleto'` o `'con_cobertura'` |
| `notas` | TEXT | Descripción, metodología, caveats — **fuente de tooltips en el panel** |
| `registrado_en` | TIMESTAMP | Cuándo se registró |
| `label` | TEXT | Etiqueta de display (ej. "Cruceros") |
| `sublabel` | TEXT | Subtítulo opcional en cards |
| `color` | VARCHAR(16) | Color hex de la señal en el panel |
| `icon_cls` | VARCHAR(64) | Clase Font Awesome (ej. `fas fa-ship`) |
| `agg_fn` | VARCHAR(16) | Función de agregación: `sum` · `mean` · `max` |
| `display_mode` | TEXT | Componente de render: `'yoy'` · `'events_count'` · `'cruceros'` · `'calendario'` · `'hidden'` |
| `canonical_type` | TEXT | Tipo canónico para normalización (ej. `tm_concierto → concierto`). NULL = no es un tipo de evento. |

> `incompleto` → hay feature pero faltan datos en `store_features_ext`. `con_cobertura` → promovido automáticamente por `_promote_if_covered()` al final de la ingesta.

---

### `feature_flags`
Decisión por ubicación de si una feature entra al modelo.

| Columna | Tipo | Descripción |
|---|---|---|
| `feature_key` | TEXT PK → `feature_registry` CASCADE | Feature |
| `location_uuid` | TEXT PK → `dim_ubicaciones` | Tienda |
| `status` | TEXT NN | `'active'` (entra al modelo) · `'contexto'` (visible en panel, no en modelo) · `'inactive'` (oculto) |
| `wmape_delta` | DOUBLE | Impacto en WMAPE (negativo = mejora) |
| `evaluated_at` | TIMESTAMPTZ | Cuándo se evaluó |
| `periodicidad` | TEXT | `'diaria'` · `'mensual'` · `'trimestral'` · `'puntual'` · `'nunca'` |

---

### `feature_eval_results`
Resultados walk-forward de evaluación de features (del notebook `feature_lab.ipynb`).

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | SERIAL PK | — |
| `evaluated_at` | TIMESTAMPTZ | — |
| `feature_key` | TEXT → `feature_registry` CASCADE | — |
| `location_uuid` | TEXT | — |
| `split_idx` | INT | Ventana de evaluación |
| `fecha_eval_ini/fin` | DATE | Rango del split |
| `n_train / n_eval` | INT | Tamaños de los sets |
| `wmape_baseline` | DOUBLE | WMAPE sin la feature |
| `wmape_con_feat` | DOUBLE | WMAPE con la feature |
| `wmape_delta` | DOUBLE | Diferencia (negativo = mejora) |
| `horizonte` | INT | Días de forecast |

---

## Calendario/eventos

### `store_calendario_org`
Eventos discretos ligados a una org o ubicación. Cruceros, ferias, Ticketmaster, etc.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | Auto-generado |
| `org_uuid` | TEXT → `dim_organizaciones` | Organización (nullable) |
| `location_uuid` | TEXT → `dim_ubicaciones` | Tienda concreta (nullable) |
| `pais_codigo` | TEXT | Código de país del evento |
| `evento_key` | TEXT NN | Tipo: `tm_concierto`, `escala_crucero`, `festivo_local`, etc. |
| `fecha_inicio` | DATE NN | Inicio del evento |
| `fecha_fin` | DATE NN | Fin del evento |
| `metadata` | JSONB | Info extra: título, venue, aforo, pax, etc. |
| `fuente` | TEXT | `'ticketmaster'`, `'manual'`, `'puerto_malaga'`, etc. |
| `source_key` | TEXT UNIQUE | Clave de deduplicación (ej. `tm_<event_id>`) |

**Índices:** `idx_cal_org_fecha (org_uuid, fecha_inicio)`, `idx_cal_loc_fecha (location_uuid, fecha_inicio)`

---

## Modelos ML

### `model_registry`
Metadatos de modelos XGBoost entrenados. El binario va en `src/models/registry/*.ubj`.

| Columna | Tipo | Descripción |
|---|---|---|
| `model_id` | TEXT PK | Clave: `{location_uuid}__{zone_uuid}` |
| `location_uuid` | TEXT NN → `dim_ubicaciones` CASCADE | Tienda |
| `zone_uuid` | TEXT NN → `dim_zonas` CASCADE | Zona |
| `trained_at` | TIMESTAMP | Cuándo se entrenó |
| `features` | JSONB | Lista de features usadas |
| `metrics` | JSONB | `{wmape, mae, accuracy}` |
| `model_path` | TEXT | Ruta al `.ubj` en disco |
| `is_valid` | BOOLEAN | FALSE = invalidado (re-entrenar) |

---

## Chatbot

### `chat_conversaciones`
Una fila por conversación de usuario con el asistente IA.

| Columna | Tipo | Descripción |
|---|---|---|
| `conv_id` | TEXT PK | UUID de la conversación |
| `user_id` | TEXT NN → `dim_usuarios` CASCADE | Usuario |
| `title` | TEXT | Título auto-generado del primer mensaje |
| `location_uuid` | TEXT → `dim_ubicaciones` CASCADE | Contexto de ubicación |
| `created_at` | TIMESTAMP | — |
| `updated_at` | TIMESTAMP | Último mensaje |

**Índice:** `idx_chat_user_updated (user_id, updated_at)`

---

### `chat_mensajes`
Un mensaje por fila, ordenados por `seq` dentro de cada conversación.

| Columna | Tipo | Descripción |
|---|---|---|
| `msg_id` | UUID PK | Auto-generado |
| `conv_id` | TEXT NN → `chat_conversaciones` CASCADE | Conversación |
| `seq` | INT NN | Número de orden |
| `role` | TEXT NN | `'user'` o `'assistant'` |
| `content` | TEXT | Texto o JSON serializado (tool calls) |
| `created_at` | TIMESTAMP | — |

---

### `cache_responses`
Caché de respuestas del chatbot para preguntas frecuentes.

| Columna | Tipo | Descripción |
|---|---|---|
| `cache_key` | TEXT PK | Hash SHA-256 de question + location |
| `question` | TEXT NN | Pregunta original |
| `location_uuid` | TEXT → `dim_ubicaciones` CASCADE | Contexto |
| `answer` | TEXT NN | Respuesta cacheada |
| `created_at` | TIMESTAMP | — |
| `hits` | INT | Veces servida desde caché |
| `expires_at` | TIMESTAMP NN | TTL (indexado para purga) |

**Índice:** `idx_cache_expires (expires_at)`

---

## Registros de display (DB-driven render layer)

Estas tablas controlan completamente la presentación visual del panel. No hay dicts hardcodeados en Python — toda decisión de label/color/icono viene de aquí.

### `poi_category_registry`
Metadatos de display para categorías de POIs en el mapa geoespacial.

| Columna | Tipo | Descripción |
|---|---|---|
| `category` | TEXT PK | Clave de categoría (ej. `'competidor'`, `'transporte'`) |
| `label` | TEXT NN | Etiqueta visible |
| `icon_cls` | VARCHAR(64) | Clase Font Awesome |
| `color` | VARCHAR(16) | Color hex del marcador |
| `badge_color` | VARCHAR(16) | Color del badge en lista lateral |

---

### `zone_type_registry`
Estilos por tipo de zona de conteo (tienda, caja, calle/exterior).

| Columna | Tipo | Descripción |
|---|---|---|
| `zone_type` | TEXT PK | Tipo: `'tienda'`, `'caja'`, `'exterior'`, `'default'` |
| `label` | TEXT NN | Etiqueta visible en el panel |
| `icon_cls` | VARCHAR(64) | Clase Font Awesome |
| `color` | VARCHAR(16) | Color del encabezado de zona |
| `tooltip` | TEXT | Texto de tooltip explicativo |

---

### `narrative_category_registry`
Categorías de la narrativa ejecutiva (acordeón en el Panel PM).

| Columna | Tipo | Descripción |
|---|---|---|
| `category_key` | TEXT PK | Clave interna (ej. `'rendimiento'`, `'contexto'`) |
| `label` | TEXT NN | Etiqueta en el acordeón |
| `icon_cls` | VARCHAR(64) | Clase Font Awesome |
| `sort_order` | INT | Orden de presentación (default 99) |

---

### `alert_level_registry`
Niveles de alerta para los mensajes de la narrativa.

| Columna | Tipo | Descripción |
|---|---|---|
| `level_key` | TEXT PK | Clave del nivel (ej. `'ok'`, `'warning'`, `'critical'`) |
| `text_color` | VARCHAR(16) | Color del texto |
| `bg_color` | VARCHAR(16) | Color de fondo del badge |
| `sort_order` | INT | Orden visual (default 99) |

---

## Tablas de configuración por ubicación/fuente

### `location_pois`
Puntos de interés geoespaciales ligados a una ubicación (competidores, transporte, etc.). Datos Esri Places + manuales.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | SERIAL PK | — |
| `org_uuid` | TEXT NN | Organización |
| `location_uuid` | TEXT NN → `dim_ubicaciones` | Tienda |
| `nombre` | TEXT NN | Nombre del POI |
| `lat` / `lon` | DOUBLE NN | Coordenadas |
| `categoria` | TEXT NN | `'competidor'`, `'transporte'`, `'ocio'`, etc. |
| `valor_relativo` | DOUBLE | Score de importancia (0–1, default 0.5) |
| `detalle` | TEXT | Info extra (ej. línea de metro) |
| `radio_m` | INT | Radio de búsqueda usado al descubrir el POI |
| `isocrona_minutos` | INT | Isócrona a pie en minutos |
| `isocrona_geojson` | JSONB | GeoJSON de la isócrona (Esri Network Analysis) |
| `fuente` | TEXT | `'manual'`, `'esri_places'`, etc. |
| `activo` | BOOLEAN | Default TRUE |
| `created_at` | TIMESTAMP | — |

**Unique:** `(location_uuid, nombre, categoria)`

---

### `location_source_config`
Configuración por ubicación y fuente de datos externa. PK compuesta `(location_uuid, source)`. Los ingestores leen aquí sus parámetros específicos (p.ej., `port_authority` para Puertos del Estado, `estaciones` + `iata` para metro/AENA).

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | SERIAL PK | — |
| `location_uuid` | TEXT NN | Tienda |
| `source` | TEXT NN | Identificador de la fuente (`'metro_madrid'`, `'puertos_estado'`, `'aena'`, etc.) |
| `params` | JSONB NN | Parámetros específicos. Ver `docs/source_params_contract.md` |
| `activo` | BOOLEAN NN | Default TRUE. FALSE = ingestor la ignora |
| `created_at` | TIMESTAMP NN | — |

**Unique:** `(location_uuid, source)`

**Cómo añadir una fuente nueva:** `INSERT INTO location_source_config (location_uuid, source, params) VALUES ('...', 'nueva_fuente', '{"clave": "valor"}')`. Sin tocar código de ingestores.

---

## Estado actual del feature registry (2026-06-30)

| Fuente | Features | Status | Notas |
|---|---|---|---|
| `supercalendario` | 15 | `con_cobertura` / active | ES y MX configurados por org |
| `open_meteo` | 3 | `con_cobertura` / active | `temp_max`, `temp_min`, `llueve` |
| `predicthq` | 7 | `con_cobertura` / inactive | Sin cobertura histórica en tier gratuito |
| `cruceros` | 1 | `con_cobertura` / active (Málaga) | `n_pasajeros_crucero_dia` |
| `esri` | 47 | `con_cobertura` / inactive | Datos estáticos, no aportan varianza temporal al forecast |
| `metro_madrid` | 2+ | `contexto` para Madrid Gran Vía | `afluencia_metro_gran_via`, `afluencia_metro_callao`. Visibles en señal de contexto, no entran al modelo |

**Vector de producción (active):** ~19 features base + 15 supercalendario + 3 clima + 1 cruceros (Málaga)

> Features con `status='contexto'` son visibles en el panel "Señal del contexto exterior" pero no entran al modelo ML. `_render_senal_contexto_modal()` usa `AND f.status IN ('active', 'contexto')` para incluirlas.
