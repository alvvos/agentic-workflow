# Handoff — Esri/ArcGIS: cuenta lista, anatomía de peticiones y piloto Miniso

**Fecha:** 2026-05-27
**Autor de la sesión:** Álvaro (decisiones) + asistente (research docs Esri)
**Para:** Claude Code, sobre el repo Agentic Workflow
**Continúa:** HANDOFF_esri_arcgis_setup (2026-05-23) y Session Handoff 2026-05-12 (commit `b8e7f7d`)

---

## Qué ha cambiado desde el handoff anterior

El handoff del 23/05 dejaba el setup de cuenta a medias (sin tarjeta, estrategia mock). **Eso ya está resuelto.** Estado actual:

- Cuenta **ArcGIS Location Platform** ✅
- **API key creada** y guardada en `.env` ✅
- **pay-as-you-go ACTIVADO** ✅ (la tarjeta dio "error processing card" en un primer intento, se resolvió después)
- Privilegios de la key: **GeoEnrichment + Routing + Places + Basemaps** (marcados de una vez para no regenerar el token varias veces)

**Consecuencia:** ya NO hace falta el mock. El acceso real a todos los servicios (incluido GeoEnrichment, que es premium) está operativo. El plan de desarrollo pasa de "mock" a "llamadas reales".

> Recordatorio operativo: cada vez que se modifiquen privilegios de la key, Esri **invalida el token** y hay que regenerarlo y actualizar `.env` (y cualquier despliegue: local + gunicorn). Por eso se marcaron los 4 servicios de golpe.

---

## DOS consumidores distintos de Esri en el proyecto (no confundir)

Esta sesión clarificó que hay dos usos separados de Esri, con coste y propósito distintos:

1. **El MODELO (forecasting)** → usa **GeoEnrichment** (premium, de pago). Es el objeto del handoff original: rellenar `geo_features.json` para matar la "ceguera espacial".
2. **El PANEL (visual para PMs)** → usa **Basemap + Places + Routing/Service Areas** (todos con tier gratuito). Objetivo: dar contexto espacial visual al panel de Performance Monitoring existente.

El panel (PM = Performance Monitoring) visualiza señales/visitor flow DENTRO de cada local; lo que se añade ahora es la capa de contexto EXTERIOR (catchment, competidores, demografía).

**Decisión de integración del panel:** mapa dentro del Dash actual vía **`dash-leaflet`** (wrapper Python de Leaflet, sin escribir JS). El basemap de ArcGIS entra como `dl.TileLayer` apuntando a la URL de tiles de Esri; locales como `dl.Marker`; áreas de captación y competidores como capas GeoJSON. Alternativa descartada: ArcGIS Maps SDK for JS (más potente pero implica JS embebido; `dash-arcgis-open` es comunitario, no afiliado a Esri/Plotly → soporte incierto).

---

## Anatomía de las peticiones a Esri

### Patrón común a todos los servicios de datos

```
POST al endpoint del servicio
  Header: Authorization: Bearer <TOKEN>
          (en GeoEnrichment: X-Esri-Authorization: Bearer <TOKEN>)
  Body (application/x-www-form-urlencoded):
    - QUÉ/DÓNDE: studyAreas / facilities / punto+radio
    - DETALLE:   analysisVariables / breaks / categorías
    - f=json     (o pjson para verlo formateado; sin esto devuelve HTML)
    - returnGeometry=true  (si se quiere geometría para pintar en el mapa)
```

REST sobre HTTP, normalmente POST (algunos admiten GET). El token también se acepta como parámetro `token=` en el body, pero la cabecera es lo recomendado.

### GeoEnrichment (el central para el modelo)

**Endpoint (solo enhanced):**
```
https://geoenrich.arcgis.com/arcgis/rest/services/World/geoenrichmentserver/Geoenrichment/Enrich
```

**Flujo conceptual:** determinar país → definir área (punto+buffer, drive/walk-time, o polígono) → elegir variables → consultar.

**Parámetros:**

- `studyAreas` — **único obligatorio**. Array JSON. Admite puntos XY, direcciones, polígonos propios, o geografías administrativas con nombre (códigos postales, etc.). Para nuestro caso (walk-time):
  ```json
  studyareas=[{"geometry":{"x":<lon>,"y":<lat>},
              "areaType":"NetworkServiceArea",
              "bufferUnits":"Minutes",
              "bufferRadii":[5,10,15],
              "travel_mode":"Walking"}]
  ```
  Límite: una petición de network service area / ring no puede exceder 300 millas o 300 minutos (5/10/15 min van holgados).

