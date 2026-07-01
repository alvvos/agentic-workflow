"""
Descubre automáticamente los validadores de params por SOURCE.

Convención: cada módulo en este paquete expone:
  SOURCE: str      — nombre de la fuente (ej. 'metro_madrid')
  Params: BaseModel — modelo Pydantic con los campos requeridos

El módulo se auto-carga al importar este paquete.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from pydantic import BaseModel, ValidationError

_validadores: dict[str, type[BaseModel]] = {}


def _cargar() -> None:
    pkg_dir = Path(__file__).parent
    for _, modname, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if modname.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"src.api.validadores.{modname}")
            cls = getattr(mod, "Params", None)
            source = getattr(mod, "SOURCE", modname)
            if cls is not None:
                _validadores[source] = cls
        except Exception:
            pass


_cargar()


def validar_params(source: str, params: dict) -> tuple[bool, str | None]:
    """
    Valida los params para el source dado.
    Devuelve (True, None) si OK o si no existe validador para ese source.
    Devuelve (False, mensaje) si falla la validación.
    """
    cls = _validadores.get(source)
    if cls is None:
        return True, None
    try:
        cls.model_validate(params)
        return True, None
    except ValidationError as exc:
        errores = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return False, errores


def schema_params(source: str) -> dict | None:
    """Devuelve el JSON Schema de los params del source, o None si no hay validador."""
    cls = _validadores.get(source)
    return cls.model_json_schema() if cls else None


def fuentes_con_validador() -> list[str]:
    return list(_validadores.keys())
