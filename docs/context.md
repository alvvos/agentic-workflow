# Contexto de sesión — Agentic Workflow

**Última actualización:** 2026-05-27  
**Branch:** main  
**Commits recientes:** 950e601 (fix ventana PM), e2cd1d0 (refactor PM panel)

---

## Estado actual — qué está hecho y funcionando

### Esri GeoEnrichment ✅ — 4 ubicaciones en producción
- **Cuenta ArcGIS Location Platform** activa, pay-as-you-go, key en `.env` → `ESRI_KEY`
- **Privilegios de la key:** GeoEnrichment + Routing + Places + Basemaps
- **Enriquecimiento ejecutado** el 2026-05-27: 3 Miniso España + 1 Barceló
- **Coste total real:** ~0.51 USD (42 vars × 3 anillos × 4 locs = 504 atributos)
- **RingBuffer** 400/800/1200 m como proxy peatonal (NetworkServiceArea falla — permanente hasta resolverlo con Esri)

### Feature store geo (`src/data/geo_features.json`)
Las 4 ubicaciones tienen **42/47 features** con datos AIS reales. Los 5 nulos son Phase 2 (Places+Routing), esperados.

| Ubicación | UUID | pob_5min | renta_hogar_anual | gasto_ropa_calzado |
|---|---|---|---|---|
| Malaga Muelle 1 | 67034276-… | 5.170 | 29.547 € | 1.286 € |
| Valencia Bonaire | db01e2ed-… | 8.828 | 35.500 € | 1.367 € |
| Madrid Gran Via | 251e7f40-… | 10.820 | 33.449 € | 1.330 € |
| Barceló Corales Villas | bcb4c229-… | 179 | 18.885 € | 557 € |

⚠ `empleados_por_hogar` (TOTOCCME): valores (19/19/42/1) anómalamente bajos — posible unidad diferente en AIS. Verificar antes de usar en modelo.

**Política de snapshots:**
- Miniso: snapshot activo desde `2026-05-27` (nuevo) — encima de los anteriores
- Barceló: 2 snapshots — `[2024-01-01 → 2026-05-26]` backdatable + `[2026-05-27 → open]` activo

### Esquema de features — 47 features (`src/data_processing/geo_enrichment.py`)

```python
GEO_FEATURE_COLS = [
    # Bloque 1 — Isócronas (RingBuffer)
    "poblacion_5min",           # PEOPLE @ 400m
    "poblacion_10min",          # PEOPLE @ 800m
    "poblacion_15min",          # PEOPLE @ 1200m
    # Bloque 2 — Edad (800m)
    "pob_15_19",                # POPAG15
    "pob_20_24",                # POPAG20
    "pob_25_29",                # POPAG25
    "pob_30_34",                # POPAG30
    "pob_35_39",                # POPAG35
    # Bloque 3 — Renta y hogar (800m)
    "renta_hogar_anual",        # NINCHA
    "renta_hogar_mensual",      # NINCHM
    "renta_per_capita",         # NINCCA
    "n_hogares_total",          # HHOLDS
    "tamanio_medio_hogar",      # PEOFAM
    "hogares_renta_alta",       # THINC5M (>€2589/mes)
    "hogares_renta_media_alta", # THINC4M (€2122-€2589)
    "hogares_jovenes_solos",    # TOTYOSI (<35)
    "hogares_parejas_jovenes",  # TOTYOCO (<35)
    "hogares_parejas_adultas",  # TOTADCO (35-64)
    "hogares_familias_hijos",   # TOTFUSMA (<16)
    "hogares_monoparentales",   # TOTSIFA
    # Bloque 4 — Salud financiera (800m)
    "puede_afrontar_imprevistos_pct",  # DOCAYE
    "llega_mes_con_facilidad_pct",     # HOMAEASE
    "en_riesgo_pobreza_pct",           # HORIPOYE
    # Bloque 5 — Gasto retail (800m)
    "gasto_ropa_calzado",       # SPCLOFO (señal directa Miniso)
    "gasto_ropa",               # SPCLOTH
    "gasto_calzado",            # SPFOOTW
    "gasto_cuidado_personal",   # SPPCARE
    "gasto_ocio_cultura",       # SPLEISU
    "gasto_vacaciones",         # SPLHOLI
    "gasto_restaurantes",       # SPHOTRE
    "gasto_alimentacion",       # SPFOODR
    "gasto_transporte",         # SPTRANS
    "gasto_comunicaciones",     # SPCOMM
    # Bloque 6 — Empleo y pobreza (800m)
    "tasa_desempleo",           # UNERATE
    "tasa_desempleo_jovenes",   # UNERATE24
    "empleados_por_hogar",      # TOTOCCME ⚠ valores anómalos — verificar
    "tasa_riesgo_pobreza",      # RISPORA
    # Bloque 7 — Inmobiliario (800m)
    "precio_medio_piso_compra",    # AVREAPRI (proxy riqueza zona)
    "precio_medio_piso_alquiler",  # AVPRIRENP (proxy presión comercial)
    # Bloque 8 — Canal online (800m)
    "pct_compras_online",          # PUTHINT
    "online_ropa_deporte_pct",     # PROPURSPO
    "online_ultimo_mes_pct",       # WHELAIN
    # Bloque 9 — Phase 2 (todos None ahora)
    "densidad_comercial_score",
    "indice_movilidad_peatonal",
    "dist_transporte_min_m",
    "n_competidores_500m",
    "dist_competidor_cercano_m",
]
```

