# Guía Completa: Variables Exógenas para Enriquecimiento de Informes PDF

**Fecha del análisis:** 2026-07-30
**Base de datos:** PostgreSQL en `localhost:5433` (reporting)
**Contacto:** Análisis realizado para dashboard Agentic Workflow

---

## 1. RESUMEN EJECUTIVO

La base de datos dispone de **4 categorías principales** de variables exógenas que pueden enriquecer los informes PDF con insights contextuales:

| Categoría | Tablas | Variables | Cobertura Temporal | Cobertura Espacial |
|-----------|--------|-----------|-------------------|-------------------|
| **Clima** | `valores_señales`, `señales` | llueve, temp_max, temp_min | 2025-01-01 → 2026-07-28 | 6 ubicaciones |
| **Turismo/Eventos** | `eventos`, `valores_señales` | Escalas cruceros, pasajeros | 2025-07-31 → 2026-12-31 | 1 ubicación (Málaga) |
| **Contexto Geoespacial** | `snapshots_geo` | 57 variables (demogr., renta, empleo, gasto) | Actualizado 2026-07-30 | 7-9 ubicaciones |
| **POIs / Densidad Comercial** | `puntos_interes`, `categorias_poi` | 1.742 POIs en 8 categorías | Actualizado 2026-07-30 | 9 ubicaciones |

---

## 2. FUENTES DE DATOS

### 2.1 Tabla: `señales` (Catálogo)
Metadatos de todas las señales externas disponibles.

```sql
SELECT
    señal_id,
    fuente,
    categoria,
    label,
    status,
    tipo_canonico
FROM señales
ORDER BY categoria, señal_id;
```

**Fuentes integradas:**
- `open_meteo`: Datos meteorológicos (OpenMeteo API)
- `puerto_malaga`: Escalas de cruceros (puerto de Málaga)
- `puertos_estado`: Datos oficiales de puertos españoles
- `esri_places`: Contexto geoespacial (Esri)
- `google_places`: POIs (Google Places API)
- `manual`: Ingesta manual

### 2.2 Tabla: `valores_señales` (Series temporales)
Series diarias de señales externas por ubicación.

**Estructura:**
```
fecha (date) | ubicacion_id (text) | señal_id (text) | valor (float) | ingerido_en (timestamp)
```

**Señales disponibles:**
- **Clima:** `llueve`, `temp_max`, `temp_min`
- **Turismo:** `n_pasajeros_crucero_oficial`, `n_pasajeros_crucero_dia`
- **Contexto:** `esri_places_vaguada`, `google_places_pois_gran_via` (incompleto)

### 2.3 Tabla: `eventos` (Eventos puntuales)
Calendario de eventos turísticos y laborales.

**Estructura:**
```
id (uuid) | evento_key (text) | fecha_inicio | fecha_fin | fuente (text) |
ubicacion_id (text) | metadata (jsonb)
```

**Eventos existentes:**
- Escalas de cruceros (524 eventos, 2025-07-31 a 2026-12-31)
- Metadata incluye: barco, terminal, número de pasajeros

**Ejemplo de metadata:**
```json
{
  "barco": "AIDAMAR ITALIA AIDA CRUISES",
  "terminal": "",
  "n_pasajeros": 2686
}
```

### 2.4 Tabla: `snapshots_geo` (Features geoespaciales estáticas)
Datos demográficos y de contexto geoespacial por ubicación.

**Estructura:**
```
ubicacion_id (text) | señal_id (text) | valor (float) | actualizado_en (timestamp)
```

**57 variables disponibles, organizadas en:**

#### Población (Isócronas)
- `poblacion_5min`, `poblacion_10min`, `poblacion_15min`
- `densidad_poblacion` (hab/km²)

