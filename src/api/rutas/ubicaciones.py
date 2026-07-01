from fastapi import APIRouter, HTTPException

from src.api.controladores import ubicaciones as ctrl
from src.api.modelos.ubicacion import Ubicacion, UbicacionResumen

router = APIRouter(tags=["Ubicaciones"])


@router.get("/ubicaciones", response_model=list[UbicacionResumen])
def listar_ubicaciones(solo_activas: bool = True) -> list[UbicacionResumen]:
    return ctrl.listar_ubicaciones(activas_only=solo_activas)


@router.get("/ubicaciones/{uuid}", response_model=Ubicacion)
def obtener_ubicacion(uuid: str) -> Ubicacion:
    loc = ctrl.obtener_ubicacion(uuid)
    if loc is None:
        raise HTTPException(status_code=404, detail=f"Ubicación '{uuid}' no encontrada")
    return loc
