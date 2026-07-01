from fastapi import APIRouter, HTTPException

from src.api.controladores import features as ctrl
from src.api.modelos.feature import CambiarEstadoFeature, EstadoFeature, Feature

router = APIRouter(tags=["Features"])


@router.get("/features/catalogo", response_model=list[Feature])
def catalogo_features() -> list[Feature]:
    return ctrl.listar_features_catalogo()


@router.get("/ubicaciones/{uuid}/features", response_model=list[EstadoFeature])
def listar_features(uuid: str) -> list[EstadoFeature]:
    return ctrl.listar_features(uuid)


@router.patch(
    "/ubicaciones/{uuid}/features/{feature_key}",
    response_model=EstadoFeature,
)
def cambiar_estado_feature(
    uuid: str,
    feature_key: str,
    body: CambiarEstadoFeature,
) -> EstadoFeature:
    result = ctrl.cambiar_estado_feature(uuid, feature_key, body.status)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Feature '{feature_key}' no encontrada para '{uuid}'",
        )
    return result
