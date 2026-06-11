# HANDOFF — Supercalendario: nuevas fuentes de datos externas

## Contexto
El forecasting actual usa KPIs internos + clima + festivos (booleano). Los datos de GeoEnrichment de Esri no aportan variabilidad temporal, así que no sirven como features de forecast. Necesitamos fuentes externas con variabilidad diaria/semanal que expliquen el comportamiento del tráfico exterior.

## Fuentes a integrar (por prioridad)

### 1. Calendario comercial (determinista, implementar primero)
- Fechas fijas: rebajas invierno (7 ene - 28 feb), rebajas verano (1 jul - 31 ago), Black Friday (último viernes nov + semana), Cyber Monday, San Valentín, Día de la Madre (primer domingo mayo), Navidad (1-24 dic pre-compras), Reyes (1-5 ene)
- Estructura: columna categórica o one-hot por evento, + columna "días hasta evento" (countdown) como feature numérica
- No requiere API, es un calendario estático configurable por organización

### 2. Fiestas y eventos locales (alto impacto, scraping/manual)
- Fuentes posibles: agendas municipales (web scraping), Google Events, Eventbrite API, Predicthq.com (API de eventos con categorías y ranking de impacto — tiene free tier)
- PredictHQ es la opción más viable: API REST, filtra por localización+radio+fecha, devuelve eventos categorizados (festivals, sports, concerts, public-holidays) con campo "rank" de impacto estimado
- Estructura: para cada día y ubicación → count de eventos en radio X km + suma de ranks + categoría del evento top
- Endpoint: GET https://api.predicthq.com/v1/events/?location_around.origin={lat},{lng}&location_around.offset={radius_km}km&active.gte={date}&active.lte={date}

### 3. Índice turístico (mensual, INE)
- INE > Encuesta de ocupación hotelera > por provincia > mensual
- URL datos: https://www.ine.es/jaxiT3/Tabla.htm?t=2074
- Descargar serie CSV por provincia, interpolar a diario o usar como feature mensual
- Estructura: ocupación_hotelera_provincia (float 0-100)
- Alternativa más granular: Airdna (datos Airbnb/VRBO por zona) pero es de pago

### 4. Tráfico rodado (DGT)
- DGT publica datos de estaciones de aforo permanentes
- Portal: https://nap.dgt.es/
- Datos históricos de IMD (Intensidad Media Diaria) por estación
- Buscar la estación de aforo más cercana a cada ubicación
- Estructura: imd_diaria (int, vehículos/día) de la estación más próxima
- Limitación: los datos pueden tener delay de semanas/meses

## Estructura global del supercalendario
fecha | location_uuid | es_rebajas | evento_comercial | dias_hasta_evento | eventos_locales_count | evento_top_rank | evento_top_categoria | ocupacion_hotelera | imd_trafico

Cada fila = un día × una ubicación. Se joinea con el dataset de forecast por fecha + location_uuid.

## Plan de ejecución
1. Calendario comercial → hardcoded, sin API, implementar ya
2. PredictHQ → registrarse, obtener API key, probar endpoint, crear ingesta
3. INE ocupación → descargar CSV, mapear provincia a ubicaciones
4. DGT → explorar portal, evaluar viabilidad de automatización

## Restricciones
- Cachear todo agresivamente, no repetir llamadas
- El calendario comercial es configurable por organización (no todas las fechas aplican igual)
- Las features deben tener variabilidad diaria o al menos semanal para que aporten al modelo