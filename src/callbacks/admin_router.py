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


# ── Security layer (server-side — checks is_admin()) ─────────────────────────


@app.callback(
    Output("main-container", "style"),
    Output("dashboard-container", "style"),
    Output("admin-container", "style"),
    Input("url", "pathname"),
)
def route_security(pathname):
    if not pathname or not pathname.startswith("/admin"):
        return _CONTAINER_DASHBOARD, _SHOW, _HIDE
    if not is_admin():
        return _CONTAINER_DASHBOARD, _SHOW, _HIDE
    return _CONTAINER_ADMIN, _HIDE, _SHOW


# ── Page switching (clientside — instantaneous, no round-trip) ────────────────

app.clientside_callback(
    """
    function(pathname) {
        var SHOW = {};
        var HIDE = {'display': 'none'};
        var NAV_ACTIVE = 'admin-nav-link d-flex align-items-center px-3 py-2 mb-1 rounded-3 text-decoration-none active';
        var NAV_BASE  = 'admin-nav-link d-flex align-items-center px-3 py-2 mb-1 rounded-3 text-decoration-none';

        if (!pathname || !pathname.startsWith('/admin')) {
            return [HIDE, HIDE, HIDE, NAV_BASE, NAV_BASE, NAV_BASE];
        }

        var isUsuarios   = pathname === '/admin/usuarios'   || pathname === '/admin';
        var isUbicaciones = pathname === '/admin/ubicaciones';
        var isPois        = pathname === '/admin/pois';

        // fallback: mostrar usuarios si no hay subpágina reconocida
        if (!isUsuarios && !isUbicaciones && !isPois) {
            isUsuarios = true;
        }

        return [
            isUsuarios    ? SHOW : HIDE,
            isUbicaciones ? SHOW : HIDE,
            isPois        ? SHOW : HIDE,
            pathname.startsWith('/admin/usuarios')    ? NAV_ACTIVE : NAV_BASE,
            pathname.startsWith('/admin/ubicaciones') ? NAV_ACTIVE : NAV_BASE,
            pathname.startsWith('/admin/pois')        ? NAV_ACTIVE : NAV_BASE,
        ];
    }
    """,
    Output("admin-page-usuarios", "style"),
    Output("admin-page-ubicaciones", "style"),
    Output("admin-page-pois", "style"),
    Output("admin-nav-usuarios", "className"),
    Output("admin-nav-ubicaciones", "className"),
    Output("admin-nav-pois", "className"),
    Input("url", "pathname"),
)
