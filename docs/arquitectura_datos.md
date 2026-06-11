# Arquitectura de datos — Agentic Workflow

**Versión:** 2026-06-01

---

## Por qué existe este documento

El sistema ha evolucionado de una colección de ficheros dispersos (CSVs por sesión, JSONs planos, cachés locales) a una base de datos estructurada. Este documento explica **qué hay ahora, por qué está así, y cómo añadir cosas nuevas** sin romper lo que ya funciona.

---

## 1. El problema que se resuelve

### Antes: datos fragmentados

Cada vez que un usuario abría el panel, se generaba un CSV nuevo con sus datos de visitas. Los datos geoespaciales vivían en un JSON sin tipado. El modelo de predicción tenía el calendario comercial y los festivos hardcodeados para España, sin posibilidad de configurar otras organizaciones. Si se quería probar una variable nueva (¿influyen los cruceros en las visitas de Málaga?), no había un sitio claro donde meterla ni forma de saber si realmente mejoraba las predicciones.

**Los síntomas concretos:**
- Duplicados entre sesiones de usuarios distintos
- Bug silencioso: el JSON usaba `latitude` pero el código leía `lat`
- El fichero de features de Esri quedó fuera de git sin que nadie se diera cuenta
- No había forma de evaluar si una variable nueva mejoraba o empeoraba el modelo

### Ahora: un único almacén ordenado

Todo el dato vive en **`src/data/agentic.duckdb`** — un único fichero de base de datos que cualquier proceso puede leer y escribir de forma segura. Los CSV de sesión siguen generándose como fallback mientras la migración está en curso, pero no son la fuente de verdad.

---

## 2. Qué es una *feature*

En este contexto, una **feature** es cualquier variable que el modelo de predicción puede usar para hacer mejores estimaciones de visitas. Por ejemplo:

- `es_festivo` — ¿es festivo nacional ese día? (sí/no)
- `temp_max` — temperatura máxima prevista (número)
- `n_pasajeros_crucero_dia` — cruceristas esperados en el puerto ese día (número)
- `poblacion_5min` — cuántas personas viven a 5 minutos a pie de la tienda (número)

Algunas features son universales (aplican a todas las tiendas), otras son específicas de una ubicación o país.

---

## 3. Las tablas de la base de datos

### Tablas de dimensiones — "el catálogo"

Describen las entidades del negocio. Se cargan una vez desde `todas_las_ubicaciones.json` y `users.json`, y se actualizan manualmente cuando cambia la estructura organizativa.

