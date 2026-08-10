import logging
import os

import dash
import dash_bootstrap_components as dbc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
)

MODO_DESARROLLO = os.getenv("MODO_DESARROLLO", "false").lower() == "true"

dias_semana_es = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo",
}
orden_dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# __file__ = src/core/config.py → subir dos niveles para llegar a la raíz del proyecto
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = dash.Dash(
    __name__,
    assets_folder=os.path.join(_PROJECT_ROOT, "assets"),
    external_stylesheets=[dbc.themes.LUX, dbc.icons.FONT_AWESOME],
    suppress_callback_exceptions=True,
    update_title=None,
)
app.title = "Reporting Aitanna"

server = app.server
_secret_key = os.getenv("SECRET_KEY")
if not _secret_key:
    if MODO_DESARROLLO:
        _secret_key = "dev-only-insecure-key"
    else:
        raise RuntimeError(
            "SECRET_KEY no está configurada. Define la variable de entorno antes de arrancar en producción."
        )
server.secret_key = _secret_key


@server.teardown_request
def _release_db_conn(exc):
    from src.db.store import close_conn

    close_conn()
