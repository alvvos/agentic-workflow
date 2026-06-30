"""
Theme constants — colores y paletas compartidas por todos los renderers.

Este módulo centraliza las constantes de color y configuración visual que
antes estaban duplicadas en cada renderer (health_check, geo_panel, etc.).
Cualquier nuevo renderer debe importar de aquí en lugar de redefinir.
"""

C_PRIMARY = "#0052CC"
C_SUCCESS = "#28A745"
C_DANGER = "#DC3545"
C_AMBER = "#f39c12"
C_DARK = "#2c3e50"
C_MUTED = "#6c757d"
C_GRID = "#f0f0f0"

CFG_GRAPH = {"displayModeBar": False, "responsive": True}

PALETA_PM = [
    "#0052CC",
    "#E67E22",
    "#27AE60",
    "#8E44AD",
    "#E74C3C",
    "#17A2B8",
    "#F39C12",
    "#2ECC71",
    "#9B59B6",
    "#C0392B",
    "#1ABC9C",
    "#D35400",
    "#2980B9",
    "#16A085",
    "#7D3C98",
]