#### Demografía (18 grupos etarios)
- `pob_0_4`, `pob_5_9`, `pob_10_14`, `pob_15_19`, `pob_20_24`, `pob_25_29`
- `pob_30_34`, `pob_35_39`, `pob_40_44`, `pob_45_49`, `pob_50_54`, `pob_55_59`
- `pob_60_64`, `pob_65_69`, `pob_70_74`, `pob_75_79`, `pob_80_84`, `pob_85_plus`

#### Renta y Poder de Compra (7 variables)
- `renta_hogar_anual`, `renta_per_capita`
- `indice_poder_compra` (100 = nacional, > 150 = alto, < 100 = bajo)
- `hogares_renta_alta`, `hogares_renta_media_alta`, `n_hogares_total`

#### Empleo (4 variables)
- `tasa_desempleo` (%), `tasa_desempleo_jovenes` (%)
- `en_riesgo_pobreza_pct`, `trabajadores_zona`

#### Gasto de Consumo (8 variables)
- `gasto_alimentacion`, `gasto_cuidado_personal`
- `gasto_restaurantes`, `gasto_transporte`, `gasto_vacaciones`, `gasto_ocio_cultura`
- `hogares_familias_hijos`, `hogares_jovenes_solos`, `hogares_parejas_jovenes`

#### Actividad Online (3 variables)
- `online_ultimo_mes_pct`, `online_ropa_deporte_pct`, `pct_compras_online`

#### POIs / Infraestructura (8 variables)
- `n_atracciones`, `n_competidores`, `n_restauracion`, `n_anclas`
- `n_nodos_transporte`, `gasto_transporte`, `gasto_vacaciones`

### 2.5 Tabla: `puntos_interes` (POIs con categorización)
1.742 puntos de interés catalogados alrededor de cada ubicación.

**Estructura:**
```
id | org_id | ubicacion_id | nombre | lat | lon | categoria |
valor_relativo | radio_m | isocrona_minutos | isocrona_geojson | fuente | activo
```

**Categorías (8 tipos):**
| Categoría | Label | Cantidad | Icono |
|-----------|-------|----------|-------|
| `ancla` | Tienda ancla / gran superficie | 135 | fa-building |
| `competitor` | Competidor | 511 | fa-store |
| `restauracion` | Restauración | 375 | fa-utensils |
| `tourist_poi` | Polo turístico | 287 | fa-landmark |
| `metro` | Metro / Transporte | 211 | fa-subway |
| `event_venue` | Sala de eventos | 132 | fa-theater-masks |
| `transporte_bus` | Bus / Parada | 10 | fa-bus |
| `otro` | Otro | 81 | fa-map-pin |

---

## 3. CONSULTAS SQL RECOMENDADAS

### 3.1 Enriquecimiento por Clima

```sql
-- Obtener datos de clima para un período y ubicación
SELECT
    v.fecha,
    s.label as variable,
    v.valor,
    CASE
        WHEN v.señal_id = 'llueve' AND v.valor = 1 THEN 'Lluvia'
        WHEN v.señal_id = 'llueve' AND v.valor = 0 THEN 'Sin lluvia'
        ELSE NULL
    END as descripcion
FROM valores_señales v
JOIN señales s ON v.señal_id = s.señal_id
WHERE v.ubicacion_id = ?
    AND v.fecha BETWEEN ? AND ?
    AND v.señal_id IN ('llueve', 'temp_max', 'temp_min')
ORDER BY v.fecha DESC, v.señal_id;
```

### 3.2 Eventos Turísticos en Período de Visitas