- `analysisVariables` — subconjunto concreto de variables. **USAR ESTE, no `dataCollections` entero** (ver sección de coste — la diferencia es ~15×). La facturación se basa solo en variables devueltas.
- `dataCollections` — paquetes predefinidos. Si no se pasa ni esto ni `analysisVariables`, devuelve KeyGlobalFacts por defecto.
- `f=json` / `returnGeometry=true` (para obtener el polígono del catchment y pintarlo) / `langCode` (`en-us`, `fr`, `ja`...).

**Respuesta:** JSON con array de features. Cada feature trae: atributos de área/geometría (OBJECTID), las variables pedidas, y metadata. Si los studyAreas se envían sin atributos, se añade un campo `id` a cada feature de salida con el índice del array de entrada → así se casa la respuesta con el input.

**Nota útil:** GeoEnrichment con `NetworkServiceArea` ya calcula el área internamente. Si se enriquece Y se quiere el polígono para el mapa, basta `returnGeometry=true` en Enrich — no hace falta llamar a Routing por separado.

### Routing / Service Areas (solo el polígono de captación, para el panel)

Endpoint del servicio de rutas. Parámetros: origen (facilities), modo (walking/driving), cortes de tiempo (`defaultBreaks: [5,10,15]`). Devuelve polígonos GeoJSON listos para pintar. Facturación: por nº de service areas devueltas (tier gratuito disponible).

### Places (competidores / POI, para el panel)

Búsqueda "nearby": punto + radio + categorías de POI. Devuelve lista de lugares con nombre, categoría, coordenadas, atributos. Facturación: por resultados de query devueltos (tier gratuito).

### Basemaps (mapa de fondo, para el panel)

No es petición de datos: son **tiles**. No se construye a mano — la librería de mapa (dash-leaflet) pide los tiles sola; solo se le pasa la URL del estilo + token. Facturación: por nº de tiles solicitados (tier gratuito).

---

## Datos de España — cobertura y variables

España tiene cobertura **por encima de la media**: dos niveles de datos.

**Básico (KeyGlobalFacts)** — global, todos los países: población total, hogares, población masc./fem., tamaño medio del hogar. Fuente fuera de EE.UU./Canadá: Michael Bauer Research (MBR).

**Avanzado (AIS) — el relevante para retail.** Dataset Advanced de España: renta, tipo de hogar, presencia de niños, lugar de nacimiento, nacionalidad, vivienda y tipo de propiedad, empleo, y **87 atributos de gasto** (consumer spending). **>650 variables en total.** Las data collections que lo contienen terminan en **"(AIS)"**.

Para retail, lo más valioso: además de renta, el **gasto de consumidor** — probablemente más señal predictiva que la población a secas.

**Granularidad España:** Comunidad / Municipio (8.162) / Provincia (52) / Secciones censales (36.071) / Distritos censales (10.512). Las 36.071 secciones censales → catchment de alta resolución.

**Frescura:** datos actualizados cada ~2 años, reflejan condiciones de ~9 meses antes de publicación. Válido para features estructurales backdatables.

**PENDIENTE antes de codificar:** los IDs exactos de variable NO son adivinables. Hay que descubrirlos una vez vía:
- `/DataCollections?f=json` filtrado a España, o
- el **Analysis Variable Finder** / **Data Collection Finder** de la doc de Esri.

Cerrar la lista exacta de variables AIS de renta/gasto/demografía para España ANTES de fijarlas en `analysisVariables`.

---

## Coste — fórmula y escenarios

**Fórmula oficial:** `atributos = nº variables solicitadas × nº áreas analizadas (studyAreas)`.
Cada variable cuenta por cada área. Con 3 áreas (5/10/15 min), cada variable se multiplica ×3.

**Precio:** ~1 $ por cada 1.000 atributos (ratio público estándar; **verificar en la calculadora de la pricing page en EUR antes de cerrar números**, pero sirve para dimensionar).

**Escenarios — OJO: la tabla de abajo asume 30 localizaciones, pero el universo de producción real son 7 (ver sección de decisión). Se deja la tabla como referencia de la fórmula; los números reales del piloto están en la sección de decisión (~0,84 $ para 7 locales × 40 var).**

