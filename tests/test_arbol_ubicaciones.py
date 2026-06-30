"""
Tests de actualizar_arbol_ubicaciones.py:
  - _limpiar()           — limpieza de strings con NBSP y espacios
  - _candidatos_query()  — generación de queries Nominatim en orden correcto
  - _cargar_memorias()   — preservación de lat/lon y zoneType desde JSON existente
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data_ingestion.actualizar_arbol_ubicaciones import (
    _candidatos_query,
    _limpiar,
)

# ── _limpiar ──────────────────────────────────────────────────────────────────


def test_limpiar_elimina_nbsp():
    assert _limpiar("San Jaime\xa07\xa0") == "San Jaime 7"


def test_limpiar_colapsa_espacios_multiples():
    assert _limpiar("Calle   Mayor   3") == "Calle Mayor 3"


def test_limpiar_none_devuelve_vacio():
    assert _limpiar(None) == ""


def test_limpiar_strip_bordes():
    assert _limpiar("  Madrid  ") == "Madrid"


# ── _candidatos_query ─────────────────────────────────────────────────────────


def test_candidatos_query_incluye_todos_los_campos():
    qs = _candidatos_query("Tienda", "Calle Mayor 1", "Madrid", "28013", "España")
    # El primer candidato debe contener dirección + ciudad + CP + país
    assert "Calle Mayor 1" in qs[0]
    assert "Madrid" in qs[0]
    assert "28013" in qs[0]
    assert "España" in qs[0]


def test_candidatos_query_sin_city_usa_solo_address():
    qs = _candidatos_query("Tienda", "Calle Mayor 1, 28013 Madrid", "", "", "")
    assert any("Calle Mayor 1" in q for q in qs)


def test_candidatos_query_fallback_nombre_ciudad():
    qs = _candidatos_query("Gran Vía", "", "Madrid", "", "España")
    # Sin dirección, debe haber un candidato con el nombre de la tienda
    assert any("Gran Vía" in q for q in qs)


def test_candidatos_query_no_duplicados():
    qs = _candidatos_query("T", "Addr", "City", "12345", "Spain")
    assert len(qs) == len(set(qs))


def test_candidatos_query_todo_vacio_devuelve_lista_vacia():
    qs = _candidatos_query("", "", "", "", "")
    assert qs == []


# ── _cargar_memorias — eliminada en migración a PostgreSQL ────────────────────
# Los tests de esta función se eliminaron porque _cargar_memorias fue reemplazada
# por consultas directas a dim_ubicaciones/dim_zonas en la BD.
