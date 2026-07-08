# TFG — Predicción de afluencia retail con XGBoost
## Handoff para orientación con IA

Este documento describe el sistema de predicción de visitas diarias a tiendas físicas
implementado en un proyecto real de analytics retail. Se usa como punto de partida para
definir el tema y alcance de un TFG de estadística en el grado de Matemáticas.

---

## Contexto del problema

Miniso España tiene sensores de conteo de personas en 3 tiendas (Madrid Gran Vía,
Málaga Muelle 1, Valencia Bonaire). Cada día se registra el número de visitantes por
zona dentro de cada tienda (planta baja, planta alta, zona de cajas, etc.).

El objetivo es predecir $y_{t+h}$ — visitantes el día $t+h$ — dado el histórico hasta $t$
y covariables exógenas conocidas (tiempo meteorológico previsto, festivos, eventos).
El horizonte de predicción habitual es $H = 30$ días.

Los datos están disponibles desde enero de 2024, lo que da aproximadamente
900 observaciones diarias por zona en el momento de redactar este documento.

---

## Pipeline implementado

### 1. Feature engineering

**Autocorrelación (lags y medias móviles)**

$$\ell_{k,t} = y_{t-k}, \quad k \in \{1, 7, 14\}$$

$$\bar{y}_{w,t} = \frac{1}{w}\sum_{i=1}^{w} y_{t-i}, \quad w \in \{7, 14\}$$

$$\sigma_{7,t} = \sqrt{\frac{1}{7}\sum_{i=1}^{7}(y_{t-i} - \bar{y}_{7,t})^2}$$

El lag-7 captura la periodicidad semanal (el mismo día de la semana anterior).
La desviación estándar sobre la última semana actúa como proxy de volatilidad reciente.

**Meteorología** (Open-Meteo API, histórico completo disponible)

Variables continuas: $T_{max}$, $T_{min}$, precipitación. Variables binarizadas por umbrales
de dominio: `mucho_calor` ($T_{max} \geq 32°C$), `mucho_frio` ($T_{min} \leq 8°C$),
`clima_ideal` ($18 \leq T_{max} \leq 26$ y sin lluvia). Interacción: `finde_lluvioso` =
`es_finde` × `llueve`.

La binarización es una decisión de dominio: el comportamiento de compra cae
abruptamente por encima de 32°C, no de forma lineal. Esto merece contraste
estadístico formal (¿mejora la binarización sobre la variable continua en CV?).

**Calendario** (generado internamente)

`dia_semana` (0–6), `dia_mes`, `mes`, `quincena`, `es_finde`, `es_festivo`,
`vispera_festivo`, y ventanas comerciales binarias: rebajas de enero/agosto,
semana de Black Friday, Cyber Monday, periodo navideño, Reyes, San Valentín,
Día de la Madre, `dias_hasta_evento_comercial` (distancia al próximo evento).

**Geoespaciales — Esri** (disponibles desde julio 2026, las 3 tiendas)

Variables estáticas del entorno: población en buffer de 5/10/15 min a pie,
distancia al nodo de transporte más cercano, renta media del código postal,
conteo de competidores / restauración / tiendas ancla en radio 500m,
índice de movilidad peatonal, densidad comercial score.

Estas features son constantes en el tiempo durante el horizonte de predicción,
lo que elimina el problema de fuga de datos al usarlas como covariables.

---

### 2. Modelo: XGBoost

Gradient Boosted Decision Trees. En cada iteración $m$:

$$F_m(\mathbf{x}) = F_{m-1}(\mathbf{x}) + \eta \cdot f_m(\mathbf{x})$$

donde $\eta = 0.05$ es el learning rate y $f_m$ es un árbol ajustado al gradiente
negativo de la pérdida (MSE para regresión) con regularización $\Omega(f)$ sobre
la complejidad del árbol.

Configuración usada en producción:

```
n_estimators     = 250     # máximo de árboles
learning_rate    = 0.05    # shrinkage
max_depth        = 4       # profundidad máxima → hasta 16 hojas por árbol
early_stopping   = 20      # parar si validación no mejora en 20 rondas
```