| Escenario | Variables | Atributos (×3 áreas ×30 locs) | Coste |
|---|---|---|---|
| Mínimo (plan original) | 6 | 540 | ~0,54 $ |
| Medio (+ renta + gasto clave) | 15 | 1.350 | ~1,35 $ |
| Rico (dataset AIS explotado) | 40 | 3.600 | ~3,60 $ |

**Coste real del trabajo acordado (7 locales producción, escenario rico):** 40 var × 3 áreas × 7 locs = 840 atributos = **~0,84 $**.

**Conclusión:** el coste NO es la restricción en ningún escenario. La restricción es (a) elegir variables con señal real y (b) detectar qué variables vuelven vacías para España.

**Optimización crítica:**
- La palanca de coste mayor son las **áreas**, no las variables (pasar de 3 a 5 cortes ×1,67). 3 cortes suele bastar.
- Usar `analysisVariables` (subconjunto), NUNCA `dataCollections` AIS entera. Pedir la colección completa "por si acaso" = 650 var × 3 × 30 ≈ 58 $ (15× más caro). Pedir solo lo usado = los <4 $ de la tabla.

---

## DECISIÓN DE ESTA SESIÓN: enriquecer todo el universo de producción (escenario rico)

**CORRECCIÓN DE ALCANCE IMPORTANTE:** el universo de producción NO son 30 localizaciones. Son **4**: organización **Miniso (3)** + organización **Barceló (1)**. Las ~30 UUIDs pre-registradas en `geo_features.json` incluyen sitios que no están en producción. El trabajo real se acota a estas 4.

**Alcance acordado:** enriquecer las **7 localizaciones de producción** con el **escenario rico** (dataset AIS de España explotado, ~40 variables: demografía + renta + gasto retail).

**Coste:**
- 40 variables × 3 áreas walk-time × 7 localizaciones = **840 atributos** = **~0,84 $**
- Menos de un euro para enriquecer TODO el universo real con el máximo de variables.

**Por qué se va directo al escenario rico:** con solo 7 localizaciones, el coste a tope es calderilla. El argumento de "validar con pocas variables primero" pierde fuerza. Se va a por las 40 de una vez.

**Estado de la prueba ya realizada:** se tiró un primer test que consumió **144 enrichment attributes** (visible en el dashboard de Usage). Eso corresponde a 16 variables × 3 áreas × 3 locales (Miniso). Coste ~0,14 $. Las otras categorías (Basemaps/Places/Routing) marcan "No usage" — correcto: Routing usado dentro de Enrich no se factura aparte, y Basemaps/Places aún no se han llamado (son del panel, fase pendiente).

### RIESGO REAL de las 40 variables (NO es el coste)

Algunas variables AIS pueden NO devolver valor para según qué geografía española. En la prueba, de un set amplio volvieron 16 con valor. El riesgo al pedir 40 no es gastar de más, es acabar con **columnas vacías en el feature store sin saber cuáles fallaron**. Mitigación obligatoria: registrar explícitamente qué variables vuelven null/vacías por localización (ver paso de calidad abajo).

### Decisión sobre quién elige las 40 variables

**Claude Code las elige** — descubre las disponibles vía `/DataCollections?f=json` (España, collections "(AIS)") y selecciona ~40 relevantes para retail. CONDICIÓN: debe **entregar la lista con IDs exactos ANTES de ejecutar en masa**, para que Álvaro la revise/vete. La señal que alimenta el modelo de forecasting no debe quedar fijada sin revisión humana.

**Implicación en el feature store:** el escenario rico AMPLÍA `GEO_FEATURE_COLS` más allá de las 6 features originales. Hay que decidir qué variables AIS nuevas entran (renta, gasto retail, tipo de hogar, etc.), clasificarlas en backdatable vs dinámica, y reflejarlas en `geo_features.json`, `GEO_FEATURE_COLS`, `GEO_FEATURES_BACKDATABLE`, `GEO_FEATURES_DINAMICAS`.

---

## Próximos pasos para Claude Code (ENCARGO ACTUAL)

Objetivo: enriquecer las **7 localizaciones de producción** (Miniso 3 + Barceló 1) con el **escenario rico (~40 variables AIS España)**, y poder verlo.

1. **[Descubrir variables, ~0 coste]** Llamar a `/DataCollections?f=json` filtrado a España. Identificar las data collections AIS (terminan en "(AIS)"). Seleccionar ~40 variables relevantes para retail: demografía (población, hogares, tamaño/tipo de hogar, presencia de niños), **renta**, y **gasto de consumidor**. **ENTREGAR la lista con IDs exactos a Álvaro ANTES de ejecutar en masa** — no fijar la señal del modelo sin revisión.

