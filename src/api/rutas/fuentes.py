from fastapi import APIRouter, HTTPException

from src.api.controladores import fuentes as ctrl
from src.api.modelos.fuente import ConfigFuente, FuenteDisponible, NuevaConfigFuente

router = APIRouter(tags=["Fuentes"])


@router.get("/fuentes/catalogo", response_model=list[FuenteDisponible])
def catalogo_fuentes() -> list[FuenteDisponible]:
    return ctrl.catalogo_fuentes()


@router.get("/ubicaciones/{uuid}/fuentes", response_model=list[ConfigFuente])
def listar_fuentes(uuid: str) -> list[ConfigFuente]:
    return ctrl.listar_fuentes(uuid)


@router.post(
    "/ubicaciones/{uuid}/fuentes/{source}",
    response_model=ConfigFuente,
    status_code=201,
)
def configurar_fuente(uuid: str, source: str, body: NuevaConfigFuente) -> ConfigFuente:
    config, err = ctrl.configurar_fuente(uuid, source, body.params)
    if err:
        raise HTTPException(status_code=422, detail=err)
    return config


@router.delete("/ubicaciones/{uuid}/fuentes/{source}", status_code=204)
def eliminar_fuente(uuid: str, source: str) -> None:
    encontrado = ctrl.eliminar_fuente(uuid, source)
    if not encontrado:
        raise HTTPException(
            status_code=404,
            detail=f"No hay configuración activa de '{source}' para '{uuid}'",
        )
