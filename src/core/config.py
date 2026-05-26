import os
import dash
import dash_bootstrap_components as dbc

MODO_DESARROLLO = os.getenv("MODO_DESARROLLO", "false").lower() == "true"

dias_semana_es = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
orden_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.LUX, dbc.icons.FONT_AWESOME],
    suppress_callback_exceptions=True
)
app.title = "Panel Analítico Predictivo"

server = app.server
server.secret_key = os.getenv("SECRET_KEY", "dev-only-change-in-prod")
