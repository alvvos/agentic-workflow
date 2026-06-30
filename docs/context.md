# Context — Handoff sesión 2026-06-30

## Estado general

Versión en producción: **v2.2.47**. Refactor DB-driven completo: toda la capa de render del panel utiliza la DB como única fuente de verdad para labels, colores, iconos y routing de componentes. Cero dicts hardcodeados en Python para display.

---

## Cambios de esta sesión

### Principio arquitectónico establecido

"Todo debe venir explícito de la DB. La DB está para llenarla de información y datos, no para hardcodear en el código." Este principio se aplicó como un barrido completo sobre todo el codebase.

### Refactor DB-driven — `health_check.py`

Eliminados completamente:
- `_UNIVERSAL_KEYS`, `_FEATURE_META`, `_FEATURE_FA_ICONS`, `_icon_for_feature()`
- `_ICONO_TIPO`, `_TIPO_FEATURE_KEY`, `_TIPOS_EXCLUIR`
- `_C_PRIMARY`, `_C_DARK`, `_C_MUTED` (movidos a `src/core/theme.py`)
- `_MESES_ES` (movido a `src/core/utils.py`)

Añadidos:
- `_load_feature_meta(conn, location_uuid)` — query única a `feature_registry` devuelve todo lo necesario para renderizar cualquier señal
- `_load_zone_meta(conn)` — estilos de zona desde `zone_type_registry`
- `_load_narrative_meta(conn)` — categorías/niveles desde `narrative_category_registry` + `alert_level_registry`
- `_load_norm_tipo(conn)` — `canonical_type` desde `feature_registry` reemplaza `_NORM_TIPO` Python dict

`display_mode` en `feature_registry` controla el componente de render: `'yoy'` · `'events_count'` · `'cruceros'` · `'calendario'` · `'hidden'`. Añadir señal nueva = solo INSERT en DB.

### Refactor DB-driven — `geo_panel.py`

Eliminados: `_SPATIAL_CONTEXT` (POIs hardcodeados para Madrid Gran Vía), `_SPATIAL_COLORS`, `_SPATIAL_LABELS`, `_EV_RANK_META`, `_EV_KEYS`, `_EV_ICONS`, `_EV_LABELS`, `_EV_COLOR`, `_EXT_SERIES_META`.

Añadido: `_load_geo_meta(conn)` — query a `feature_registry` + `poi_category_registry` + `canonical_type`. POIs leídos de `location_pois` DB.

### Módulos compartidos nuevos

- `src/core/theme.py` — `C_PRIMARY`, `C_SUCCESS`, `C_DANGER`, `C_AMBER`, `C_DARK`, `C_MUTED`, `C_GRID`, `CFG_GRAPH`, `PALETA_PM`
- `src/core/utils.py` — `MESES_ES`, `MESES_ES_FULL`, `DIAS_SEMANA_ES`, `DIAS_CORTO`

### Nuevas tablas en DB (migración `_migrate_registries`)

| Tabla | Propósito |
|---|---|
| `poi_category_registry` | Display metadata de categorías de POIs |
| `zone_type_registry` | Estilos por tipo de zona (tienda/caja/exterior) |
| `narrative_category_registry` | Categorías del acordeón narrativo |
| `alert_level_registry` | Niveles de alerta (ok/warning/critical) |

Columnas nuevas en `feature_registry`: `label`, `sublabel`, `color`, `icon_cls`, `agg_fn`, `display_mode`, `canonical_type`.

`canonical_type` registrado para: `tm_concierto→concierto`, `tm_festival→festival`, `tm_deportivo→deportivo`, `concierto_wizink→concierto`, `estreno_callao→concierto`, `festival_madrid→festival`, `manifestacion_gran_via→evento_municipal`, `partido_deportivo→deportivo`.

### Refactor `admin_pois.py`

Eliminados `_CAT_LABELS`, `_CAT_ICONS`, `_CAT_COLORS`. Añadido `_load_poi_categories(conn)` desde `poi_category_registry`.

### Refactor `feature_router.py`

Eliminado `_MALAGA_KEYS = {"malaga", "málaga"}` city name matching. Cruceros ahora activados por `location_source_config WHERE source='cruceros' AND activo=TRUE`.

### Tooltips DB-driven

Tooltips en secciones `ev_rank`, `cruceros` y `eventos` del panel PM provienen de `feature_registry.notas`. No hay `_FEATURE_TOOLTIPS` Python dict. Para añadir/editar un tooltip: `UPDATE feature_registry SET notas='...' WHERE feature_key='...'`.

---

## Estado de features externas

| Feature | Status global | Notas |
|---|---|---|
| `n_pasajeros_crucero_oficial` | `con_cobertura` para Málaga Muelle 1 | Puertos del Estado XLSX |
| `n_pasajeros_crucero_dia` | `con_cobertura` para Málaga Muelle 1 | Puerto de Málaga API |
| `open_meteo.*` | `active` todas ubicaciones | Clima histórico + forecast |
| `afluencia_metro_gran_via` | `contexto` para Madrid Gran Vía | Metro Madrid Excel ✅ |
| `afluencia_metro_callao` | `contexto` para Madrid Gran Vía | Metro Madrid Excel ✅ |
| Features `events_count` | display_mode solo, no en feature_flags | `concierto`, `festival`, `deportivo`, `evento_municipal` |

---

## Próximos pasos

1. **Poblar registros de display** — `zone_type_registry`, `narrative_category_registry`, `alert_level_registry` están creadas con DDL pero vacías. Rellenar con los valores correctos via SQL o panel admin.

2. **Conectar ingestores mensual a `sync_mensual.py`** — añadir `metro_madrid` (y los stubs que se vayan completando) a `_build_ingestores()`.

3. **Verificar estación "Sol"** en Metro Madrid Excel — puede ser "Sol (Metro)" o variante. Investigar nombre exacto de columna.

4. **INE pernoctaciones hoteleras** — stub `ine_eoh.py` listo. Investigar granularidad ciudad vs. provincia.

5. **Validar impacto geo en modelo** — comparar WMAPE antes/después de primeras entregas Esri en Málaga y Madrid Gran Vía.

---

## Bugs conocidos

- `src/models/anomalys.py` (`generar_panel_bi_completo`) — WIP, RuntimeError si se alcanza esa ruta en analytics.
- `src/data_processing/constructor_master.py` — lee `loc.get('latitude', ...)` pero el JSON usa `lat`. Bug pre-existente, no bloqueante.
- **Tenerife CC Nivaria** — sin coordenadas en `dim_ubicaciones`. Excluida de todo prefetch.
