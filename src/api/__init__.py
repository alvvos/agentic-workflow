"""
API interna — FastAPI.

Punto de entrada:
    uvicorn src.api.servidor:app --port 8001 --reload

Rutas principales:
    GET  /salud
    GET  /ubicaciones
    GET  /ubicaciones/{uuid}
    GET  /ubicaciones/{uuid}/fuentes
    POST /ubicaciones/{uuid}/fuentes/{source}
    DEL  /ubicaciones/{uuid}/fuentes/{source}
    GET  /fuentes/catalogo
    GET  /ubicaciones/{uuid}/features
    PATCH /ubicaciones/{uuid}/features/{feature_key}
    GET  /features/catalogo
"""
