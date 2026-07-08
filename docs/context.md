# Context — Handoff sesión 2026-07-08

## Estado general

Versión en producción: **v2.2.77**. Esta sesión incorporó Kiosko MX como segundo tenant, implementó predicción conformal al 90 %, añadió la barrera de entrada por org, y reescribió el sync del árbol Aitanna para que sea automático.

---

## Cambios de esta sesión

### 1. Barrera de entrada por organización — `ALLOWED_ORG_IDS`

`src/data_ingestion/_common.py` define un frozenset:
```python
ALLOWED_ORG_IDS = frozenset({
    "5c13b57d-782d-4458-911b-64cd40eebb55",  # Miniso España
    "5345a134-3495-4884-a780-c9b37a50df20",  # Kiosko MX
})
```
Importado en `_common.get_active_locations()` y en `data_master._load_from_db()`. El API key de Aitanna tiene acceso cross-org — sin este filtro entrarían datos de The Phone House ES, S69, etc. **CRÍTICO: al añadir un cliente nuevo, añadir su org_uuid aquí.**

### 2. Kiosko MX — Colima Nueva

**UUID correcto:** `e160c359-66a5-4366-b1ac-94cb8f846bbd` (obtenido de `/api/v1/get-all-locations-and-zones`).
**Datos disponibles:** desde 2026-05-08. Sin datos antes de esa fecha.
**Zonas (con sus UUIDs reales de Aitanna):**
- `960e1607` → Exterior (funnel_step=1, zone_type=exterior)
- `5750d14e` → Tienda (funnel_step=2, zone_type=interior)
- `05809e0f` → Caja (funnel_step=3, zone_type=checkout, parent=Tienda)

**Incidente UUID:** en sesiones anteriores se identificó `ce86e8a6` como "Colima Nueva" vía logs del sincronizador. Ese UUID pertenece a **The Phone House — Móstoles** (España), no a Kiosko. El API key de Aitanna permite query cross-org, lo que causó la confusión. Se eliminó y se reemplazó por el UUID correcto.

### 3. Sync automático del árbol Aitanna — `actualizar_arbol_ubicaciones.py`

Reescrito completamente. Ahora en Fase 0 llama a:
```
GET https://platform.aitanna.ai/api/v1/get-all-locations-and-zones
```
Devuelve el árbol completo org → ubicación → zona con `zoneName` y jerarquía (`fathers`). La función `_sync_arbol_aitanna()` hace upsert en `organizaciones`, `ubicaciones` y `zonas`, filtrando por `ALLOWED_ORG_IDS`. Los nombres de zona se toman directamente del campo `zoneName` de la API — no se asignan manualmente. Luego se detectan ubicaciones nuevas y se lanza el pipeline de onboarding como antes.

**Nota importante:** La Fase 0 no debe nunca asignar nombres de zona a mano. Siempre desde la API.

### 4. Predicción conformal al 90 % — `ml_predictivo.py` + `ml_dashboard.py`

Split cambiado de 85/15 a **70/15/15** (train/calibración/validación).

Cuantil conformal:
```python
resid = |y_cal - max(0, modelo.predict(X_cal))|
level = min(ceil((n_cal+1) * 0.90) / n_cal, 1.0)
q_conf = quantile(resid, level, method="higher")
```

`q_conf` se guarda en el cache de modelo (`.meta.json`) y se devuelve en el resultado como `lower` y `upper`. El dashboard renderiza la banda como polígono `fill="toself"` en Plotly, con `fillcolor="rgba(39,174,96,0.10)"`.

La función `_loop_prediccion()` se extrajo como función standalone (antes era código inline en `ejecutar_auditoria_predictiva`).

### 5. Fix DatePickerRange — `sidebar.py`

`start_date` cambiado de `datetime(2025, 9, 1)` hardcodeado a `datetime.today() - timedelta(days=90)` (rolling 90 días). Evita que el picker abra en 2025 cuando el usuario tiene datos de 2026.

---

## Estado de tenants

| Org | UUID | Ubicaciones activas | Datos desde | Esri | Contexto |
|---|---|---|---|---|---|
| Miniso España | `5c13b57d` | 4 (Madrid GV, Málaga, Valencia, Tenerife⚠) | ene 2024 | Madrid + Málaga | ✅ completo |
| Kiosko MX | `5345a134` | 1 (Colima Nueva) | 8 may 2026 | No | Sin señales de contexto |

---

## Endpoint Aitanna relevante descubierto

`GET https://platform.aitanna.ai/api/v1/get-all-locations-and-zones`
- Headers: `x-api-key: <AITANNA_API_KEY>`
- Devuelve: `[{uuid, name, locations: [{uuid, name, zones: [{uuid, zoneName, hidden, fathers?}]}]}]`
- Filtra: el API key tiene acceso cross-org. Siempre filtrar por `ALLOWED_ORG_IDS`.

---

## Bugs conocidos

- `src/models/anomalys.py` (`generar_panel_bi_completo`) — WIP, RuntimeError si se alcanza en analytics callback.
- `src/data_processing/constructor_master.py` — lee `loc.get('latitude', ...)` pero el JSON usa `lat`. Pre-existente, no bloqueante.
- **Tenerife CC Nivaria** — sin coordenadas. Excluida de prefetch.

---

## Próximos pasos

1. **Kiosko MX — más ubicaciones:** Manzanillo (`2ee8181c`) está en el árbol sin datos. Cuando arranque el sensor, `_sync_arbol_aitanna()` lo detectará y lanzará onboarding automáticamente.
2. **Predicción para Kiosko:** Con datos desde mayo 2026 (~60 días), hay suficiente histórico para entrenar XGBoost. Validar que la predicción funciona en el tab Predicción para Colima Nueva.
3. **Conformal Fase 2:** Implementar ventana deslizante para calibración (en lugar de bloque fijo) para mejor cobertura empírica en horizontes largos.
4. **Validar impacto geo en modelo** — comparar WMAPE antes/después de primeras entregas Esri en Málaga y Madrid Gran Vía.
5. **Poblar registros de display** — `zone_type_registry`, `narrative_category_registry`, `alert_level_registry` creadas pero vacías.
