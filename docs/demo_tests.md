# Demo Test Battery

Living document — maintained by `/context-update` at end of each session.
Executed by `/demo-prepare` before demos.

---

## INF — Infraestructura

| ID | Descripción | Comando en servidor |
|----|-------------|---------------------|
| INF-1 | Docker: db, pgweb y prefect-server activos | `docker ps --format '{{.Names}}' \| sort` |
| INF-2 | Gunicorn (app) activo vía systemd | `systemctl is-active gunicorn` |
| INF-3 | prefect-flows service activo | `systemctl is-active prefect-flows` |
| INF-4 | sync-noche.timer activo (ingesta nocturna) | `systemctl is-active sync-noche.timer` |

## APP — Aplicación

| ID | Descripción | Comando en servidor |
|----|-------------|---------------------|
| APP-1 | Dash responde HTTP 200 | `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/` |
| APP-2 | Endpoint /api/html-to-pdf registrado (405 = existe) | `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/html-to-pdf` |

## DB — Base de datos

| ID | Descripción | Comando en servidor |
|----|-------------|---------------------|
| DB-1 | Ubicaciones activas en dim_ubicaciones | `docker exec agentic-workflow-db-1 psql -U admin -d reporting -t -c "SELECT COUNT(*) FROM dim_ubicaciones WHERE activo = true;"` |
| DB-2 | Sync reciente — última actualización < 48h | `docker exec agentic-workflow-db-1 psql -U admin -d reporting -t -c "SELECT MAX(updated_at) FROM dim_ubicaciones;"` |
| DB-3 | store_features_ext tiene datos | `docker exec agentic-workflow-db-1 psql -U admin -d reporting -t -c "SELECT COUNT(*) FROM store_features_ext LIMIT 1;"` |

## PRE — Prefect

| ID | Descripción | Comando en servidor |
|----|-------------|---------------------|
| PRE-1 | Prefect API healthy | `curl -s http://127.0.0.1:4200/api/health` |
| PRE-2 | Flows registrados (onboarding-ubicacion, onboarding-lote) | `PREFECT_API_URL=http://127.0.0.1:4200/api /home/alvaro.salis/agentic-workflow/venv/bin/prefect flow ls 2>/dev/null` |

## ONB — Pipeline Onboarding (Agentes 1-2)

| ID | Descripción | Comando en servidor |
|----|-------------|---------------------|
| ONB-1 | quality_gate importable sin errores | `cd /home/alvaro.salis/agentic-workflow && venv/bin/python -c "from src.onboarding.quality_gate import validar; print('ok')"` |
| ONB-2 | feature_router importable sin errores | `cd /home/alvaro.salis/agentic-workflow && venv/bin/python -c "from src.onboarding.feature_router import enrutar; print('ok')"` |
| ONB-3 | pipeline.py importable (Prefect tasks ok) | `cd /home/alvaro.salis/agentic-workflow && venv/bin/python -c "from src.onboarding.pipeline import onboarding_ubicacion; print('ok')"` |
| ONB-4 | context_scout importable sin errores | `cd /home/alvaro.salis/agentic-workflow && venv/bin/python -c "from src.onboarding.context_scout import descubrir_fuentes; print('ok')"` |
| ONB-5 | feature_eval importable sin errores | `cd /home/alvaro.salis/agentic-workflow && venv/bin/python -c "from src.onboarding.feature_eval import evaluar; print('ok')"` |
| ONB-6 | smoke_test importable sin errores | `cd /home/alvaro.salis/agentic-workflow && venv/bin/python -c "from src.onboarding.smoke_test import ejecutar; print('ok')"` |
| ONB-7 | _eval_core importable sin depender de src/lab/ | `cd /home/alvaro.salis/agentic-workflow && venv/bin/python -c "from src.onboarding._eval_core import _evaluate_feature, MIN_TRAIN_ROWS; print('ok')"` |
| ONB-8 | puertos_estado importable y parsea XLSX | `cd /home/alvaro.salis/agentic-workflow && venv/bin/python -c "from src.data_ingestion.prefetch.puertos_estado import parse_xlsx, _get_configured_locations; print('ok')"` |
| ONB-9 | metro_madrid importable y lee location_source_config | `cd /home/alvaro.salis/agentic-workflow && venv/bin/python -c "from src.data_ingestion.mensual.metro_madrid import _get_configured_locations; print('ok')"` |
| ONB-10 | theme.py importable (constantes color) | `cd /home/alvaro.salis/agentic-workflow && venv/bin/python -c "from src.core.theme import C_PRIMARY, PALETA_PM; print('ok')"` |
| ONB-11 | utils.py importable (arrays calendario ES) | `cd /home/alvaro.salis/agentic-workflow && venv/bin/python -c "from src.core.utils import MESES_ES, DIAS_SEMANA_ES; print('ok')"` |

## DB-DISPLAY — Registros de display DB-driven

| ID | Descripción | Comando en servidor |
|----|-------------|---------------------|
| DB-4 | poi_category_registry existe | `docker exec agentic-workflow-db-1 psql -U admin -d reporting -t -c "SELECT COUNT(*) FROM poi_category_registry;"` |
| DB-5 | zone_type_registry existe | `docker exec agentic-workflow-db-1 psql -U admin -d reporting -t -c "SELECT COUNT(*) FROM zone_type_registry;"` |
| DB-6 | narrative_category_registry existe | `docker exec agentic-workflow-db-1 psql -U admin -d reporting -t -c "SELECT COUNT(*) FROM narrative_category_registry;"` |
| DB-7 | alert_level_registry existe | `docker exec agentic-workflow-db-1 psql -U admin -d reporting -t -c "SELECT COUNT(*) FROM alert_level_registry;"` |
| DB-8 | feature_registry tiene columnas display_mode y canonical_type | `docker exec agentic-workflow-db-1 psql -U admin -d reporting -t -c "SELECT display_mode, canonical_type FROM feature_registry LIMIT 1;"` |