### Panel PM (`src/reporting/health_check.py` + `src/reporting/geo_panel.py`)

**health_check.py — `generar_mensajes_salud()`:**
- Carga `geo_vals_loc` UNA vez (shared entre narrativa y geo panel)
- `_narrativa()` recibe `geo_vals` → genera hasta 3 insights geo al final
- `_render_pm_questions()` pasa `dias_v` (7 o 28) a los charts → filtro semana/mes correcto

**geo_panel.py — `generar_panel_geo_visual()`:**
- 4 tarjetas AIS + hasta 3 tarjetas Phase 2 (solo si tienen dato)
- Fila 1: barras captación isócrona (lg=5) + mapa carto-positron (lg=7)
- Fila 2: gasto consumidor horizontal bars (lg=7) + perfil hogar vertical bars (lg=5)
- Mapa muestra aviso "⚠ Isócronas aproximadas — sin red viaria"

### Historial de conversaciones por usuario ✅

**Almacenamiento:** `src/data/conversations/<session_id>/`
- Un fichero JSON por conversación: `<conv_id>.json` con `id, title, created_at, updated_at, location_uuid, messages[]`
- Índice ligero: `_index.json` — contiene título, timestamp y uuid de ubicación (sin mensajes)
- Máximo 50 conversaciones por usuario (las más recientes)
- Título auto-generado del primer mensaje de usuario (primeros 50 chars)

**Módulo:** `src/chatbot/history.py`
- `create_conversation(session_id, location_uuid) → conv_id`
- `update_conversation(session_id, conv_id, messages, location_uuid)` — persiste el array completo
- `list_conversations(session_id) → list[dict]` — índice ordenado por updated_at
- `load_conversation(session_id, conv_id) → dict` — carga mensajes completos para reanudar

**UI:** sidebar izquierdo en el modal del asistente (185px)
- Botón "Nueva conversación" (`id="chat-new-btn"`)
- Lista de conversaciones previas (`id="chat-conv-list"`) — cada ítem es `{"type": "conv-item", "id": conv_id}`
- Clic en ítem → restaura todos los mensajes en `chat-messages-store` y `chat-history`

**Flujo de persistencia:**
1. Usuario envía primer mensaje → `create_conversation()` → `conv_id` se guarda en `dcc.Store(id="chat-conv-id")`
2. Cada turno (user + assistant) → `update_conversation()` con el array completo de mensajes
3. Al abrir el modal → `list_conversations()` renderiza el índice en el sidebar
4. Al reanudar conversación → `load_conversation()` carga mensajes en store → llama `render_history()`

**`chat-conv-id`** — nuevo `dcc.Store` en el modal para el ID de la conversación activa (None = sin conversación activa)

### Supercalendario comercial ✅ — código correcto, notebook desactualizado
- `src/data_processing/supercalendario.py` — 9 features de calendario retail español
- `CALENDARIO_FEATURE_COLS`: `es_rebajas_invierno`, `es_rebajas_verano`, `es_black_friday_semana`, `es_cyber_monday`, `es_navidad_compras`, `es_reyes_compras`, `es_san_valentin_ventana`, `es_dia_madre_ventana`, `dias_hasta_evento_comercial`
- El notebook `laboratorio_ml.ipynb` muestra un `TypeError: Cannot compare Timestamp with datetime.date` en Fase 5. **Es output antiguo** — el archivo actual ya tiene la conversión `fecha.date()` en líneas 82-85. Basta re-ejecutar el notebook.