**Split temporal**: el histórico hasta $t_0$ se divide en train (primero 85%) y
validación (último 15%), siempre respetando el orden temporal. Una división
aleatoria introduciría data leakage vía los lags.

El early stopping monitoriza el error en validación y detiene el entrenamiento
antes del máximo de árboles. Actúa como regularización implícita.

**Registro de modelos**: el modelo entrenado se serializa a disco (formato `.ubj`)
con metadatos (features usadas, fecha de entrenamiento, métricas). Se reutiliza
durante 7 días si el conjunto de features no ha cambiado, evitando re-entrenar
en cada petición al dashboard.

---

### 3. Predicción autorregresiva multi-step

Para $h = 1$ la predicción es directa. Para $h > 1$, los lags futuros no están
disponibles y se sustituyen por las predicciones ya generadas:

```
Para i = 0, 1, ..., H-1:
    lag_1d  = ŷ_{t₀+i-1}    ← real si i=0, predicho si i>0
    lag_7d  = ŷ_{t₀+i-7}    ← real si i<7, predicho si i≥7
    lag_14d = ŷ_{t₀+i-14}   ← real si i<14, predicho si i≥14
    ŷ_{t₀+i} = max(0, round( modelo.predict(features) ))
    Añadir ŷ_{t₀+i} al buffer histórico de trabajo
```

`max(0, ·)` garantiza no-negatividad. `round(·)` refleja que los conteos son enteros.

**Problema central**: el error de $\hat{y}_{t_0+1}$ contamina $\hat{y}_{t_0+2}$ vía
`lag_1d`, y así sucesivamente. En horizontes largos el modelo revierte a la media
histórica porque los lags predichos pierden información real del proceso. Esto es
el problema de *error propagation in recursive multi-step forecasting*.

---

### 4. Métricas

$$\text{MAE} = \frac{1}{n}\sum_{i=1}^n |y_i - \hat{y}_i|$$

$$\text{WMAPE} = \frac{\sum_{i=1}^n |y_i - \hat{y}_i|}{\sum_{i=1}^n y_i}$$

Se usa WMAPE en lugar de MAPE clásico porque MAPE diverge cuando $y_i \to 0$
(días de cierre, festivos con tráfico mínimo). WMAPE equivale a MAE dividido
por la media ponderando por volumen total.

La accuracy reportada es $\text{acc} = (1 - \text{WMAPE}) \times 100\%$.

---

## Limitaciones actuales — donde entra el TFG

### L1 — Walk-forward validation ausente

El split 85/15 fijo da una única estimación del error. No se sabe si ese error
es representativo o si fue "fácil" por la posición del corte. Una evaluación
correcta para series temporales es **walk-forward (rolling/expanding window)**:
entrenar en $[0, t]$, evaluar en $[t+1, t+H]$, avanzar $t$, repetir. Resultado:
distribución empírica del error por horizonte $h$, no un único escalar.

### L2 — Sin cuantificación de incertidumbre

El modelo produce predicciones puntuales. No hay intervalos de predicción.
Alternativas directamente aplicables sobre XGBoost:

- **Quantile regression**: `objective='reg:quantilereg'`, entrenar un modelo para
  el cuantil $\alpha/2$ y otro para $1-\alpha/2$. Produce bandas de predicción
  pero no garantiza cobertura nominal.
- **Conformal prediction**: método de cobertura garantizada (distribution-free).
  Aplicado a series temporales requiere adaptar el "calibration set" para respetar
  la dependencia temporal (EnbPI, o split conformal con ventana deslizante).

### L3 — Heteroscedasticidad no modelada

La varianza de $y_t$ es mayor en fines de semana y festivos. El MSE los trata igual
que los días laborables. Opciones: transformación $\log(1 + y_t)$, pérdida
heteroscedástica, o modelar la varianza condicionada explícitamente (GARCH sobre
los residuos del modelo de medias).

### L4 — Propagación de incertidumbre meteorológica

