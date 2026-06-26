# Context — Handoff sesión 2026-06-26

## Estado general

Versión en producción: **v2.2.38**. Pipeline de onboarding 5 agentes completo y funcionando. Demo org Gran Vía (`Demo Madrid Gran Vía (ficticia)`) activa con coordenadas correctas (40.420797, -3.706425, CP 28013).

---

## Cambios de esta sesión

### `puertos_estado.py` — data-driven

Reescrito desde cero para eliminar hardcoding de Málaga. Ahora lee `port_authority` de `location_source_config WHERE source='puertos_estado'`. Interfaz `sync(jobs, fecha)` compatible con `sync_mensual.py`. Añadir una AP nueva = insertar fila en `location_source_config`, sin tocar código.

### `src/onboarding/_eval_core.py` — nuevo fichero (bug fix producción)

`feature_eval.py` importaba `from src.lab.eval_features import ...` — pero `src/lab/` está en `.gitignore` y no existe en producción. Solución: extraer las funciones de producción a `src/onboarding/_eval_core.py` (tracked) y actualizar el import.

### Context Scout (Agente 3) — dos cambios

1. **Strip markdown**: Claude a veces devuelve JSON envuelto en ` ```json ``` `. Añadido strip defensivo antes de `json.loads()`.
2. **Escala de directitud A→D**: catálogo actualizado para priorizar AENA (pasajeros aeropuerto) e INE pernoctaciones hoteleras (nivel A) sobre ICM y SEPE (nivel C). Criterio 7-DIRECTITUD añadido al prompt: no incluir señales D si ya hay A o B.

### Gráfico de cruceros (health_check.py)

Revertido de timeline 24 meses continuo (v2.2.37, rechazado por el usuario) a **barras agrupadas 12 meses**: eje X = Ene-Dic, dos series (año anterior ghost + año en curso tier-colored), `barmode="group"`, línea "hoy" en mes actual, leyenda de barcos separada por año.

---

## Estado de features externas

| Feature | Status global | Notas |
|---|---|---|
| `n_pasajeros_crucero_oficial` | `con_cobertura` para Málaga Muelle 1 | Puertos del Estado XLSX. Otros puertos: añadir en `location_source_config` |
| `n_pasajeros_crucero_dia` | `con_cobertura` para Málaga Muelle 1 | Puerto de Málaga API (previsión) |
| `open_meteo.*` | `active` todas ubicaciones | Clima histórico + forecast |
| Features Context Scout | `contexto` según ubicación | Sin ingestores implementados todavía |

---

## Próximos pasos

1. **AENA pasajeros** — ingestor pendiente. Context Scout ya lo descubre y registra como `contexto`. Fuente: Excel mensual de `aena.es`, sin auth, ~día 20 del mes siguiente. Feature key: `aena_pasajeros_{iata_snake}`.

2. **INE pernoctaciones hoteleras** — pendiente investigar granularidad ciudad vs. provincia. Para Gran Vía, proxy adecuado podría ser municipio Madrid. Context Scout lo registra como `ine_pernoctaciones_hoteleras_{provincia_snake}`.

3. **Hotelería Gran Vía** — el usuario preguntó por costes promedio en hotelería urbana. Fuente natural: INE Encuesta Ocupación Hotelera (ADR, RevPAR, ocupación). Granularidad: provincia/municipio, no barrio. Alternativa: STR/AirDNA si hay acceso.

4. **Más autoridades portuarias** — `puertos_estado.py` ahora es data-driven. Para añadir Barcelona, Palma, etc.: insertar en `location_source_config (location_uuid, 'puertos_estado', '{"port_authority": "<nombre exacto en XLSX>"}')`.

---

## Bugs conocidos (pre-existentes, no introducidos esta sesión)

- `src/models/anomalys.py` (`generar_panel_bi_completo`) — WIP, RuntimeError si se alcanza esa ruta en analytics.
- `src/data_processing/constructor_master.py` — lee `loc.get('latitude', ...)` pero el JSON usa `lat`. Bug pre-existente, no bloqueante (no se toca en los requests normales del panel).
