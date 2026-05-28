import json
import os
from datetime import date, timedelta

from src.data_processing.geo_enrichment import (
    GEO_FEATURE_COLS,
    GEO_FEATURES_BACKDATABLE,
    GEO_FEATURES_DINAMICAS,
    _GEO_PATH,
)

TRAINING_START = "2024-01-01"

def ingestar_snapshot_esri(
    location_uuid: str,
    valores: dict,
    fecha_entrega: str = None,
) -> dict:
    """
    Registra una nueva entrega de datos Esri para una ubicación.

    Aplica la política de back-date diferenciada por tipo de feature:

    Primera entrega
    ───────────────
    Se generan DOS snapshots:

    1. Snapshot estructural [TRAINING_START → fecha_entrega - 1 día]
       Contiene solo features backdatables (poblacion_*, dist_transporte_min_m,
       renta_media_cp, poblacion_cp). Son valores de lenta evolución — el dato
       de hoy es una aproximación honesta del pasado.
       El modelo aprende la correlación entre contexto estructural y tráfico
       a lo largo de todo el histórico disponible.

    2. Snapshot completo [fecha_entrega → abierto]
       Contiene todas las features, incluidas las dinámicas
       (densidad_comercial_score, indice_movilidad_peatonal, n_competidores_500m,
       dist_competidor_cercano_m). Estas no se back-datean porque un competidor
       que abrió en 2026 no existía en 2024.

    Entregas subsiguientes
    ──────────────────────
    Se cierra el snapshot activo y se abre uno nuevo con todos los valores actualizados.
    El histórico anterior queda intacto — nunca se elimina ningún snapshot.

    Parámetros
    ──────────
    location_uuid   UUID de la localización (debe existir en todas_las_ubicaciones.json)
    valores         Dict con los valores Esri. Las claves deben ser subconjunto de GEO_FEATURE_COLS.
    fecha_entrega   Fecha ISO 8601 de esta entrega. Por defecto: hoy.

    Retorna
    ───────
    Dict con resumen de la operación: snapshots creados, features registradas, política aplicada.

    Ejemplo
    ───────
    >>> from src.data_ingestion.ingesta_geo import ingestar_snapshot_esri
    >>> resultado = ingestar_snapshot_esri(
    ...     location_uuid="67034276-0d01-4c90-a363-fa75699a19a4",
    ...     valores={
    ...         "poblacion_5min": 4200,
    ...         "poblacion_10min": 14800,
    ...         "poblacion_15min": 31500,
    ...         "dist_transporte_min_m": 95,
    ...         "renta_media_cp": 24300,
    ...         "poblacion_cp": 52000,
    ...         "densidad_comercial_score": 0.81,
    ...         "indice_movilidad_peatonal": 0.73,
    ...         "n_competidores_500m": 4,
    ...         "dist_competidor_cercano_m": 210,
    ...     },
    ...     fecha_entrega="2026-06-01",
    ... )
    """
    if fecha_entrega is None:
        fecha_entrega = date.today().isoformat()

    # Extraer geometría antes de la validación de keys (no es una feature del modelo)
    catchment_rings = valores.pop("_catchment_rings", None)

    desconocidas = set(valores.keys()) - set(GEO_FEATURE_COLS)
    if desconocidas:
        raise ValueError(f"Features no reconocidas (no están en GEO_FEATURE_COLS): {desconocidas}")

    # Leer JSON completo preservando _meta y todas las ubicaciones
    with open(_GEO_PATH, "r", encoding="utf-8") as f:
        store_raw = json.load(f)

    snapshots = store_raw.get(location_uuid, [])
    if not isinstance(snapshots, list):
        snapshots = []

    # Primera entrega = todos los snapshots previos tienen valores todos nulos
    is_primera_entrega = not any(
        any(s.get(col) is not None for col in GEO_FEATURE_COLS)
        for s in snapshots
    )

    fecha_entrega_dt = date.fromisoformat(fecha_entrega)
    cierre_anterior = (fecha_entrega_dt - timedelta(days=1)).isoformat()

    # Cerrar snapshot activo sin eliminarlo — el histórico es inmutable
    for s in snapshots:
        if s.get("valid_to") is None:
            s["valid_to"] = cierre_anterior

    nuevos_snapshots = []
    politica_log = []

    if is_primera_entrega:
        # Rellena el placeholder nulo in-place si ya existe un snapshot con valid_from=TRAINING_START
        # (evita crear dos intervalos solapados con el mismo valid_from).
        snap_placeholder = next(
            (s for s in snapshots if s.get("valid_from") == TRAINING_START),
            None,
        )
        if snap_placeholder is not None:
            for col in GEO_FEATURES_BACKDATABLE:
                if col in valores:
                    snap_placeholder[col] = valores[col]
        else:
            snap_estructural = {
                "valid_from": TRAINING_START,
                "valid_to": cierre_anterior,
                **{col: None for col in GEO_FEATURE_COLS},
            }
            for col in GEO_FEATURES_BACKDATABLE:
                if col in valores:
                    snap_estructural[col] = valores[col]
            nuevos_snapshots.append(snap_estructural)

        backdated = [c for c in GEO_FEATURES_BACKDATABLE if valores.get(c) is not None]
        politica_log.append({
            "tipo": "estructural_backdated",
            "valid_from": TRAINING_START,
            "valid_to": cierre_anterior,
            "features": backdated,
        })

    snap_completo = {
        "valid_from": fecha_entrega,
        "valid_to": None,
        **{col: None for col in GEO_FEATURE_COLS},
    }
    for col in GEO_FEATURE_COLS:
        if col in valores:
            snap_completo[col] = valores[col]
    if catchment_rings is not None:
        snap_completo["catchment_rings"] = catchment_rings

    nuevos_snapshots.append(snap_completo)
    politica_log.append({
        "tipo": "completo" if is_primera_entrega else "actualizacion",
        "valid_from": fecha_entrega,
        "valid_to": None,
        "features": [c for c in GEO_FEATURE_COLS if valores.get(c) is not None],
    })

    store_raw[location_uuid] = snapshots + nuevos_snapshots

    # Escritura atómica: evita estado corrupto si el proceso muere durante la escritura
    tmp_path = _GEO_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(store_raw, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, _GEO_PATH)

    # Invalidar modelos en caché para esta ubicación — el próximo predict reentrenará
    # con los nuevos datos Esri.
    from src.services.ml_predictivo import invalidar_modelos_location
    invalidar_modelos_location(location_uuid)

    return {
        "location_uuid": location_uuid,
        "primera_entrega": is_primera_entrega,
        "snapshots_creados": len(nuevos_snapshots),
        "features_registradas": [c for c in GEO_FEATURE_COLS if valores.get(c) is not None],
        "politica_aplicada": politica_log,
    }


