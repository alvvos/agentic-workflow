Lee toda la documentación técnica del proyecto para tener contexto completo antes de trabajar.

## Pasos

1. Lee los siguientes archivos **en este orden**:
   - `docs/ARCHITECTURE.md` — arquitectura completa, stack, flujo de datos, interfaces
   - `docs/DB_SCHEMA.md` — schema PostgreSQL completo con todas las tablas y columnas
   - `docs/FILE_TREE.md` — árbol de ficheros anotado
   - `docs/feature_pipeline.md` — ciclo de vida de features externas
   - `docs/context.md` — handoff de la sesión anterior (estado Esri, geo panel, chatbot)

2. Confirma al usuario en **una sola línea** que el contexto está cargado, incluyendo:
   - Versión en producción (del campo en ARCHITECTURE.md)
   - Número de tablas en PostgreSQL
   - Número de ubicaciones activas en Miniso (con/sin geo)
   
   Ejemplo: "Contexto cargado — v2.2.18 · 17 tablas PG · Miniso 4 ubicaciones (3 con geo, 1 sin coordenadas)."

3. **No resumas** el contenido de los archivos al usuario. Solo la línea de confirmación. Queda listo para trabajar.

## Cuándo usar

Al inicio de cada conversación donde vayas a tocar código del proyecto. No hace falta si la sesión ya está en marcha o si tienes el contexto fresco.