```sql
-- Detectar escalas de cruceros alineadas con fecha de visita
SELECT
    e.evento_key,
    e.fecha_inicio,
    e.fecha_fin,
    e.metadata->>'barco' as barco,
    (e.metadata->>'n_pasajeros')::INT as n_pasajeros,
    v.total_visitas,
    ROUND(
        (v.total_visitas - avg_visitas_histórico) / avg_visitas_histórico * 100, 2
    ) as pct_variación
FROM eventos e
LEFT JOIN visitas v ON
    e.ubicacion_id = v.ubicacion_id
    AND v.fecha = e.fecha_inicio
LEFT JOIN (
    SELECT ubicacion_id, AVG(total_visitas) as avg_visitas_histórico
    FROM visitas
    WHERE fecha < ?
    GROUP BY ubicacion_id
) hist ON e.ubicacion_id = hist.ubicacion_id
WHERE e.ubicacion_id = ?
    AND e.fecha_inicio BETWEEN ? AND ?
ORDER BY e.fecha_inicio DESC;
```

### 3.3 Contexto Geoespacial de la Ubicación

```sql
-- Obtener todas las variables geoespaciales para una ubicación
SELECT
    CASE
        WHEN señal_id LIKE 'poblacion%' THEN 'Población'
        WHEN señal_id LIKE 'pob_%' THEN 'Demografía'
        WHEN señal_id LIKE 'renta%' THEN 'Renta'
        WHEN señal_id LIKE 'indice%' THEN 'Índices'
        WHEN señal_id LIKE 'tasa%' THEN 'Empleo'
        WHEN señal_id LIKE 'gasto%' THEN 'Gasto'
        WHEN señal_id LIKE 'online%' THEN 'Online'
        WHEN señal_id LIKE 'n_%' THEN 'Infraestructura'
        ELSE 'Otros'
    END as categoria,
    señal_id,
    valor
FROM snapshots_geo
WHERE ubicacion_id = ?
ORDER BY categoria, señal_id;
```

### 3.4 Análisis de Penetración y Potencial de Mercado

```sql
-- Calcular penetración de mercado vs. población isócrona
WITH visitas_resumen AS (
    SELECT
        ubicacion_id,
        COUNT(DISTINCT fecha) as dias_operativos,
        SUM(total_visitas) as total_visitas,
        AVG(total_visitas) as promedio_diario
    FROM visitas
    WHERE ubicacion_id = ?
        AND fecha BETWEEN ? AND ?
    GROUP BY ubicacion_id
)
SELECT
    u.nombre,
    vr.promedio_diario,
    CAST(sg_pop.valor AS INT) as poblacion_5min,
    ROUND((vr.promedio_diario / sg_pop.valor) * 100, 2) as penetracion_pct,
    CAST(sg_poder.valor AS INT) as indice_poder_compra,
    CASE
        WHEN sg_poder.valor > 150 THEN 'Alto'
        WHEN sg_poder.valor >= 100 THEN 'Medio'
        ELSE 'Bajo'
    END as poder_compra_categoria
FROM visitas_resumen vr
JOIN ubicaciones u ON vr.ubicacion_id = u.ubicacion_id
LEFT JOIN snapshots_geo sg_pop ON
    vr.ubicacion_id = sg_pop.ubicacion_id
    AND sg_pop.señal_id = 'poblacion_5min'
LEFT JOIN snapshots_geo sg_poder ON
    vr.ubicacion_id = sg_poder.ubicacion_id
    AND sg_poder.señal_id = 'indice_poder_compra'
WHERE vr.ubicacion_id = ?;
```

### 3.5 Densidad de Competencia

```sql
-- Contabilizar POIs por categoría para identificar concentración comercial
SELECT
    cp.categoria,
    cp.label,
    COUNT(pi.id) as cantidad,
    ROUND(COUNT(pi.id)::FLOAT /
        (SELECT COUNT(*) FROM puntos_interes WHERE ubicacion_id = ?) * 100, 1) as pct_total
FROM puntos_interes pi
LEFT JOIN categorias_poi cp ON pi.categoria = cp.categoria
WHERE pi.ubicacion_id = ?
GROUP BY pi.categoria, cp.label
ORDER BY cantidad DESC;
```

### 3.6 Enriquecimiento completo de visitas con contexto

