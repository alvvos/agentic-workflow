"""
Validadores de estructura de datos para cada sección del panel de reporting.

Cada módulo define:
  SECCION: str                          — nombre de la sección
  validar(df) -> tuple[bool, list[str]] — (ok, lista_errores)

El número de validadores es fijo: uno por estructura de datos consumida
por el panel, independientemente de cuántas fuentes de ingesta existan.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

# ── Registro auto-descubierto ─────────────────────────────────────────────────

_validadores: dict[str, object] = {}  # {seccion: modulo}


def _cargar() -> None:
    pkg_dir = Path(__file__).parent
    for _, modname, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if modname.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"src.api.validadores.{modname}")
            seccion = getattr(mod, "SECCION", None)
            if seccion and callable(getattr(mod, "validar", None)):
                _validadores[seccion] = mod
        except Exception:
            pass


_cargar()


# ── API pública ───────────────────────────────────────────────────────────────


def validar_seccion(seccion: str, df: pd.DataFrame) -> tuple[bool, list[str]]:
    """
    Valida que df tenga la estructura correcta para la sección indicada.

    Devuelve (True, []) si es válido o si no existe validador para esa sección.
    Devuelve (False, [mensajes]) si hay errores de estructura.

    Secciones disponibles: visitas, features_ext, calendario, prevision
    """
    mod = _validadores.get(seccion)
    if mod is None:
        return True, []
    return mod.validar(df)  # type: ignore[attr-defined]


def secciones_disponibles() -> list[str]:
    """Lista de secciones con validador registrado."""
    return list(_validadores.keys())