### PredictHQ ⚠ — sin señal en training por limitación de ventana
- `src/data_processing/predicthq_client.py` — 7 features de eventos geolocalizados
- `PHQ_FEATURE_COLS`: `phq_rank_ph`, `phq_rank_sh`, `phq_rank_ob`, `phq_att_sports`, `phq_att_concerts`, `phq_att_festivals`, `phq_att_community`
- **Problema estructural**: el tier gratuito solo cubre `hoy ± 90 días` → ventana 2026-03-02 a 2026-08-29
- El train set cubre 2025-09-16 a 2026-03-31: **~85% de las filas tienen PHQ = 0** (168 de 197 filas fuera de ventana)
- Consecuencia: correlación Pearson ≈ 0, importancia XGBoost ≈ 0, el modelo no aprende los coeficientes
- Las 14 fechas de forecast (abril 2026) sí están en ventana, pero sin coeficientes aprendidos el modelo no puede aprovecharlos

**Acceso histórico en PredictHQ:**
- Tier Developer (gratuito): ±90 días desde hoy, inamovible
- Tier de pago (contrato a medida, sin precio público): acceso histórico desde 2011-2013 según categoría
- Las categorías necesarias (sports, concerts, festivals, community, holidays) tienen datos desde 2011
- **Recomendación antes de contratar**: pedir trial con acceso histórico → reentrenar sobre el mismo split → comparar WMAPE con/sin PHQ. Si la mejora no es significativa en Málaga Muelle 1 (donde el spatial blindness es más visible), el coste no se justifica.
- Contacto: formulario en predicthq.com/pricing argumentando caso ML/forecasting retail

### Modo oscuro ❌ ELIMINADO
Eliminado en 2026-05-27. Causa raíz: ~50 `style={}` inline en Python imposibles de anular con CSS.

---

## Arquitectura clave

```
app.py
├── src/core/config.py          — app Dash, MODO_DESARROLLO
├── src/layout/main_layout.py   — serve_layout() dinámica
│   ├── src/layout/sidebar.py
│   └── src/layout/tabs/
│       ├── tab_pm.py           — Panel PM (tab principal)
│       ├── tab_bi.py           — BI comparativo
│       ├── tab_reportes.py     — Excel / PDF export
│       └── tab_ml.py           — Forecasting XGBoost
├── src/callbacks/
│   ├── filtros.py              — dropdowns, toggle sidebar
│   ├── sync_callbacks.py       — sincronización background
│   └── master_callback.py      — master_reactive_analytics()
├── src/data_ingestion/
│   ├── sincronizador.py        — Aitanna API → CSV
│   ├── esri_client.py          — fetch_enrich() real + mock
│   └── ingesta_geo.py          — ingestar_snapshot_esri()
├── src/data_processing/
│   ├── geo_enrichment.py       — get_geo_vals(), enriquecer_con_geo()
│   ├── constructor_master.py   — weather + holidays join
│   └── feature_engineering.py — lags, rolling, day-of-week
├── src/reporting/
│   ├── health_check.py         — Panel PM completo
│   └── geo_panel.py            — Sección geo (tarjetas + 4 charts)
└── src/services/
    └── ml_predictivo.py        — XGBoost con temporal join geo
```

**Data flow:** `todas_las_ubicaciones.json` → Aitanna API sync → `data/raw/dataset_*.csv` → constructor_master → feature_engineering → health_check / ml_predictivo

**Geo flow:** Esri GeoEnrichment → `esri_client.py` → `ingesta_geo.py` → `geo_features.json` → `geo_enrichment.py` → `enriquecer_con_geo(df)` en training / `generar_panel_geo_visual()` en UI

---

## Interfaces clave (no inventar)

```python
# Ingesta
ingestar_snapshot_esri(location_uuid: str, valores: dict, fecha_entrega: str) -> dict
# valores = {col: val for col in GEO_FEATURE_COLS}
# Retorna: {primera_entrega, snapshots_creados, features_registradas}

# Consulta
get_geo_vals(location_uuid, fecha=None) -> dict   # snapshot válido en fecha (None=activo)
get_geo_features_activos(location_uuid, fecha=None) -> list
enriquecer_con_geo(df, col_location_id='location_id', col_fecha='fecha') -> df

# Enriquecimiento batch
cargar_todas_ubicaciones(org_filter='Miniso', fecha_entrega='2026-05-27', dry_run=False)
# 4 ubicaciones producción: Miniso 3 + Barceló 1
```

