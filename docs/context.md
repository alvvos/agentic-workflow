# Context — Handoff sesión 2026-06-30

## Estado general

Versión en producción: **v2.2.46**. Pipeline de onboarding 5 agentes completo y funcionando. Miniso Madrid Gran Vía con datos de metro operativos en "señal de contexto". Nuevas tablas `location_pois` y `location_source_config` en DB.

---

## Cambios de esta sesión

### Bug fix: `_GV_UUID` apuntaba a UUID incorrecto (`store.py`, `geo_panel.py`)

`_GV_UUID` tenía el UUID de "Showroom" (`faf7d203-...`) en lugar de Madrid Gran Vía (`251e7f40-95c7-4678-aa48-df1b90e3461c`). Corregido en `store.py` (líneas 746 y 782) y en `geo_panel.py` (dict `_SPATIAL_CONTEXT`). Además se migró en DB los 1460 rows de `store_features_ext` ya escritos bajo el UUID incorrecto.

### Bug fix: señal de contexto no mostraba features `status='contexto'` (`health_check.py`)

`_render_senal_contexto_modal()` tenía `AND f.status = 'active'` en el JOIN con `feature_flags`. Las features de metro tienen `status = 'contexto'` deliberadamente (visibles en panel, excluidas del modelo). Cambiado a `AND f.status IN ('active', 'contexto')`. Ahora los datos de metro aparecen en el acordeón.

### Mapa de isócronas más grande (`geo_panel.py`)

Altura del mapa en `generar_mapa_contexto()` aumentada de `340px` a `520px`.

### Stubs ingestores mensuales — `src/data_ingestion/mensual/`

Directorio nuevo con ingestores mensuales de señales de movilidad/turismo. `metro_madrid.py` es funcional (descarga Excel Metro Madrid, parsea validaciones por estación, escribe en `store_features_ext`). El resto son stubs documentados con catálogo y contrato de `location_source_config`:

| Fichero | Fuente | Estado |
|---|---|---|
| `metro_madrid.py` | Excel validaciones Metro Madrid | ✅ Funcional |
| `aena.py` | Excel pasajeros aeropuerto AENA | 🔲 Stub |
| `cercanias_renfe.py` | CSV viajeros Cercanías RENFE | 🔲 Stub |
| `metro_barcelona.py` | TMB open data | 🔲 Stub |
| `metro_bilbao.py` | Metro Bilbao open data | 🔲 Stub |
| `metro_sevilla.py` | Metro Sevilla open data | 🔲 Stub |
| `metro_valencia.py` | Metrovalencia open data | 🔲 Stub |
| `ine_eoh.py` | INE Encuesta Ocupación Hotelera | 🔲 Stub |

Todos exponen `sync(jobs, fecha)` y `run(location_uuid, ...)` para integrarse con `sync_mensual.py`.

### docker-compose: adminer → pgweb

`docker-compose.yml` reemplaza el contenedor Adminer por pgweb (interfaz web PostgreSQL más ligera, puerto 8081). Alias `pgweb-tunnel` disponible en `~/.config/zsh/.zshrc`.

### Pre-commit: ruff excluye `src/lab/`

`.pre-commit-config.yaml` ahora excluye `src/lab/` del hook ruff (E402/E701 en celdas Jupyter no aplican). Black sí sigue actuando sobre lab/.

---

## Estado de features externas

| Feature | Status global | Notas |
|---|---|---|
| `n_pasajeros_crucero_oficial` | `con_cobertura` para Málaga Muelle 1 | Puertos del Estado XLSX. Otros puertos: añadir en `location_source_config` |
| `n_pasajeros_crucero_dia` | `con_cobertura` para Málaga Muelle 1 | Puerto de Málaga API (previsión) |
| `open_meteo.*` | `active` todas ubicaciones | Clima histórico + forecast |
| `afluencia_metro_gran_via` | `contexto` para Madrid Gran Vía | Metro Madrid Excel. Datos disponibles en señal de contexto ✅ |
| `afluencia_metro_callao` | `contexto` para Madrid Gran Vía | Metro Madrid Excel ✅ |
| Features Context Scout | `contexto` según ubicación | Stubs implementados; ingestores pendientes de conectar a sync_mensual |

---

## Próximos pasos

1. **Conectar ingestores mensual a `sync_mensual.py`** — añadir los stubs funcionales (`metro_madrid`, etc.) a `_build_ingestores()` en `sync_mensual.py`. Primero completar el stub AENA.

2. **Verificar estación "Sol" en Metro Madrid Excel** — durante la ingesta, "Sol" no matchó en el Excel. Investigar el nombre exacto de la columna (puede ser "Sol (Metro)" o similar).

3. **INE pernoctaciones hoteleras** — pendiente investigar granularidad ciudad vs. provincia. Stub `ine_eoh.py` creado. Para Gran Vía, proxy adecuado podría ser municipio Madrid.

4. **Más autoridades portuarias** — `puertos_estado.py` es data-driven. Para añadir Barcelona, Palma, etc.: insertar en `location_source_config (location_uuid, 'puertos_estado', '{"port_authority": "<nombre exacto en XLSX>"}')`.

---

## Bugs conocidos

- `src/models/anomalys.py` (`generar_panel_bi_completo`) — WIP, RuntimeError si se alcanza esa ruta en analytics.
- `src/data_processing/constructor_master.py` — lee `loc.get('latitude', ...)` pero el JSON usa `lat`. Bug pre-existente, no bloqueante.
- **Tenerife CC Nivaria** — sin coordenadas en `dim_ubicaciones`. Excluida de todo prefetch.
