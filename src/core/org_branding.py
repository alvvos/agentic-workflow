"""
Personalización visual por organización (branding).

Cada organización registrada puede definir:
  primary     — color principal de marca; reemplaza el azul Aitanna (#0052CC) en
                el chrome de la UI y en la primera serie de los gráficos.
  secondary   — color secundario / acento tipográfico.
  logo_asset  — ruta en /assets/ al logo de la org (PNG o SVG).
                Si el fichero no existe, la UI cae al logo global (/assets/logo.png).
  palette     — paleta de ≥10 colores para series multi-zona (primer color = primary).

NO se personalizan los colores que representan magnitudes o estados:
  C_SUCCESS (#28A745) — variación positiva
  C_DANGER  (#DC3545) — variación negativa / alerta
  C_AMBER   (#f39c12) — advertencia / neutral
  C_MUTED   (#6c757d) — texto secundario

Para añadir una organización nueva: copia el bloque de Miniso y adapta los campos.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrgBranding:
    org_id: str
    nombre: str
    primary: str  # color principal HEX (#RRGGBB)
    secondary: str  # color secundario HEX
    logo_asset: str  # ruta relativa a /assets/
    palette: tuple[str, ...]  # paleta multi-serie; ≥10 colores


# ── Paleta y branding por defecto (Aitanna/sin org) ──────────────────────────

_DEFAULT_PALETTE = (
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
)

_DEFAULT = OrgBranding(
    org_id="__default__",
    nombre="Default",
    primary="#0052CC",
    secondary="#2c3e50",
    logo_asset="/assets/logo.png",
    palette=_DEFAULT_PALETTE,
)


# ── Registro de organizaciones ────────────────────────────────────────────────

_REGISTRY: dict[str, OrgBranding] = {
    # ── Miniso España ─────────────────────────────────────────────────────────
    # UUID de org extraído de db/seed.py (Miniso España org).
    # Coloca el logo en assets/logo_miniso.png (PNG 400×120 px aprox., fondo blanco/transparente).
    "5c13b57d-782d-4458-911b-64cd40eebb55": OrgBranding(
        org_id="5c13b57d-782d-4458-911b-64cd40eebb55",
        nombre="Miniso",
        # Rojo corporativo Miniso — Pantone 2347 C
        primary="#E60012",
        secondary="#1A1A1A",
        logo_asset="/assets/logo_miniso.png",
        palette=(
            "#E60012",  # rojo Miniso primario
            "#1A1A1A",  # negro corporativo
            "#F4811F",  # naranja terracota
            "#8E44AD",  # violeta
            "#16A085",  # verde jade
            "#2980B9",  # azul acero
            "#D35400",  # siena
            "#6C3483",  # púrpura oscuro
            "#148F77",  # verde oscuro
            "#4D4D4D",  # gris carbón
        ),
    ),
}


# ── API pública ───────────────────────────────────────────────────────────────


def get_org_branding(org_id: str | None) -> OrgBranding:
    """Devuelve el branding registrado para org_id, o el branding por defecto."""
    return _REGISTRY.get(org_id or "", _DEFAULT)


def get_branding_from_locs(locs: list[str]) -> OrgBranding:
    """Deriva el branding a partir de una lista de ubicacion_id consultando la DB."""
    if not locs:
        return _DEFAULT
    try:
        from src.db.store import get_conn

        row = (
            get_conn()
            .execute(
                "SELECT org_id FROM ubicaciones WHERE ubicacion_id = %s LIMIT 1",
                [locs[0]],
            )
            .fetchone()
        )
        return get_org_branding(row[0] if row else None)
    except Exception:
        return _DEFAULT


def branding_css(b: OrgBranding) -> str:
    """
    Genera el bloque CSS que sobreescribe las custom properties de Bootstrap 5
    con los colores de la org. Se inyecta en un <style> de la página.
    """
    r, g, b_val = _hex_to_rgb(b.primary)
    h = b.primary.lstrip("#")
    rd = int(int(h[0:2], 16) * 0.75)
    gd = int(int(h[2:4], 16) * 0.75)
    bd = int(int(h[4:6], 16) * 0.75)
    primary_dark = f"#{rd:02x}{gd:02x}{bd:02x}"
    rgb = f"{r},{g},{b_val}"
    return f"""
