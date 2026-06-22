Actualiza la documentación técnica del proyecto con los cambios de esta sesión.

## Pasos

1. **Revisa qué cambió** en esta sesión:
   - `git diff HEAD~5..HEAD --stat` — ficheros modificados en commits recientes
   - `git log --oneline -10` — commits de la sesión
   - Piensa en qué cambios conceptuales ocurrieron (nuevas features, bugs encontrados, decisiones de arquitectura, cambios de schema, etc.)

2. **Para cada doc, decide si necesita actualización:**

   ### `docs/ARCHITECTURE.md`
   Actualizar si cambió:
   - Stack o versiones
   - Flujo de datos o ingesta nocturna
   - Componentes añadidos/eliminados
   - Interfaces clave (firmas de funciones)
   - Bugs conocidos (añadir nuevos, marcar los resueltos)
   - Variables de entorno

   ### `docs/DB_SCHEMA.md`
   Actualizar si cambió:
   - Columnas añadidas o eliminadas en alguna tabla (via `_migrate_*` en store.py)
   - Nuevas tablas
   - Cambios en `feature_registry` o `feature_flags` (status de features)
   - Estado actual del feature registry al final

   ### `docs/FILE_TREE.md`
   Actualizar si:
   - Se crearon o eliminaron archivos
   - Cambió el propósito de un módulo existente
   - Se añadieron scripts o comandos

   ### `docs/feature_pipeline.md`
   Actualizar si cambió la lógica de ingesta, evaluación o activación de features.

   ### `docs/context.md`
   Actualizar si hay cambios de estado importantes para la próxima sesión:
   - Bugs encontrados y su estado
   - Decisiones arquitectónicas tomadas
   - Features Esri / geo — estado actual
   - Próximos pasos pendientes

3. **Edita solo los docs que necesiten cambios.** No toques un doc si no cambió nada relevante.

4. **Actualiza `docs/demo_tests.md`** con los tests de lo implementado en esta sesión.

   **4a. Obtén la lista real de ficheros nuevos o modificados:**
   ```bash
   git diff HEAD~10..HEAD --name-only --diff-filter=AM
   ```
   Agrupa los resultados por tipo y genera un test por cada componente nuevo, siguiendo estas reglas exactas:

   | Patrón de fichero                      | Grupo  | ID siguiente libre | Comando de test                                                                                  |
   |----------------------------------------|--------|--------------------|--------------------------------------------------------------------------------------------------|
   | `src/onboarding/*.py`                  | ONB    | ONB-N+1            | `cd /home/alvaro.salis/agentic-workflow && venv/bin/python -c "from src.onboarding.<módulo> import <símbolo_principal>; print('ok')"` |
   | `src/data_ingestion/*.py` (nuevo)      | ONB    | ONB-N+1            | igual que arriba pero con `src.data_ingestion.<módulo>`                                          |
   | `src/services/*.py` (nuevo)            | APP    | APP-N+1            | import test + si expone endpoint, `curl` al puerto 8000                                          |
   | `src/callbacks/*.py` (nuevo)           | APP    | APP-N+1            | `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/` (verifica que la app arranca)   |
   | `src/db/store.py` (tabla nueva)        | DB     | DB-N+1             | `docker exec agentic-workflow-db-1 psql -U admin -d reporting -t -c "SELECT COUNT(*) FROM <tabla>;"` |
   | `deploy/systemd/*.service` (nuevo)     | INF    | INF-N+1            | `systemctl is-active <nombre-servicio>`                                                          |
   | `scripts/*.py` (nuevo flow Prefect)    | PRE    | PRE-N+1            | `PREFECT_API_URL=http://127.0.0.1:4200/api venv/bin/prefect flow ls 2>/dev/null \| grep <nombre-flow>` |

   **4b. Añade solo las filas que no existan ya** en `docs/demo_tests.md`. Usa el siguiente ID libre dentro del grupo (lee el archivo primero para saber cuál es). No elimines tests existentes.

   **4c. Si se eliminó un componente** (fichero en `--diff-filter=D`), elimina la fila de test correspondiente y renumera si es necesario.

   Si no hubo ficheros nuevos relevantes, no toques el archivo.

5. **Haz commit de los docs actualizados:**
   ```bash
   git add docs/
   git commit -m "docs: actualiza documentación técnica post-sesión"
   ```
   Si el commit de docs se puede unir al último commit de código de la sesión (si fue el mismo tema), hazlo como commit separado de todas formas para que sea fácil de rastrear.

6. **Informa al usuario** en 2-3 líneas qué docs se actualizaron y por qué. Nada más.

## Cuándo usar

Al final de cada sesión de trabajo donde se hayan hecho cambios significativos al código, la base de datos, la arquitectura o el estado del proyecto.