---

## Bugs conocidos y trampas

1. **`constructor_master.py`** lee `loc.get('latitude', ...)` pero el JSON usa `lat`. Bug pre-existente.

2. **Valencia Bonaire** tenía `pob_5min=47` en el piloto anterior (2026-05-27 primero). Con el re-enriquecimiento ampliado muestra `pob_5min=8828`. El snapshot activo es el más reciente — `get_geo_vals(uuid)` devuelve el correcto.

3. **NetworkServiceArea** falla con "Internal error". Usar siempre `RingBuffer`.

4. **`src/models/anomalys.py`** no existe — `app.py` lo importa en línea 17. RuntimeError si el callback BI llega al panel de anomalías. WIP.

5. **`USE_MOCK`** en `esri_client.py` se activa automáticamente si `ESRI_KEY` no está en el entorno. Mock usa `random.Random(location_uuid)` para valores deterministas.

6. **`empleados_por_hogar` (TOTOCCME)** — valores 19/19/42/1 sospechosamente bajos. Puede ser un índice escalado, no recuento absoluto. No usar en modelo hasta verificar la unidad con la documentación AIS.

7. **Isócronas sintéticas** — `_isochrone()` en `geo_panel.py` genera círculos ondulados sin red viaria. Para Málaga Muelle 1 cubren el mar. Fix futuro: `returnGeometry=true` en la llamada Enrich.

8. **Notebook `laboratorio_ml.ipynb` — output desactualizado**: la Fase 5 (Supercalendario) muestra un `TypeError` que ya no existe en el código actual. Re-ejecutar el notebook desde cero. La Fase 6 (PredictHQ) mostrará cobertura ≈ 0 en training hasta que se consiga acceso histórico.

---

## Próximos pasos pendientes

### Prioridad alta
- [ ] **Re-ejecutar notebook** — `src/lab/laboratorio_ml.ipynb` desde cero para obtener métricas reales con Supercalendario + ver cobertura real PredictHQ.
- [ ] **Validar impacto en modelo** — comparar WMAPE antes/después de geo features en Malaga y Madrid Gran Via (picos extremos). `ml_predictivo.py` ya hace el temporal join automáticamente.
- [ ] **Verificar TOTOCCME** — consultar documentación AIS para confirmar unidad de `empleados_por_hogar`. Posiblemente excluir del training hasta confirmación.
- [ ] **Decisión PredictHQ** — pedir trial con acceso histórico a predicthq.com → reentrenar → comparar WMAPE. Si hay ganancia, contratar tier de pago. Si no, excluir `PHQ_FEATURE_COLS` del training.

### Prioridad media
- [ ] **Phase 2 features** — Places API (`n_competidores_500m`, `dist_competidor_cercano_m`) + Routing (`dist_transporte_min_m`). Endpoints: `https://places-api.arcgis.com/arcgis/rest/services/places-service/v1/places/near-point`
- [ ] **Isocronas reales** — añadir `returnGeometry=true` en el body de Enrich → polígono real basado en red de calles → almacenar GeoJSON en `geo_features.json` → renderizar en mapa.
- [ ] **Panel geo — dash-leaflet** — mapa interactivo con TileLayer Esri, marcadores y polígonos GeoJSON.
- [ ] **Reunión con Mario (Esri)** — Business Analyst, Network Analysis, POI avanzado, licencias enterprise.

### Prioridad baja
- [ ] **Escalar a los 30 locales** — `cargar_todas_ubicaciones(org_filter=None, ...)`. Coste estimado: ~3.60 USD.
- [ ] **Model registry** — serializar XGBoost con `model.save_model()`, clave `(location_uuid, zone_uuid, training_date)`.

---

## Servidor de producción
- Google Cloud, IP `34.175.22.17`, puerto 80/443
- Deploy: `/deploy` skill → git tag → push → `~/deploy.sh` en servidor via SSH
- gunicorn 4 workers, systemd, sudo passwordless
- `ESRI_KEY` debe estar en `.env` del servidor

---

## Archivos de referenciaS
- `HANDOFF_esri_peticiones_y_piloto_miniso.md` — decisiones del piloto, variables AIS, coste
- `src/data_processing/geo_enrichment.py` — fuente de verdad del esquema (47 features)
- `src/data/geo_features.json` — store actual (excluido de git por .gitignore con excepción)