```sql
-- Query master que une todas las dimensiones para un informe integral
SELECT
    -- Identificación
    v.fecha,
    u.nombre as ubicacion,

    -- Visitas
    v.total_visitas,
    v.visitantes_unicos,
    v.tiempo_estancia_min,

    -- Clima (día de la visita)
    ROUND(COALESCE(vs_tmax.valor, 0)::NUMERIC, 1) as temp_max_c,
    ROUND(COALESCE(vs_tmin.valor, 0)::NUMERIC, 1) as temp_min_c,
    CASE WHEN COALESCE(vs_llueve.valor, 0) = 1 THEN 'Sí' ELSE 'No' END as llueve,

    -- Eventos turísticos
    CASE WHEN e.evento_key IS NOT NULL THEN 1 ELSE 0 END as hay_evento,
    e.evento_key,
    COALESCE((e.metadata->>'n_pasajeros')::INT, 0) as n_pasajeros_crucero,

    -- Contexto estático
    CAST(sg_pop5.valor AS INT) as poblacion_5min,
    ROUND((v.total_visitas / NULLIF(sg_pop5.valor, 0))::NUMERIC * 100, 2) as penetracion_pct,
    CAST(sg_comp.valor AS INT) as n_competidores,
    CAST(sg_poder.valor AS INT) as indice_poder_compra

FROM visitas v
JOIN ubicaciones u ON v.ubicacion_id = u.ubicacion_id
LEFT JOIN valores_señales vs_tmax ON
    v.ubicacion_id = vs_tmax.ubicacion_id
    AND v.fecha = vs_tmax.fecha
    AND vs_tmax.señal_id = 'temp_max'
LEFT JOIN valores_señales vs_tmin ON
    v.ubicacion_id = vs_tmin.ubicacion_id
    AND v.fecha = vs_tmin.fecha
    AND vs_tmin.señal_id = 'temp_min'
LEFT JOIN valores_señales vs_llueve ON
    v.ubicacion_id = vs_llueve.ubicacion_id
    AND v.fecha = vs_llueve.fecha
    AND vs_llueve.señal_id = 'llueve'
LEFT JOIN eventos e ON
    v.ubicacion_id = e.ubicacion_id
    AND v.fecha BETWEEN e.fecha_inicio AND e.fecha_fin
LEFT JOIN snapshots_geo sg_pop5 ON
    v.ubicacion_id = sg_pop5.ubicacion_id
    AND sg_pop5.señal_id = 'poblacion_5min'
LEFT JOIN snapshots_geo sg_comp ON
    v.ubicacion_id = sg_comp.ubicacion_id
    AND sg_comp.señal_id = 'n_competidores'
LEFT JOIN snapshots_geo sg_poder ON
    v.ubicacion_id = sg_poder.ubicacion_id
    AND sg_poder.señal_id = 'indice_poder_compra'
WHERE v.ubicacion_id = ?
    AND v.fecha BETWEEN ? AND ?
ORDER BY v.fecha DESC;
```

---

## 4. EJEMPLOS DE INSIGHTS AUTOMÁTICOS

### 4.1 Climat Impact
**Patrón detectado:** Lluvia + caída de visitas

```sql
WITH clima_visitas AS (
    SELECT
        v.fecha,
        v.total_visitas,
        vs_llueve.valor as llueve,
        LAG(v.total_visitas, 7) OVER (ORDER BY v.fecha) as visitas_semana_anterior
    FROM visitas v
    LEFT JOIN valores_señales vs_llueve ON
        v.ubicacion_id = vs_llueve.ubicacion_id
        AND v.fecha = vs_llueve.fecha
        AND vs_llueve.señal_id = 'llueve'
    WHERE v.ubicacion_id = ?
)
SELECT
    fecha,
    CASE WHEN llueve = 1 THEN 'Lluvia' ELSE 'Sin lluvia' END as condicion,
    total_visitas,
    visitas_semana_anterior,
    ROUND(((total_visitas - visitas_semana_anterior) / NULLIF(visitas_semana_anterior, 0)) * 100, 1) as pct_cambio
FROM clima_visitas
WHERE llueve = 1 AND total_visitas < visitas_semana_anterior * 0.8
ORDER BY fecha DESC
LIMIT 10;
```