2. **[Petición]** Usar esas variables en `analysisVariables` (NUNCA la dataCollection entera — ~15× más caro). 3 áreas walk-time: 5/10/15 min, `travel_mode: Walking`. Header `X-Esri-Authorization: Bearer <token de .env>`, `f=json`, `returnGeometry=true` si se quiere el polígono para el panel.

3. **[Recorrer producción]** Filtrar `src/data/todas_las_ubicaciones.json` por organizaciones **Miniso + Barceló** = 7 localizaciones. NO recorrer las 30 (incluyen sitios fuera de producción).

4. **[Registro de calidad — OBLIGATORIO]** Para cada variable que vuelva null/vacía en alguna localización, registrarlo explícitamente. Al final, tabla: qué variables devolvieron valor en las 7, cuáles fallaron y dónde. NO descartar variables vacías en silencio (este es el único riesgo real de ir a 40).

5. **[Ampliar feature store]** Añadir las variables nuevas a `GEO_FEATURE_COLS`, `GEO_FEATURES_BACKDATABLE`, `GEO_FEATURES_DINAMICAS` y `geo_features.json`. Clasificar cada una: estructural (backdatable a 2024-01-01) vs dinámica (desde fecha de entrega). **Confirmar las firmas reales** de `ingestar_snapshot_esri(location_uuid, valores, fecha_entrega)`, `get_geo_vals`, y el formato de `valores` en el repo ANTES de tocar nada — no inventar la interfaz.

6. **[Ingestar]** Llamar a `ingestar_snapshot_esri()` por localización (back-date automático). try-except por local: si una falla, registrarla y seguir, no abortar el lote.

7. **[Verlo]** Cerrar con `listar_estado_geo()` + la tabla de calidad del paso 4. Coste esperado: ~0,84 $ (840 atributos). Si el credit budget salta, avisar antes de seguir.

8. **[Validar modelo]** Comparar WMAPE antes/después en las 7 localizaciones (foco en las de picos extremos: Málaga Muelle 1, Madrid Gran Vía si están en el set).

9. **[Panel, en paralelo, tier gratuito]** Mapa en Dash con `dash-leaflet`: basemap ArcGIS (TileLayer) + marcadores de las 7 tiendas + polígonos catchment + competidores (Places). Esto SÍ estrenará uso de Basemaps/Places/Routing (ahora en "No usage").

10. **[Negocio]** Reunión con Mario (Esri) — pendiente de handoffs anteriores.

---

## Recordatorios / trampas conocidas

- **GeoEnrichment + Routing juntos:** las walk-time areas son service areas de RED, no buffers circulares. Requieren privilegio de Routing además del de GeoEnrichment. Ambos ya están en la key.
- **No pedir dataCollections entera** (×15 coste). Solo `analysisVariables`.
- **Token muere al cambiar privilegios** → regenerar + actualizar `.env` en todos los despliegues.
- **Referrer URLs:** la key es server-side (token en `.env`), referrer vacío es lo correcto. Poner referrer rompería las llamadas del backend.
- **Bug pre-existente** (de handoff 12/05, sin corregir): `constructor_master.py` lee `loc.get('latitude', ...)` pero el campo JSON es `lat`. Tocar al pasar por ese archivo.
- Activar returnGeometry para ver las isocronas reales.

---

## Lo que NO se ha hecho / queda pendiente

- Se hizo UNA prueba de Enrich (144 atributos, 16 var × 3 áreas × 3 locales Miniso) que validó el flujo. NO se ha hecho la carga completa de las 4 localizaciones ni con las 40 variables.
- **NO existe aún la lista concreta de las ~40 variables AIS.** Claude Code debe descubrirlas (`/DataCollections` España) y entregarlas para revisión ANTES de ejecutar (paso 1 del encargo).
- No se ha tocado el panel (Basemaps/Places/Routing en "No usage"). El mapa `dash-leaflet` es fase paralela pendiente.
- No se ha hablado con Mario (Esri) — pendiente.
- **Verificar el precio en EUR** en la calculadora de la pricing page de Esri antes de tratar las cifras de coste como definitivas (la fórmula variables×áreas está confirmada; el ratio 1$/1.000 es el público estándar).
