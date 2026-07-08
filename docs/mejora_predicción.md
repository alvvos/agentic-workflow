# Handoff — Integración de intervalos de predicción (conformal) en el sistema de afluencia

## Objetivo

Envolver el predictor XGBoost de afluencia existente con **predicción conforme
(split conformal)** para producir **intervalos de predicción con garantía de
cobertura** (~90%), en lugar de una predicción puntual. Resuelve la limitación
**L2** (sin cuantificación de incertidumbre) del sistema actual.

Este documento es la guía para **empezar la integración** en el panel.

---

## Contexto del sistema actual (resumen)

- Modelo: XGBoost (GBDT), regresión, predicción de visitantes diarios por zona.
- Multi-step **recursivo**: los lags futuros se sustituyen por predicciones previas.
- Split temporal 85/15 fijo, respetando orden temporal.
- Métricas: MAE, WMAPE. Salida: **predicción puntual** `max(0, round(ŷ))`.
- Horizonte habitual H = 30 días.

---

## Qué es split conformal, en una frase

Se toman los **residuos absolutos** del modelo sobre un bloque de calibración
retenido, se calcula su **cuantil empírico (1−α)** con corrección de muestra
finita, y ese valor `q` es la semi-anchura de la banda: `[ŷ − q, ŷ + q]`.
Bajo intercambiabilidad, cubre con probabilidad ≥ 1−α. En series temporales la
cobertura es **aproximada** (la intercambiabilidad no se cumple); las fases
siguientes la mejoran.

---

## Fase 1 — Split conformal básico  (~1 día)

Pasos:

1. Reservar un **bloque de calibración** en la cola del train, respetando el
   orden temporal (NO barajar — barajar introduce leakage vía los lags).
   Ej.: el modelo entrena con el primer 80% del train; el último 20% es
   calibración.
2. Calcular residuos de calibración `R_i = |y_i − ŷ_i|`.
3. Cuantil con corrección de muestra finita:
   tomar el residuo en la posición `⌈(n+1)(1−α)⌉` de los residuos ordenados.
4. Intervalo para un punto nuevo: `[max(0, round(ŷ − q)), round(ŷ + q)]`
   (respetar no-negatividad y redondeo a entero, coherente con el pipeline).

Esbozo (Python, indicativo — ajustar a la API real del proyecto):

```python
resid = np.abs(y_cal - model.predict(X_cal))
n = len(resid)
level = np.ceil((n + 1) * (1 - alpha)) / n
q = np.quantile(resid, min(level, 1.0), method="higher")
lower = np.maximum(0, np.round(y_pred - q))
upper = np.round(y_pred + q)
```

**Limitación consciente de la Fase 1:** da UNA sola anchura `q` para todos los
horizontes. Es incorrecto para multi-step (el error crece con h). Se corrige en
la Fase 2. Documentar esta limitación en el panel (ej.: "intervalo aproximado,
no ajustado por horizonte").

---

## Fase 2 — Conformal por horizonte

Problema: en multi-step recursivo el error se propaga y **crece con h** (L5).
Una sola `q` infravalora la incertidumbre en h=30 y la sobrevalora en h=1.

Solución: **calibración separada por horizonte**. Para cada `h ∈ {1,…,H}`,
recoger los residuos de las predicciones a h pasos sobre el bloque de
calibración (mediante origen deslizante) y calcular `q_h`. Las bandas se
ensanchan de forma natural con h. Esto además ataca en parte **L4**
(la incertidumbre debe crecer con el horizonte).

---

## Validación y métricas a añadir al panel

La cobertura hay que **medirla**, no asumirla. Evaluar con **walk-forward**
(entrenar en `[0,t]`, evaluar en `[t+1, t+H]`, avanzar `t`, repetir):

- **Cobertura empírica** (objetivo 90%): fracción de valores reales dentro de la
  banda.
- **Anchura media del intervalo** por horizonte h (informatividad / sharpness).
- **Trade-off cobertura–anchura**.

Baseline de comparación: regresión cuantílica nativa de XGBoost (verificar el
string exacto del `objective` para la versión instalada — cambió entre versiones).

---

## Errores fáciles de cometer (evitar)

- Barajar datos para calibración → rompe el orden temporal, leakage.
- Usar una sola `q` para todos los horizontes como versión final (la Fase 1 lo
  hace a propósito y provisionalmente; pasar a Fase 2).
- Evaluar cobertura con un solo split → no informa nada; usar walk-forward.
- Confundir "banda al 90%" con "cobertura del 90%": la cobertura hay que MEDIRLA.

---

## Mejoras futuras (opcional)

Para reforzar el manejo de la dependencia temporal más allá de la Fase 2:

- **Calibración adaptativa**: ventana de calibración reciente que sigue la deriva
  y la heteroscedasticidad (L3).
- **ACI** (adaptive conformal inference): actualización online del nivel α
  efectivo mediante una tasa de aprendizaje γ.
- **EnbPI**: residuos out-of-bag de un ensemble, sin dividir datos.

---

## Referencias mínimas para quien implemente

- Angelopoulos & Bates (2023), *Conformal Prediction: A Gentle Introduction* —
  leer secciones 1–2 antes de tocar código.
- (Avanzado / mejoras futuras) Xu & Xie (2021), EnbPI;
  Gibbs & Candès (2021), *Adaptive Conformal Inference Under Distribution Shift*.