**Insight automático generado:**
> "El martes 15/01 hubo lluvia, y se registró una caída de 22% en visitas (3.200 vs promedio de 4.100) en comparación con la semana anterior. La lluvia podría haber impactado negativamente en la afluencia exterior."

### 4.2 Tourism Events
**Patrón detectado:** Escalas de cruceros + aumento de visitas

```sql
SELECT
    e.fecha_inicio,
    (e.metadata->>'barco') as barco,
    (e.metadata->>'n_pasajeros')::INT as pasajeros,
    v.total_visitas,
    ROUND(((v.total_visitas - avg_normal) / NULLIF(avg_normal, 0)) * 100, 1) as pct_incremento
FROM eventos e
LEFT JOIN visitas v ON e.ubicacion_id = v.ubicacion_id AND v.fecha = e.fecha_inicio
CROSS JOIN (
    SELECT AVG(total_visitas) as avg_normal
    FROM visitas
    WHERE ubicacion_id = ? AND fecha < ?
) baseline
WHERE e.ubicacion_id = ? AND e.fecha_inicio BETWEEN ? AND ?
ORDER BY pasajeros DESC;
```

**Insight automático generado:**
> "El 28/12 estuvo la escala del crucero 'COSTA FASCINOSA' con 3.800 pasajeros, y se registraron 6.200 visitas (+51% vs promedio). La actividad turística influyó positivamente en la afluencia."

### 4.3 Commercial Density
**Patrón detectado:** Alta concentración de competidores → penetración baja

```sql
SELECT
    u.nombre,
    COUNT(DISTINCT CASE WHEN pi.categoria = 'competitor' THEN pi.id END) as n_competidores,
    COUNT(DISTINCT CASE WHEN pi.categoria = 'restauracion' THEN pi.id END) as n_restaurantes,
    ROUND(vr.penetracion_pct, 2) as penetracion_actual,
    CASE
        WHEN n_competidores > 70 THEN 'ALTA (> 70)'
        WHEN n_competidores > 40 THEN 'MEDIA (40-70)'
        ELSE 'BAJA (< 40)'
    END as densidad_competencia
FROM ubicaciones u
LEFT JOIN puntos_interes pi ON u.ubicacion_id = pi.ubicacion_id
CROSS JOIN (
    SELECT
        ubicacion_id,
        ROUND((AVG(total_visitas) /
            MAX(sg.valor) FILTER (WHERE sg.señal_id = 'poblacion_5min')) * 100, 2) as penetracion_pct
    FROM visitas v
    LEFT JOIN snapshots_geo sg ON v.ubicacion_id = sg.ubicacion_id
    WHERE fecha BETWEEN ? AND ?
    GROUP BY ubicacion_id
) vr
WHERE u.ubicacion_id = vr.ubicacion_id
GROUP BY u.nombre, vr.penetracion_pct;
```

**Insight automático generado:**
> "La zona de Gran Vía cuenta con 80 competidores cercanos y 43 restaurantes, lo que fragmenta la afluencia. La penetración actual es 24.9%, comparativamente baja para un índice de poder de compra alto (176)."

### 4.4 Demographic Opportunity
**Patrón detectado:** Alto poder de compra pero baja penetración

