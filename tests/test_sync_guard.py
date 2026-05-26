"""
Tests del mecanismo de lock de sincronización (_acquire_sync_lock / _release_sync_lock).

Objetivo: garantizar que el callback ejecutar_sincronizacion no puede ejecutarse
de forma concurrente ni relanzarse en un reconect de Dash mientras ya hay un sync
en curso.
"""
import os
import time
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.callbacks.sync import _acquire_sync_lock, _release_sync_lock


def test_acquire_crea_lock(tmp_path):
    lock = str(tmp_path / "dataset_test.lock")
    assert _acquire_sync_lock(lock) is True
    assert os.path.exists(lock)


def test_acquire_bloquea_segunda_llamada(tmp_path):
    lock = str(tmp_path / "dataset_test.lock")
    _acquire_sync_lock(lock)
    assert _acquire_sync_lock(lock) is False


def test_release_elimina_lock(tmp_path):
    lock = str(tmp_path / "dataset_test.lock")
    _acquire_sync_lock(lock)
    _release_sync_lock(lock)
    assert not os.path.exists(lock)


def test_lock_expirado_permite_nueva_adquisicion(tmp_path):
    lock = str(tmp_path / "dataset_test.lock")
    _acquire_sync_lock(lock)
    # Simula un lock antiguo modificando su mtime
    stale_mtime = time.time() - 700  # 700s > max_age=600
    os.utime(lock, (stale_mtime, stale_mtime))
    assert _acquire_sync_lock(lock, max_age=600) is True


def test_release_es_idempotente(tmp_path):
    lock = str(tmp_path / "dataset_test.lock")
    _release_sync_lock(lock)  # no debe lanzar excepción si no existe


def test_lock_fresco_bloquea_incluso_si_antiguo_minutos(tmp_path):
    lock = str(tmp_path / "dataset_test.lock")
    _acquire_sync_lock(lock)
    # Lock de 5 minutos, aún dentro del max_age
    recent_mtime = time.time() - 300
    os.utime(lock, (recent_mtime, recent_mtime))
    assert _acquire_sync_lock(lock, max_age=600) is False
