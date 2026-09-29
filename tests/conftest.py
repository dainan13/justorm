"""Shared pytest fixtures for the justorm test suite.

The test suite is organised in two layers:

* **Pure tests** (``test_builder.py``, ``test_renderer.py``) exercise the
  builder and renderer without touching a database.  They use a tiny
  in-memory recorder that pretends to be a cursor, so they run
  everywhere.
* **Integration tests** (``test_psycopg.py``, ``test_psycopg2.py``,
  ``test_pymysql.py``, ``test_sqlite.py``) run against a real database.
  They are opt-in per driver and skip automatically when the driver or
  the server is not available.

Connection parameters are read from environment variables:

* ``JUSTORM_PG_DSN``    — PostgreSQL DSN for psycopg (v3).
* ``JUSTORM_PG2_DSN``   — PostgreSQL DSN for psycopg2.
* ``JUSTORM_MYSQL_DSN`` — MySQL DSN for PyMySQL.
* ``JUSTORM_SQLITE_PATH`` — SQLite database file.  If unset,
                            ``:memory:`` is used.

Cursor creation
---------------

The driver-specific justorm cursor classes are plugged into the
connections here, once per fixture, so that individual tests can call
``conn.cursor()`` without arguments:

* psycopg3 and psycopg2 accept a ``cursor_factory`` keyword on
  ``connect()``; the factory is called with the connection and must
  return a cursor instance.  ``justorm.psycopg.Cursor`` and
  ``justorm.psycopg2.Cursor`` satisfy that.
* PyMySQL accepts the cursor class as the first positional argument to
  ``Connection.cursor()``.  We set it per call, because PyMySQL's
  ``connect()`` does not take a cursor factory.
* SQLite is special: ``sqlite3.Cursor`` cannot be subclassed, so the
  justorm wrapper is constructed directly from the connection.
"""

from __future__ import annotations

import importlib
import os
import sqlite3
from typing import Iterator, Optional
from urllib.parse import urlparse

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_import(module: str) -> Optional[object]:
    try:
        return importlib.import_module(module)
    except ImportError:
        return None


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    return value if value else None


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    dsn = _env("JUSTORM_PG_DSN")
    if dsn is None:
        pytest.skip("JUSTORM_PG_DSN is not set")
    return dsn


@pytest.fixture(scope="session")
def pg2_dsn() -> str:
    dsn = _env("JUSTORM_PG2_DSN")
    if dsn is None:
        pytest.skip("JUSTORM_PG2_DSN is not set")
    return dsn


@pytest.fixture(scope="session")
def psycopg_module() -> object:
    module = _try_import("psycopg")
    if module is None:
        pytest.skip("psycopg is not installed")
    return module


@pytest.fixture(scope="session")
def psycopg2_module() -> object:
    module = _try_import("psycopg2")
    if module is None:
        pytest.skip("psycopg2 is not installed")
    return module


def _reset_pg_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS justorm_test CASCADE")
        cur.execute("CREATE SCHEMA justorm_test")
        cur.execute("SET search_path TO justorm_test")
    conn.commit()


def _drop_pg_schema(conn) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS justorm_test CASCADE")
        conn.commit()
    except Exception:  # pragma: no cover - best-effort cleanup
        try:
            conn.rollback()
        except Exception:
            pass


@pytest.fixture()
def pg_conn(psycopg_module: object, pg_dsn: str) -> Iterator[object]:
    """A live psycopg (v3) connection with a scratch schema.

    The connection is created with ``cursor_factory=justorm.psycopg.Cursor``
    so that ``conn.cursor()`` returns a justorm cursor.
    """
    psycopg = psycopg_module
    import justorm.psycopg

    conn = psycopg.connect(
        pg_dsn, cursor_factory=justorm.psycopg.Cursor
    )
    try:
        _reset_pg_schema(conn)
        yield conn
    finally:
        _drop_pg_schema(conn)
        conn.close()


@pytest.fixture()
def pg_conn2(psycopg2_module: object, pg2_dsn: str) -> Iterator[object]:
    """A live psycopg2 connection with a scratch schema."""
    psycopg2 = psycopg2_module
    import justorm.psycopg2

    conn = psycopg2.connect(
        pg2_dsn, cursor_factory=justorm.psycopg2.Cursor
    )
    try:
        _reset_pg_schema(conn)
        yield conn
    finally:
        _drop_pg_schema(conn)
        conn.close()


# ---------------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mysql_dsn() -> str:
    dsn = _env("JUSTORM_MYSQL_DSN")
    if dsn is None:
        pytest.skip("JUSTORM_MYSQL_DSN is not set")
    return dsn


@pytest.fixture(scope="session")
def pymysql_module() -> object:
    module = _try_import("pymysql")
    if module is None:
        pytest.skip("PyMySQL is not installed")
    return module


def _parse_mysql_dsn(dsn: str) -> dict:
    parts = urlparse(dsn)
    if parts.scheme not in ("mysql", "mariadb"):
        raise ValueError(
            f"unsupported MySQL DSN scheme: {parts.scheme!r}"
        )
    kwargs: dict = {}
    if parts.hostname:
        kwargs["host"] = parts.hostname
    if parts.port:
        kwargs["port"] = parts.port
    if parts.username:
        kwargs["user"] = parts.username
    if parts.password:
        kwargs["password"] = parts.password
    if parts.path and parts.path != "/":
        kwargs["database"] = parts.path.lstrip("/")
    return kwargs


def _mysql_admin_kwargs(kwargs: dict) -> dict:
    out = dict(kwargs)
    out.pop("database", None)
    return out


def _reset_mysql_database(pymysql, kwargs: dict) -> None:
    db_name = kwargs.get("database", "justorm_test")
    admin = pymysql.connect(**_mysql_admin_kwargs(kwargs))
    try:
        with admin.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
            cur.execute(f"CREATE DATABASE `{db_name}`")
        admin.commit()
    finally:
        admin.close()


@pytest.fixture()
def mysql_conn(pymysql_module: object, mysql_dsn: str) -> Iterator[object]:
    """A live PyMySQL connection with a fresh database."""
    pymysql = pymysql_module
    kwargs = _parse_mysql_dsn(mysql_dsn)
    _reset_mysql_database(pymysql, kwargs)
    conn = pymysql.connect(**kwargs)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def sqlite_module() -> object:
    module = _try_import("sqlite3")
    if module is None:  # pragma: no cover - sqlite3 is always available
        pytest.skip("sqlite3 is not available")
    return module


def _drop_all_sqlite_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        for (name,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{name}"')
        conn.commit()
    finally:
        cur.close()


@pytest.fixture()
def sqlite_conn(sqlite_module: object) -> Iterator[object]:
    """A fresh SQLite connection with an empty database."""
    sqlite3 = sqlite_module
    path = _env("JUSTORM_SQLITE_PATH") or ":memory:"
    conn = sqlite3.connect(path)
    try:
        _drop_all_sqlite_tables(conn)
        yield conn
    finally:
        conn.close()
