# CLAUDE.md

**Agentic Workflow** — dashboard de analítica retail en tiempo real (Dash/Python). Multi-tenant: org → ubicación → zona. Ingesta datos de afluencia desde la API Aitanna, genera forecasts XGBoost e isócronas Esri, y sirve paneles interactivos por ubicación.

## Comandos

```bash
pip install -r requirements.txt
python app.py                                          # dev, http://localhost:8051
gunicorn --workers 4 --bind 0.0.0.0:8000 app:server   # producción
pytest tests/ -x -q --tb=short                        # tests (requiere DB en localhost:5433)
pre-commit run --all-files                             # black + ruff
```

Deploy: usa `/deploy` (skill) o `./deploy.sh <vX.Y.Z>` en el servidor vía SSH.

## Mapa de directorios

```
src/
  callbacks/      Dash callbacks (analytics, admin, filtros, sync, chat, exports)
  chatbot/        Herramientas del chatbot IA (Gemini/Anthropic)
  conectores/     Clientes externos (Google Places, Esri)
  core/           Config, auth, branding por org, theme, utils
  db/             PostgreSQL: store.py (conexión + queries), seed.py, queries.py
  data_ingestion/ Sync desde Aitanna API, ingesta geo Esri
  data_processing/Enriquecimiento (geo, clima, festivos), data_radar
  layout/         Componentes de layout (sidebar, tabs, modals)
  models/         Detección de anomalías (WIP — no usar en callbacks aún)
  onboarding/     Pipeline de alta de nuevas ubicaciones
  pipeline/       Prefect pipeline runner
  reporting/      Paneles: health_check.py, geo_panel.py, ml_dashboard.py
  services/       ml_predictivo.py (XGBoost forecast)
  lab/            Notebooks de experimentación — NO modificar desde callbacks
assets/           CSS, logos, fotos de tiendas (assets/locations/{uuid}.jpg)
tests/            pytest — 4 ficheros, skip automático si DB no alcanzable
```

## Convenciones no negociables

- Imports absolutos `src.*` — sin imports relativos
- Columna de fecha siempre `'fecha'`; filtrar con `pd.Timestamp`
- Llamadas externas siempre en `try/except Exception` (degradación graceful)
- Placeholders SQL con `?` — `PgConn.execute()` los normaliza a `%s` internamente
- `src/lab/` está excluido del linting y no debe importar ni mutar código de producción
- Branding por org en `src/core/org_branding.py`; el admin panel usa clase `admin-chrome` para quedar siempre neutro
- `src/models/anomalys.py` es WIP — no conectar a callbacks nuevos hasta que esté completo

## No tocar nunca

- `.claude/worktrees/` — worktrees temporales gestionados por agentes
- `src/lab/` — notebooks de experimentación, no se versionan resultados
- Migraciones ya aplicadas en `src/db/seed.py` (comentadas con fecha)
