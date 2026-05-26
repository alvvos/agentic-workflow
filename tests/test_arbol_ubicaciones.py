"""
Tests de actualizar_arbol_ubicaciones.py:
  - _limpiar()           — limpieza de strings con NBSP y espacios
  - _candidatos_query()  — generación de queries Nominatim en orden correcto
  - _cargar_memorias()   — preservación de lat/lon y zoneType desde JSON existente
"""
import json
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data_ingestion.actualizar_arbol_ubicaciones import (
    _limpiar,
    _candidatos_query,
    _cargar_memorias,
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


# ── _cargar_memorias ──────────────────────────────────────────────────────────

def _json_fixture(tmp_path, data):
    p = tmp_path / "ubicaciones.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_cargar_memorias_preserva_lat_lon(tmp_path):
    datos = [{"uuid": "org1", "name": "Org", "locations": [
        {"uuid": "loc1", "name": "Tienda", "lat": 40.4, "lon": -3.7,
         "address": "Calle 1", "zones": []}
    ]}]
    ruta = _json_fixture(tmp_path, datos)
    locs, zones = _cargar_memorias(ruta)
    assert "loc1" in locs
    assert locs["loc1"]["lat"] == 40.4
    assert locs["loc1"]["lon"] == -3.7


def test_cargar_memorias_preserva_zonetype(tmp_path):
    datos = [{"uuid": "org1", "name": "Org", "locations": [
        {"uuid": "loc1", "name": "Tienda", "address": "x", "zones": [
            {"uuid": "z1", "zoneName": "Caja", "zoneType": "last_zone"},
            {"uuid": "z2", "zoneName": "Exterior"},
        ]}
    ]}]
    ruta = _json_fixture(tmp_path, datos)
    locs, zones = _cargar_memorias(ruta)
    assert zones["z1"] == "last_zone"
    assert "z2" not in zones


def test_cargar_memorias_sin_geo_no_registra_loc(tmp_path):
    datos = [{"uuid": "org1", "name": "Org", "locations": [
        {"uuid": "loc1", "name": "Tienda", "address": "x", "zones": []}
    ]}]
    ruta = _json_fixture(tmp_path, datos)
    locs, _ = _cargar_memorias(ruta)
    assert "loc1" not in locs


def test_cargar_memorias_archivo_inexistente():
    locs, zones = _cargar_memorias("/tmp/no_existe_nunca.json")
    assert locs == {}
    assert zones == {}