:root {{
  --bs-primary:          {b.primary};
  --bs-primary-rgb:      {rgb};
  --bs-link-color:       {b.primary};
  --bs-link-color-rgb:   {rgb};
  --bs-link-hover-color: {b.secondary};
  --brand-primary:       {b.primary};
  --brand-primary-rgb:   {rgb};
  --brand-secondary:     {b.secondary};
  --brand-dark:          {primary_dark};
}}
/* Bootstrap utilities */
.text-primary  {{ color: {b.primary} !important; }}
.bg-primary    {{ background-color: {b.primary} !important; }}
.border-primary {{ border-color: {b.primary} !important; }}
.badge.bg-primary {{ background-color: {b.primary} !important; }}
/* Buttons */
.btn-primary {{ background-color: {b.primary} !important; border-color: {b.primary} !important; }}
.btn-primary:hover {{ background-color: {primary_dark} !important; border-color: {primary_dark} !important; }}
.btn-primary:focus {{ box-shadow: 0 0 0 0.25rem rgba({rgb},0.25) !important; }}
.btn-outline-primary {{ color: {b.primary} !important; border-color: {b.primary} !important; }}
.btn-outline-primary:hover {{ background-color: {b.primary} !important; color: white !important; border-color: {b.primary} !important; }}
.btn-outline-primary:focus {{ box-shadow: 0 0 0 0.25rem rgba({rgb},0.25) !important; }}
/* Form controls (RadioItems, Checklist, DatePicker focus) */
.form-check-input:checked {{ background-color: {b.primary} !important; border-color: {b.primary} !important; }}
.form-check-input:focus {{ box-shadow: 0 0 0 0.25rem rgba({rgb},0.25) !important; border-color: {b.primary} !important; }}
.form-control:focus {{ border-color: {b.primary} !important; box-shadow: 0 0 0 0.25rem rgba({rgb},0.25) !important; }}
.form-select:focus {{ border-color: {b.primary} !important; box-shadow: 0 0 0 0.25rem rgba({rgb},0.25) !important; }}
/* Accordion — estado PM (cabeceras cerradas = color marca; abiertas = tint suave) */
.pm-acordeon .accordion-button.collapsed {{ background-color: {b.primary} !important; }}
.pm-acordeon .accordion-button:not(.collapsed) {{ background-color: rgba({rgb},0.06) !important; box-shadow: inset 0 -1px 0 rgba({rgb},0.12) !important; }}
/* Accordion genérico Bootstrap */
.accordion-button:not(.collapsed) {{ color: {b.primary} !important; }}
/* Tab menu */
.custom-tabs .tab--selected {{ color: {b.primary} !important; border-bottom-color: {b.primary} !important; }}
.custom-tabs .tab:not(.tab--selected):hover {{ color: {b.primary} !important; border-bottom-color: rgba({rgb},0.35) !important; }}
/* Sidebar card top accent */
.sidebar-accent-card {{ border-top-color: {b.primary} !important; }}
/* Chat FAB — overrides the hardcoded inline gradient */
#chat-fab {{ background: linear-gradient(135deg, {b.primary} 0%, {primary_dark} 100%) !important; box-shadow: 0 4px 18px rgba({rgb},0.40) !important; }}
#chat-fab:hover {{ box-shadow: 0 8px 28px rgba({rgb},0.50) !important; }}
/* Chat elements */
.chat-bubble-user {{ background: {b.primary} !important; }}
.chat-modal-content .fa-robot {{ color: {b.primary} !important; }}
/* Dropdown Select (Dash/React-Select) open border */
.Select.is-open > .Select-control {{ border-color: {b.primary} !important; box-shadow: 0 0 0 0.18rem rgba({rgb},0.20) !important; }}
/* Hover tints for mention list and chat conversation list */
.mention-option-item:hover {{ background-color: rgba({rgb},0.08) !important; }}
.chat-conv-item:hover {{ background-color: rgba({rgb},0.06) !important; border-left-color: rgba({rgb},0.35) !important; }}
""".strip()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