El tiempo a $h > 10$ días es en sí mismo una predicción con incertidumbre propia.
El sistema usa el forecast de Open-Meteo (fiable hasta ~10 días) sin modelar
la incertidumbre meteorológica acumulada en el horizonte. Esto significa que el
intervalo de predicción del tráfico debería ser más ancho a medida que $h$ crece,
no solo por la propagación del error del modelo sino también por la incertidumbre
de las covariables.

### L5 — Estrategia de predicción multi-step

Se usa predicción recursiva (un modelo, lags sustituidos por predicciones).
La alternativa es **DIRECTO**: un modelo independiente por cada horizonte $h$,
entrenado directamente con $y_{t+h}$ como target. Evita la propagación de error
pero no aprovecha la estructura autorregresiva. Una comparación formal
(recursivo vs. directo vs. MIMO) para distintos horizontes $h$ y series es
un aporte metodológico concreto.

### L6 — Impacto de features geoespaciales

Las features de Esri llevan disponibles desde julio 2026 para 3 tiendas.
La pregunta de investigación natural: ¿cuánto mejora la predicción al añadir
contexto espacial? SHAP values (nativos en XGBoost vía `get_booster().predict(pred_contribs=True)`)
permiten cuantificar la contribución marginal de cada feature y comparar el
modelo con/sin features geoespaciales en términos de WMAPE y de importancia
de variables.

---

## Posibles enfoques para el TFG

**Enfoque A — Evaluación y comparación de estrategias multi-step**
Implementar y comparar recursivo, directo y MIMO para horizontes
$h \in \{1, 7, 14, 30\}$ usando walk-forward validation. Contribución:
evidencia empírica sobre qué estrategia domina en series de tráfico retail
con fuerte periodicidad semanal.

**Enfoque B — Intervalos de predicción con conformal prediction**
Aplicar split conformal o EnbPI sobre el modelo XGBoost existente para
producir bandas de cobertura garantizada al 90%. Comparar con quantile
regression. Contribución metodológica: extensión de conformal prediction
a series con dependencia temporal en un contexto de aplicación real.

**Enfoque C — Análisis de contribución de covariables espaciales**
Cuantificar el impacto marginal de las features Esri usando SHAP y
diferencia de WMAPE en CV. Comparar las 3 tiendas entre sí (Madrid Gran Vía
tiene un entorno muy diferente a Valencia Bonaire en términos de densidad
comercial y competencia). Contribución: análisis empírico del valor predictivo
de features geoespaciales en series temporales de retail.

**Enfoque D — Modelado de la heteroscedasticidad**
Transformar la serie, ajustar el modelo de medias con XGBoost y modelar
los residuos con GARCH para cuantificar la volatilidad condicionada.
Evaluar si la cobertura empírica de los intervalos GARCH supera a los
de quantile regression o conformal.

---

## Datos disponibles

| Fuente | Cobertura | Frecuencia | Estado |
|---|---|---|---|
| Conteo de visitantes (Aitanna) | Ene 2024 – hoy | Diaria | Activo |
| Temperatura y precipitación (Open-Meteo) | Ene 2024 – +16 días | Diaria | Activo |
| Festivos (librería `holidays`) | Cualquier año | Diaria | Activo |
| Eventos Ticketmaster / TheSportsDB | 2024 – +90 días | Diaria | Activo |
| GeoEnrichment Esri (demografía, movilidad) | Jul 2026 – | Semestral | Activo (3 tiendas) |
| POIs Esri Places (competidores, restauración) | Jul 2026 – | Mensual | Activo (3 tiendas) |

---

## Preguntas para orientar con Claude web

Puedes pegar este documento entero en Claude y preguntar, por ejemplo:

- *"Dado este sistema real, ¿qué enfoque entre A, B, C y D es más original
  y viable para un TFG de estadística de 4 meses?"*
- *"Explícame conformal prediction para series temporales partiendo del sistema
  descrito en L2, sin asumir conocimiento previo de conformal."*
- *"Diseña el esquema de walk-forward validation descrito en L1 con pseudocódigo
  y dime qué métricas reportar en el TFG para que sea estadísticamente sólido."*
- *"¿Cómo comparo recursivo vs. directo en L5 de forma que el test estadístico
  de diferencia de errores sea válido con dependencia temporal (Diebold-Mariano)?"*