```sql
SELECT
    u.nombre,
    CAST(sg_poder.valor AS INT) as indice_poder_compra,
    CAST(sg_pop5.valor AS INT) as poblacion_5min,
    ROUND(vr.penetracion_pct, 2) as penetracion_actual,
    CAST(sg_joven.valor AS INT) as poblacion_15_29,
    ROUND((sg_joven.valor / sg_pop5.valor) * 100, 1) as pct_joven,
    CASE
        WHEN sg_poder.valor > 150 AND vr.penetracion_pct < 0.15 THEN 'ALTO POTENCIAL'
        WHEN sg_poder.valor > 150 THEN 'BUENO'
        ELSE 'LIMITADO'
    END as diagnostico
FROM ubicaciones u
LEFT JOIN snapshots_geo sg_poder ON u.ubicacion_id = sg_poder.ubicacion_id AND sg_poder.señal_id = 'indice_poder_compra'
LEFT JOIN snapshots_geo sg_pop5 ON u.ubicacion_id = sg_pop5.ubicacion_id AND sg_pop5.señal_id = 'poblacion_5min'
LEFT JOIN snapshots_geo sg_joven ON u.ubicacion_id = sg_joven.ubicacion_id AND sg_joven.señal_id = 'pob_15_29'
CROSS JOIN (
    SELECT
        ubicacion_id,
        ROUND((SUM(total_visitas) /
            (90 * MAX(sg.valor) FILTER (WHERE sg.señal_id = 'poblacion_5min'))) * 100, 2) as penetracion_pct
    FROM visitas v
    LEFT JOIN snapshots_geo sg ON v.ubicacion_id = sg.ubicacion_id
    WHERE fecha >= CURRENT_DATE - INTERVAL '90 days'
    GROUP BY ubicacion_id
) vr
WHERE u.ubicacion_id = ? AND vr.ubicacion_id = u.ubicacion_id;
```

**Insight automático generado:**
> "La ubicación está en una zona con alto poder de compra (índice 176) y población joven predominante (65% entre 15-29 años = 11.148 personas). Con una penetración actual del 24.9%, existe oportunidad de incremento a 35-40% mediante estrategias orientadas a millennials."

---

## 5. LIMITACIONES Y CONSIDERACIONES

### 5.1 Cobertura Espacial
- **Clima:** Solo 6 ubicaciones disponen de datos meteorológicos
- **Cruceros:** Solo 1 ubicación (Málaga)
- **Contexto geoespacial:** 7-9 ubicaciones (varía según variable)
- **POIs:** 9 ubicaciones

### 5.2 Cobertura Temporal
- **Clima:** 2025-01-01 a 2026-07-28 (datos históricos disponibles)
- **Cruceros:** Predicciones hasta 2026-12-31
- **Contexto geo:** Actualizado trimestralmente (última: 2026-07-30)
- **POIs:** Actualizado anualmente

### 5.3 Calidad de Datos
- Variables geoespaciales (`snapshots_geo`) pueden contener valores atípicos
- Eventos de cruceros: Metadata incompleta en algunos casos (terminal vacía)
- POIs: Algunos con isócronas sin completar (campo `isocrona_minutos` NULL)
- Status "incompleto" en Google Places y ESRI (cobertura parcial)

### 5.4 Interpretación
- Los insights automáticos requieren contextualización humana
- Correlación no implica causalidad (lluvia ↛ menos visitas siempre)
- Factores externos no capturados: Promociones, eventos locales puntuales, problemas técnicos

---

## 6. PRÓXIMAS MEJORAS SUGERIDAS

1. **Integrar datos de festividades españolas** en tabla `eventos` (Navidad, Reyes, etc.)
2. **Enriquecer metadata de eventos** con geolocalización exacta (lat/lon)
3. **Completar isócronas de POIs** (calcular tiempos de acceso con Esri)
4. **Datos de tráfico** por hora (si están disponibles en próximas ingestas)
5. **Correlación automática** entre variables: ML para detectar causas de anomalías

---

## Contacto y Documentación

Para consultas sobre estas variables o necesidad de nuevas ingestas:
- Base de datos: `localhost:5433` (env: `.env`)
- Código de análisis: Este script en `/home/alvvos/Proyectos/agentic-workflow/`
- Última sincronización: 2026-07-30 10:45 UTC
