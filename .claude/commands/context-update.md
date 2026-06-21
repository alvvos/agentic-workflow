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

4. **Haz commit de los docs actualizados:**
   ```bash
   git add docs/
   git commit -m "docs: actualiza documentación técnica post-sesión"
   ```
   Si el commit de docs se puede unir al último commit de código de la sesión (si fue el mismo tema), hazlo como commit separado de todas formas para que sea fácil de rastrear.

5. **Informa al usuario** en 2-3 líneas qué docs se actualizaron y por qué. Nada más.

## Cuándo usar

Al final de cada sesión de trabajo donde se hayan hecho cambios significativos al código, la base de datos, la arquitectura o el estado del proyecto.