def actualizar_catchment_rings(location_uuid: str, lat: float, lon: float) -> bool:
    """
    Actualiza solo la geometría de isócronas del snapshot activo, sin crear
    una nueva entrega ni modificar los valores de features del modelo.

    Llama a ServiceArea peatonal (5/10/15 min) y sobreescribe catchment_rings
    en el snapshot con valid_to=None. Invalida la caché del store.

    Retorna True si la actualización tuvo éxito, False si ServiceArea no respondió.
    """
    from src.data_ingestion.esri_client import fetch_service_area_isochrones

    rings = fetch_service_area_isochrones(lat, lon)
    if rings is None:
        return False

    with open(_GEO_PATH, "r", encoding="utf-8") as f:
        store_raw = json.load(f)

    snapshots = store_raw.get(location_uuid, [])
    activo = next((s for s in snapshots if s.get("valid_to") is None), None)
    if activo is None:
        return False

    activo["catchment_rings"] = rings

    tmp_path = _GEO_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(store_raw, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, _GEO_PATH)

    # Forzar recarga del cache en geo_enrichment (el cambio de mtime lo haría
    # automáticamente, pero limpiar explícitamente garantiza consistencia inmediata)
    from src.data_processing import geo_enrichment as _ge
    _ge._store_cache.clear()

    return True


def listar_estado_geo(location_uuid: str = None) -> dict:
    """
    Devuelve el estado del feature store para una o todas las ubicaciones.
    Útil para auditar qué ubicaciones tienen datos Esri y qué features faltan.

    Parámetros
    ──────────
    location_uuid   Si se especifica, devuelve solo esa ubicación. Si None, devuelve todas.

    Retorna
    ───────
    Dict con: número de snapshots, features pobladas, features pendientes, snapshot activo.
    """
    with open(_GEO_PATH, "r", encoding="utf-8") as f:
        store_raw = json.load(f)

    uuids = [location_uuid] if location_uuid else [k for k in store_raw if not k.startswith("_")]
    resultado = {}

    for uuid in uuids:
        snapshots = store_raw.get(uuid, [])
        if not isinstance(snapshots, list):
            continue

        activo = next((s for s in snapshots if s.get("valid_to") is None), None)
        tiene_datos = any(
            any(s.get(col) is not None for col in GEO_FEATURE_COLS)
            for s in snapshots
        )

        resultado[uuid] = {
            "snapshots_totales": len(snapshots),
            "tiene_datos_esri": tiene_datos,
            "snapshot_activo": {
                "valid_from": activo.get("valid_from") if activo else None,
                "features_pobladas": [c for c in GEO_FEATURE_COLS if activo and activo.get(c) is not None],
                "features_pendientes": [c for c in GEO_FEATURE_COLS if not activo or activo.get(c) is None],
            } if activo else None,
        }

    return resultado
