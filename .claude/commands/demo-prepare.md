Ejecuta la batería de tests de salud antes de una demo. Comprueba infraestructura, app, base de datos, Prefect y el pipeline de onboarding.

## Pasos

1. **Lee `docs/demo_tests.md`** para obtener la lista actualizada de tests. Ese archivo es la fuente de verdad — puede tener tests añadidos por `/context-update` desde la última vez que se usó este skill.

2. **Conecta al servidor** con:
   ```
   ssh -i ~/.ssh/id_ed25519_servidor alvaro.salis@34.175.22.17
   ```
   Ejecuta los comandos de cada grupo en orden. Para cada test anota si el resultado es **✓ OK** o **✗ FAIL** (con el output real si falla).

3. **Ejecuta los tests por grupo** en este orden:

   ### INF — Infraestructura
   - Comprueba que los contenedores Docker esperados están Running (`db`, `adminer`, `prefect-server`).
   - Comprueba que los servicios systemd (`gunicorn`, `prefect-flows`, `sync-noche.timer`) están `active`.

   ### APP — Aplicación
   - `curl` al puerto 8000 — espera HTTP 200.
   - `curl` al endpoint `/api/html-to-pdf` — espera 405 (existe pero rechaza GET).

   ### DB — Base de datos
   - Cuenta ubicaciones activas en `dim_ubicaciones` — espera > 0.
   - Comprueba `MAX(updated_at)` en `dim_ubicaciones` — debe ser de las últimas 48 horas.
   - Comprueba que `store_features_ext` tiene filas.

   ### PRE — Prefect
   - `/api/health` devuelve `{"status":"healthy"}`.
   - `prefect flow ls` muestra `onboarding-ubicacion` y `onboarding-lote`.

   ### ONB — Pipeline Onboarding
   - Importa `quality_gate`, `feature_router`, `pipeline` en el venv del servidor — espera `ok` sin tracebacks.

   Si `docs/demo_tests.md` contiene grupos adicionales (añadidos por sesiones posteriores), ejecútalos también.

4. **Muestra un resumen** en formato tabla:

   ```
   ┌──────┬─────────────────────────────────────────┬────────┐
   │  ID  │ Descripción                             │ Estado │
   ├──────┼─────────────────────────────────────────┼────────┤
   │ INF-1│ Docker containers                       │  ✓ OK  │
   │ INF-2│ Gunicorn systemd                        │  ✓ OK  │
   │ ...  │ ...                                     │  ...   │
   └──────┴─────────────────────────────────────────┴────────┘
   ```

   - Si **todos pasan**: termina con `→ Sistema listo para demo.`
   - Si **alguno falla**: lista los tests fallidos con su output real y sugiere el fix más probable. No des por lista la demo hasta que estén resueltos.

## Cuándo usar

Justo antes de una demo. Lanzar desde el directorio del proyecto con `/demo-prepare`.
