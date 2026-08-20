from dash import Input, Output

from src.core.auth import is_admin
from src.core.config import app

_SHOW = {}
_HIDE = {"display": "none"}
_CONTAINER_DASHBOARD = {"padding": "28px 32px", "minHeight": "100vh", "background": "#f7f7f5"}
_CONTAINER_ADMIN = {"padding": "0", "minHeight": "100vh", "background": "#f7f7f5"}

_NAV_ACTIVE = (
    "admin-nav-link d-flex align-items-center px-3 py-2 mb-1 rounded-3 text-decoration-none active"
)
_NAV_BASE = "admin-nav-link d-flex align-items-center px-3 py-2 mb-1 rounded-3 text-decoration-none"


@app.callback(
    Output("main-container", "style"),
    Output("dashboard-container", "style"),
    Output("admin-container", "style"),
    Output("admin-page-usuarios", "style"),
    Output("admin-page-ubicaciones", "style"),
    Output("admin-page-pois", "style"),
    Output("admin-nav-usuarios", "className"),
    Output("admin-nav-ubicaciones", "className"),
    Output("admin-nav-pois", "className"),
    Input("url", "pathname"),
)
def route_page(pathname):
    if not pathname or not pathname.startswith("/admin"):
        return (
            _CONTAINER_DASHBOARD,
            _SHOW,
            _HIDE,
            _HIDE,
            _HIDE,
            _HIDE,
            _NAV_BASE,
            _NAV_BASE,
            _NAV_BASE,
        )

    if not is_admin():
        return (
            _CONTAINER_DASHBOARD,
            _SHOW,
            _HIDE,
            _HIDE,
            _HIDE,
            _HIDE,
            _NAV_BASE,
            _NAV_BASE,
            _NAV_BASE,
        )

    def _nav(target: str) -> str:
        return _NAV_ACTIVE if pathname.startswith(target) else _NAV_BASE

    page_usuarios = _SHOW if pathname == "/admin/usuarios" else _HIDE
    page_ubicaciones = _SHOW if pathname == "/admin/ubicaciones" else _HIDE
    page_pois = _SHOW if pathname == "/admin/pois" else _HIDE

    if not any(
        pathname.startswith(p) for p in ("/admin/usuarios", "/admin/ubicaciones", "/admin/pois")
    ):
        page_usuarios = _SHOW

    return (
        _CONTAINER_ADMIN,
        _HIDE,
        _SHOW,
        page_usuarios,
        page_ubicaciones,
        page_pois,
        _nav("/admin/usuarios"),
        _nav("/admin/ubicaciones"),
        _nav("/admin/pois"),
    )
