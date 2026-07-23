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
        # SVG placeholder incluido en assets/. Reemplaza con el logo oficial PNG si lo tienes.
        logo_asset="/assets/logo_miniso.svg",
        palette=(
            "#E60012",  # rojo Miniso — serie principal
            "#1A1A1A",  # negro Miniso
            "#FF6B6B",  # rojo claro
            "#4D4D4D",  # gris oscuro
            "#CC000F",  # rojo oscuro
            "#808080",  # gris medio
            "#FF3333",  # rojo vivo
            "#B3B3B3",  # gris claro
            "#FF9999",  # rojo pálido
            "#666666",  # gris
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
    r2, g2, b2 = _hex_to_rgb(b.secondary)
    return f"""
:root {{
  --bs-primary:          {b.primary};
  --bs-primary-rgb:      {r},{g},{b_val};
  --bs-link-color:       {b.primary};
  --bs-link-color-rgb:   {r},{g},{b_val};
  --bs-link-hover-color: {b.secondary};
}}
.text-primary  {{ color: {b.primary} !important; }}
.bg-primary    {{ background-color: {b.primary} !important; }}
.btn-primary   {{ background-color: {b.primary} !important;
                  border-color: {b.primary} !important; }}
.btn-primary:hover {{ background-color: {b.secondary} !important;
                      border-color: {b.secondary} !important; }}
.border-primary {{ border-color: {b.primary} !important; }}
.badge.bg-primary {{ background-color: {b.primary} !important; }}
""".strip()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
