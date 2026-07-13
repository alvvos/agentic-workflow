"""
Shared pytest configuration.

Sets DB_POOL_TIMEOUT=2 so that tests without Docker fail fast (~2s) instead of
waiting the default 30s for the connection pool to give up.
"""

import os
import socket

import pytest

_DB_HOST = os.getenv("DB_HOST", "localhost")
_DB_PORT = int(os.getenv("DB_PORT", "5433"))

# Short pool timeout for tests — must be set BEFORE any code imports store.py
os.environ.setdefault("DB_POOL_TIMEOUT", "2")


def _db_reachable() -> bool:
    try:
        s = socket.create_connection((_DB_HOST, _DB_PORT), timeout=1)
        s.close()
        return True
    except OSError:
        return False


_DB_AVAILABLE: bool = _db_reachable()


@pytest.fixture(scope="session")
def db_available() -> bool:
    """True when the PostgreSQL instance is reachable. Use to skip DB-dependent tests."""
    return _DB_AVAILABLE
