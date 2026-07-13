"""
Agente 1 — Quality Gate de onboarding.

Valida una ubicación recién detectada antes de lanzar el pipeline de ingesta.
Geocodifica si faltan coordenadas y verifica que el resultado sea coherente
con el país declarado. Si las coordenadas están fuera del bounding box del país,
las anula en DB para proteger al resto del sistema (prefetch, ML) de datos corruptos.

Uso directo:
    from src.onboarding.quality_gate import validar
    result = validar(location_uuid)
    if result.ok:
        ...
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import requests

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_UA = "agentic-workflow/1.0 (alvaro.salis@69summer.com)"

# (lat_min, lat_max, lon_min, lon_max) por código ISO-2
_BBOX: dict[str, tuple[float, float, float, float]] = {
    "ES": (35.0, 44.5, -10.0, 5.0),
    "MX": (14.0, 33.0, -118.0, -86.0),
    "US": (24.0, 50.0, -125.0, -66.0),
    "FR": (41.0, 52.0, -5.5, 10.0),
    "DE": (47.0, 55.5, 5.5, 15.5),
    "GB": (49.5, 61.0, -10.5, 2.0),
    "IT": (35.5, 47.5, 6.5, 19.5),
    "PT": (36.5, 42.5, -9.5, -6.0),
}

# Prefijos que indican nombre comercial antes de la vía postal
_PREFIJOS_COMERCIALES = (
    "c.c.",
    "cc ",
    "centro comercial",
    "pc ",
    "plaza comercial",
    "c.c ",
    "c. c.",
    "galería",
    "galeria",
    "cc.",
    "local ",
)


@dataclass
class QualityResult:
    location_uuid: str
    nombre: str
    ok: bool
    issues: list[str] = field(default_factory=list)  # bloquean el pipeline
    warnings: list[str] = field(default_factory=list)  # se loguean pero no bloquean
    geocoded: bool = False
    lat: float | None = None
    lon: float | None = None


def _limpiar(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace("\xa0", " ")).strip()


def _candidatos(nombre, address, city, post_code):
    """Genera hasta 3 queries para Nominatim, de más a menos específica."""
    parts = [_limpiar(x) for x in (address, city, post_code)]
    address, city, post_code = parts

    candidatos = []
    q = ", ".join(p for p in (address, city, post_code) if p)
    if q:
        candidatos.append(q)
    if address and address not in candidatos:
        candidatos.append(address)
    q3 = ", ".join(p for p in (_limpiar(nombre), city) if p)
    if q3 and q3 not in candidatos:
        candidatos.append(q3)
    return candidatos


def _geocodificar(nombre, address, city, post_code, pais_codigo, timeout=6):
    """Intenta geocodificar con hasta 3 queries. Devuelve (lat, lon) o (None, None)."""
    cc = (
        pais_codigo.upper()
        if pais_codigo and len(pais_codigo) == 2 and pais_codigo != "XX"
        else None
    )
    for i, query in enumerate(_candidatos(nombre, address, city, post_code)):
        if i > 0:
            time.sleep(1)
        try:
            params = {"q": query, "format": "json", "limit": 1}
            if cc:
                params["countrycodes"] = cc
            r = requests.get(
                _NOMINATIM_URL,
                params=params,
                headers={"User-Agent": _NOMINATIM_UA},
                timeout=timeout,
            )
            results = r.json()
            if results:
                return float(results[0]["lat"]), float(results[0]["lon"])
        except Exception:
            pass
        time.sleep(1)
    return None, None


def _dentro_bbox(lat: float, lon: float, pais_codigo: str) -> bool:
    bbox = _BBOX.get(pais_codigo)
    if not bbox:
        return True  # país sin bbox definido → no validamos
    lat_min, lat_max, lon_min, lon_max = bbox
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def validar(location_uuid: str) -> QualityResult:
    """
    Valida y, si es necesario, geocodifica una ubicación.

    Checks duros (ok=False, pipeline no avanza):
      - pais_codigo inválido o 'XX'
      - sin lat/lon después de intentar geocodificar
      - coordenadas fuera del bounding box del país

    Warnings (loguean pero no bloquean):
      - direccion comienza con nombre comercial
      - codigo_postal vacío
      - ciudad vacía
    """
    from src.db.store import get_conn

    conn = get_conn()

    row = conn.execute(
        "SELECT nombre, direccion, ciudad, provincia, pais_codigo, "
        "codigo_postal, lat, lon "
        "FROM ubicaciones WHERE ubicacion_id = ?",
        [location_uuid],
    ).fetchone()

    if not row:
        return QualityResult(
            location_uuid=location_uuid,
            nombre="?",
            ok=False,
            issues=[f"ubicacion_id '{location_uuid}' no encontrado en ubicaciones"],
        )

    nombre, direccion, ciudad, provincia, pais_codigo, cp, lat, lon = row
    issues: list[str] = []
    warnings: list[str] = []

    # ── Checks de metadatos ────────────────────────────────────────────────────

    pais_efectivo = pais_codigo or ""
    if not pais_efectivo or pais_efectivo == "XX":
        issues.append(
            f"pais_codigo inválido ('{pais_efectivo}') — "
            "revisar country_code en Aitanna o añadir entrada en _COUNTRY_MAP"
        )

    if not direccion or not _limpiar(direccion):
        issues.append("direccion vacía — sin dirección la geocodificación no puede ejecutarse")
    else:
        dir_lower = _limpiar(direccion).lower()
        if any(dir_lower.startswith(p) for p in _PREFIJOS_COMERCIALES):
            warnings.append(
                f"direccion comienza con nombre comercial ('{direccion[:70]}') — "
                "puede reducir precisión de geocodificación"
            )

    if not cp or not _limpiar(cp):
        warnings.append("codigo_postal vacío")

    if not ciudad or not _limpiar(ciudad):
        warnings.append("ciudad vacía")

    # ── Geocodificación si faltan coordenadas ──────────────────────────────────

    geocoded = False
    if not (lat and lon) and not issues:
        lat, lon = _geocodificar(
            nombre=nombre or "",
            address=direccion or "",
            city=ciudad or provincia or "",
            post_code=cp or "",
            pais_codigo=pais_efectivo,
        )
        if lat is not None:
            conn.execute(
                "UPDATE ubicaciones SET lat = ?, lon = ? WHERE ubicacion_id = ?",
                [round(lat, 6), round(lon, 6), location_uuid],
            )
            geocoded = True
        else:
            issues.append(
                "geocodificación fallida — sin coordenadas la ubicación queda excluida "
                "de prefetch, Esri y ML hasta que se corrija la dirección manualmente"
            )

    # ── Validación de coordenadas contra bounding box ─────────────────────────

    if lat and lon and pais_efectivo and pais_efectivo != "XX":
        if not _dentro_bbox(lat, lon, pais_efectivo):
            issues.append(
                f"coordenadas ({lat:.5f}, {lon:.5f}) fuera del bounding box de {pais_efectivo} "
                f"— probable error de geocodificación; corregir manualmente la dirección"
            )
            # Anular coordenadas erróneas para proteger prefetch y ML
            conn.execute(
                "UPDATE ubicaciones SET lat = NULL, lon = NULL WHERE ubicacion_id = ?",
                [location_uuid],
            )
            lat = lon = None

    return QualityResult(
        location_uuid=location_uuid,
        nombre=nombre or "",
        ok=len(issues) == 0,
        issues=issues,
        warnings=warnings,
        geocoded=geocoded,
        lat=lat,
        lon=lon,
    )