| Tabla | Contenido | Filas |
|---|---|---|
| `dim_organizaciones` | Las 4 organizaciones cliente (Miniso ES, Sam's Club MX, Kiosko MX, The Phone House ES) con su país y configuración de calendario | 4 |
| `dim_ubicaciones` | Las 13 tiendas físicas, cada una con coordenadas, ciudad, país y su org | 13 |
| `dim_zonas` | Las 46 zonas de conteo dentro de cada tienda (entradas, plantas, áreas) | 46 |
| `dim_usuarios` | Usuarios del panel: `user_id`, hash de contraseña, rol (`admin`/`user`), `last_login`. Reemplaza `users.json` | crece |

### Tabla de hechos — "los datos de visitas"

| Tabla | Contenido | Filas |
|---|---|---|
| `fact_visitas` | Una fila por día y zona: visitantes totales, únicos, nuevos, tiempo de permanencia, distribución horaria | ~4.300 y creciendo |

Esta tabla reemplaza los `dataset_*.csv`. El sincronizador (`sincronizador.py`) escribe aquí en lugar de a disco.

### Tablas de chat LLM — "historial de conversaciones"

| Tabla | Contenido |
|---|---|
| `chat_conversaciones` | Una fila por conversación: `conv_id`, `user_id`, título, `location_uuid` de contexto, timestamps. Reemplaza los JSON en `src/data/conversations/` |
| `chat_mensajes` | Un fila por mensaje: `conv_id`, `seq` (orden), `role` (`user`/`assistant`), `content` (texto o JSON serializado para mensajes con tool calls) |

Las conversaciones anteriores (JSON en disco) se migran con `seed_conversaciones()`. Los nuevos mensajes se escriben directamente en DuckDB desde `src/chatbot/history.py`.

### Tabla de modelos ML — "registry de modelos entrenados"

| Tabla | Contenido |
|---|---|
| `model_registry` | Una fila por par (location, zona): `trained_at`, lista de features usadas, métricas (`wmape`, `mae`, `accuracy`), ruta al fichero `.ubj` en disco. El binario XGBoost se almacena en `src/models/registry/` — DuckDB guarda los metadatos |

Cuando `ml_predictivo.py` entrena un modelo nuevo y lo serializa, escribe automáticamente en esta tabla.

### Tablas de features externas — "las señales"

Son las tablas más importantes para el modelo. Cada una almacena un tipo distinto de señal externa.

**`store_features_ext`** — serie temporal de cualquier variable numérica externa

```
fecha + location_uuid + feature_key → valor
```

Aquí viven el clima (temperatura, lluvia de Open-Meteo), los datos de PredictHQ (asistencia a conciertos, deportes) y los cruceristas de Málaga. La clave es que el formato es siempre el mismo independientemente de la fuente — añadir una fuente nueva no cambia el schema.

**`store_geo_snapshots`** — features geoespaciales de Esri, versionadas

```
location_uuid + feature_key + valid_from → valor
```

Las variables espaciales (población en radio 800m, renta media, número de competidores) se almacenan con periodo de validez porque cambian con el tiempo. Cuando Esri entrega datos nuevos, el snapshot anterior se cierra y se abre uno nuevo — el histórico nunca se borra.

**`store_calendario_org`** — eventos discretos por organización

```
org/ubicación + evento_key + fecha_inicio/fin → metadatos
```

Para eventos que no son series temporales continuas: escalas de crucero en Málaga, ferias locales, eventos corporativos. Desde aquí se agrega a `store_features_ext` (sumando pasajeros por día, por ejemplo).

### La tabla de control — `feature_registry`

Actúa como **contrato entre los datos y el modelo**. Cada variable que puede entrar al modelo tiene exactamente un registro aquí:

| Campo | Qué indica |
|---|---|
| `feature_key` | Nombre de la columna en el modelo |
| `source` | De dónde viene (`esri`, `open_meteo`, `predicthq`, `puerto_malaga`, `supercalendario`) |
| `status` | `testing` → en pruebas / `active` → en producción / `rejected` → descartada |
| `wmape_delta` | Cuánto mejoró (o empeoró) el error del modelo al incluirla |
| `org_applicability` | `"all"` o lista de org UUIDs donde aplica |
| `location_applicability` | `null` (toda la org) o lista de location UUIDs específicos |

El modelo **solo usa features con `status = 'active'`**. Esto significa que se pueden ingestar y probar variables nuevas sin que lleguen a producción hasta validarlas.

---

## 4. Cómo se integra con el panel

El flujo completo desde dato bruto hasta predicción en pantalla:

```
Aitanna API
    ↓
sincronizador.py → fact_visitas (DuckDB)
                        ↓
                   queries.py → get_df_enriquecido()
                        │
                        ├── clima (store_features_ext, Open-Meteo)
                        ├── festivos (pais_codigo de dim_organizaciones)
                        └── supercalendario (config_calendario de dim_organizaciones)
                        ↓
                   ml_predictivo.py → ejecutar_auditoria_predictiva()
                        │
                        ├── features Esri (store_geo_snapshots, temporal join)
                        ├── features PHQ (store_features_ext)
                        └── features org-específicas (store_features_ext)
                        ↓
                   XGBoost entrenado → predicciones + métricas
                        ↓
               Panel (ml_dashboard.py) + Chatbot (tools.py → get_forecast)
```

**Puntos clave:**
- `get_df_enriquecido()` en `queries.py` es el punto de entrada del pipeline: devuelve un DataFrame listo con visitas + clima + festivos.
- `ejecutar_auditoria_predictiva()` en `ml_predictivo.py` añade las features geoespaciales y entrena el modelo. Usa la cache de modelos en `src/models/registry/` — si las features no han cambiado y el modelo tiene menos de 7 días, reutiliza el entrenado.
- El chatbot tiene acceso al mismo modelo a través de la herramienta `get_forecast`.

---

## 5. El ciclo de vida de una feature nueva

Este es el proceso para añadir cualquier variable nueva al sistema — desde la idea hasta producción:

### Paso 1 — Descubrimiento
Antes de escribir código, responder:
- ¿Tiene datos históricos de al menos 6 meses solapados con el periodo de training?
- ¿Es automatizable (API, scraping) o requiere actualización manual?
- ¿A qué tienda o tiendas aplica?

### Paso 2 — Ingesta
Crear `src/data_ingestion/ingesta_<fuente>.py` que escriba los datos en DuckDB:

```
Fuente externa
    ↓
ingesta_<fuente>.py
    ├── store_calendario_org  (si son eventos discretos: crucero, feria, lanzamiento)
    └── store_features_ext    (siempre — serie temporal con fecha + location + valor)
```

Reglas:
- La ingesta debe ser **idempotente**: si se ejecuta dos veces, el resultado es el mismo (`ON CONFLICT DO NOTHING`).
- Si el dato es un evento discreto (crucero el jueves), va primero a `store_calendario_org` y luego se agrega a `store_features_ext`.
- Si ya es una serie continua (temperatura), va directamente a `store_features_ext`.

### Paso 3 — Registro
Dar de alta la feature en `feature_registry` con `status = 'testing'`:

```python
conn.execute("""
    INSERT INTO feature_registry
        (feature_key, source, categoria, org_applicability, location_applicability, status, notas)
    VALUES (?, ?, ?, ?, ?, 'testing', ?)
""", [key, source, categoria, org_scope, loc_scope, notas])
```

Con `status = 'testing'` la feature entra al training pero no se considera en producción.

### Paso 4 — Evaluación A/B
Entrenar el modelo con y sin la feature nueva sobre el mismo periodo y zona:

```python
# Modelo A — sin la feature
resultado_a = ejecutar_auditoria_predictiva(df, loc, zone, fecha, horizonte)

# Modelo B — con la feature (ya en store_features_ext)
resultado_b = ejecutar_auditoria_predictiva(df, loc, zone, fecha, horizonte)

wmape_delta = resultado_b['wmape_pct'] - resultado_a['wmape_pct']  # negativo = mejora
```

Zonas prioritarias para evaluar: **Málaga Muelle 1** y **Madrid Gran Vía** (donde el modelo actual tiene mayor error en picos de tráfico).

### Paso 5 — Decisión

| wmape_delta | Calidad del dato | Decisión |
|---|---|---|
| < −1.5 pp | Estable y automatizable | Promover a `active` |
| −1.5 a 0 pp | Mejora marginal | Mantener en `testing`, re-evaluar con más datos |
| > 0 pp | Ruido o data leakage | Promover a `rejected` |
| No aplica | Cobertura histórica insuficiente | Mantener en `testing` hasta conseguir histórico |

```python
conn.execute("""
    UPDATE feature_registry
    SET status = ?, wmape_delta = ?, notas = ?
    WHERE feature_key = ?
""", [decision, wmape_delta, notas, feature_key])
```

### Paso 6 — Producción
Las features `active` entran automáticamente al vector de entrenamiento. El modelo serializado en `src/models/registry/` incluye la lista de features en su metadata — si cambia (porque una nueva feature pasa a `active`), la cache se invalida y el modelo se reentrena en la siguiente llamada.

### Paso 7 — Deprecación
Una feature pasa a `rejected` si la fuente deja de funcionar, introduce drift, o un modelo entrenado sin ella da igual o mejor resultado. El dato histórico en `store_features_ext` se conserva para auditoría; solo cambia el `status` en el registry.

---

## 6. Estado actual del registry

| Fuente | Features | Status | Notas |
|---|---|---|---|
| `supercalendario` | 15 | `active` | ES y MX configurados por org |
| `open_meteo` | 3 | `active` | `temp_max`, `temp_min`, `llueve` — caché en `store_features_ext`, se rellena automáticamente en el primer entrenamiento por ubicación |
| `predicthq` | 7 | `testing` | Sin cobertura histórica en tier gratuito (~85% de filas en 0) |
| `puerto_malaga` | 1 | `testing` | Pendiente scraping automático y validación WMAPE |
| `esri` | 60 | `rejected` | Datos estáticos sin varianza temporal. No aportan señal al modelo de forecasting. Retirados 2026-06-01. Los datos permanecen en `store_geo_snapshots` para auditoría |

**Nota:** Las features derivadas del clima (`mucho_calor`, `mucho_frio`, `clima_ideal`, `finde_lluvioso`) se calculan en `ml_predictivo.py` a partir de `temp_max`, `temp_min`, `llueve` — no se almacenan en DuckDB.

**Vector de producción (features `active`):** 38 (base 20 + supercalendario 15 + open_meteo 3)
**Vector completo (incluyendo `testing`):** 46

---

## 7. Features org-específicas planificadas

| Org | Feature | Fuente | Estado |
|---|---|---|---|
| Miniso ES — Málaga Muelle 1 | `n_pasajeros_crucero_dia` | puertodemalaga.es | `testing` |
| Miniso ES — Málaga | `es_feria_malaga` | Manual / calendario | Planificada |
| The Phone House ES | `lanzamiento_movil` | Scraper prensa tech | Planificada |
| Sam's Club MX | — | Por definir | — |
| Kiosko MX | — | Por definir | — |

---

## 8. Cómo conectarse a la base de datos

### Desde código Python

```python
from src.db.store import get_conn
conn = get_conn()  # singleton por proceso, lee y escribe
```

### Desde terminal (exploración interactiva)

```bash
# TUI visual
.venv/bin/pip install harlequin
.venv/bin/harlequin src/data/agentic.duckdb

# CLI DuckDB
./duckdb src/data/agentic.duckdb
```

### Re-seed desde cero (idempotente)

```bash
# Migra todas_las_ubicaciones.json → dim_* y CSVs → fact_visitas
.venv/bin/python -m src.db.seed
```

---

## 9. Archivos de referencia

| Archivo | Qué hace |
|---|---|
| `src/db/store.py` | Schema DDL y conexión singleton. Se ejecuta automáticamente al arrancar |
| `src/db/seed.py` | Migración one-off desde JSON/CSV + función `ingest_visitas_csv()` |
| `src/db/queries.py` | Capa de lectura: `get_df_enriquecido()`, `get_geo_snapshot_df()`, caché de clima |
| `src/data_processing/supercalendario.py` | Eventos comerciales ES + MX con `CONFIG_PRESETS` por org |
| `src/data_processing/geo_enrichment.py` | `GEO_FEATURE_COLS` — fuente de verdad del schema Esri |
| `src/data_ingestion/ingesta_cruceros.py` | Ciclo completo: scraping puerto → `store_calendario_org` → `store_features_ext` |
| `src/services/ml_predictivo.py` | Ensamblaje del vector final, temporal join geo, festivos por país, cache de modelos |
