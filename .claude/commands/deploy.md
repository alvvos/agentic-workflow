Despliega la versión actual al servidor de producción. Flujo completo: commit (si hay cambios pendientes) → tag → push → SSH deploy.

## Argumento opcional

`$ARGUMENTS` puede ser un número de versión completo (`v1.9.0`) o solo el segmento que cambia (`1.9.0`, `9.0`, `9`).
Si no se pasa nada, calcula automáticamente el siguiente patch del último tag.

## Pasos a ejecutar

1. **Determina la versión**:
   - Si `$ARGUMENTS` está vacío: ejecuta `git tag --sort=-v:refname | head -1` para obtener el último tag y calcula el siguiente patch (ej. `v1.8.1` → `v1.8.2`).
   - Si se pasa un argumento: normalízalo añadiendo `v` y los segmentos que falten hasta tener `vX.Y.Z`.

2. **Revisa el estado del repo** (`git status --short` y `git diff --stat HEAD`):
   - Si hay cambios staged o unstaged: muéstralos brevemente y pide un mensaje de commit al usuario antes de continuar.
   - Si el working tree está limpio: salta al paso 3.

3. **Commit** (solo si había cambios): `git commit -m "<mensaje proporcionado>"`.

4. **Tag y push**:
   ```bash
   git tag <versión>
   git push
   git push --tags
   ```

5. **Deploy en el servidor**:
   ```bash
   ssh -i ~/.ssh/id_ed25519_servidor alvaro.salis@34.175.22.17 "./deploy.sh <versión>"
   ```

6. **Verificación** — espera 8 segundos y comprueba que el servicio sigue activo:
   ```bash
   ssh -i ~/.ssh/id_ed25519_servidor alvaro.salis@34.175.22.17 "systemctl is-active agentic-workflow"
   ```
   Informa del resultado: versión desplegada, estado del servicio y cualquier error del log si el servicio no está `active`.
