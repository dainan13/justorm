"""Shared pytest fixtures for the justorm test suite.

The test suite is organised in two layers:

* **Pure tests** (``test_builder.py``, ``test_renderer.py``,
  ``test_fetch.py``) exercise the builder and renderer without
  touching a database.  They use a tiny in-memory recorder that
  pretends to be a cursor, so they run everywhere.
* **Integration tests** (``test_psycopg.py``, ``test_psycopg2.py``,
  ``test_pymysql.py``, ``test_sqlite.py``, ``test_pymssql.py``,
  ``test_oracledb.py``) run against a real database.  They are
  opt-in per driver and skip automatically when the driver or the
  server is not available.

Connection parameters are read from environment variables:

* ``JUSTORM_PG_DSN``    — PostgreSQL DSN for psycopg (v3).
                           Example: ``postgresql://user:pw@localhost/test``
* ``JUSTORM_PG2_DSN``   — PostgreSQL DSN for psycopg2.
* ``JUSTORM_MYSQL_DSN`` — MySQL DSN for PyMySQL.
                           Example: ``mysql://user:pw@localhost/test``
* ``JUSTORM_MSSQL_DSN`` — SQL Server DSN for pymssql.
                           Example: ``mssql://user:pw@localhost/test``
* ``JUSTORM_ORACLE_DSN`` — Oracle DSN for python-oracledb.
                           Example: ``oracle://user:pw@localhost:1521/service``
* ``JUSTORM_SQLITE_PATH`` — SQLite database file.  If unset,
                            ``:memory:`` is used.

Cursor creation
---------------

The driver-specific justorm cursor classes are plugged into the
connections here, once per fixture, so that individual tests can call
``conn.cursor()`` without arguments:

* psycopg3 and psycopg2 accept a ``cursor_factory`` keyword on
  ``connect()``; the factory is called with the connection and must
  return a cursor instance.
* PyMySQL accepts the cursor class as the first positional argument
  to ``Connection.cursor()``.
* SQLite and pymssql are special: their cursor classes cannot be
  plugged in through the connection, so the justorm wrapper is
  constructed directly from the connection.
* python-oracledb's ``Cursor`` can be subclassed, but
  ``Connection.cursor()`` does not accept a replacement class;
  the justorm cursor is constructed directly from the connection.
"""

from __future__ import annotations

import importlib
import os
import sqlite3
from typing import Iterator, Optional
from urllib.parse import unquote, urlparse

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


def _quote_mssql(name: str) -> str:
    """Quote a SQL Server identifier with square brackets."""
    return "[" + name.replace("]", "]]") + "]"


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
    """A live psycopg (v3) connection with a scratch schema."""
    psycopg = psycopg_module
    import justorm.psycopg

    conn = psycopg.connect(pg_dsn, cursor_factory=justorm.psycopg.Cursor)
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

    conn = psycopg2.connect(pg2_dsn, cursor_factory=justorm.psycopg2.Cursor)
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
        kwargs["host"] = unquote(parts.hostname)
    if parts.port:
        kwargs["port"] = parts.port
    if parts.username:
        kwargs["user"] = unquote(parts.username)
    if parts.password:
        kwargs["password"] = unquote(parts.password)
    if parts.path and parts.path != "/":
        kwargs["database"] = unquote(parts.path.lstrip("/"))
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
# SQL Server (pymssql)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mssql_dsn() -> str:
    dsn = _env("JUSTORM_MSSQL_DSN")
    if dsn is None:
        pytest.skip("JUSTORM_MSSQL_DSN is not set")
    return dsn


@pytest.fixture(scope="session")
def pymssql_module() -> object:
    module = _try_import("pymssql")
    if module is None:
        pytest.skip("pymssql is not installed")
    return module


def _parse_mssql_dsn(dsn: str) -> dict:
    """Parse a ``mssql://user:pw@host:port/db`` DSN into pymssql kwargs."""
    parts = urlparse(dsn)
    if parts.scheme not in ("mssql", "sqlserver"):
        raise ValueError(
            f"unsupported MSSQL DSN scheme: {parts.scheme!r}"
        )
    kwargs: dict = {}
    if parts.hostname:
        kwargs["server"] = unquote(parts.hostname)
    if parts.port:
        kwargs["port"] = parts.port
    if parts.username:
        kwargs["user"] = unquote(parts.username)
    if parts.password:
        kwargs["password"] = unquote(parts.password)
    if parts.path and parts.path != "/":
        kwargs["database"] = unquote(parts.path.lstrip("/"))
    return kwargs


#: The schema the SQL Server tests create and drop per test.  It lives
#: inside the database named in the DSN; schema and database are two
#: separate layers in SQL Server, so the names can coincide.
_MSSQL_SCHEMA = "justorm_test"


def _mssql_tables(cur) -> list:
    cur.execute(
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
        f"WHERE TABLE_SCHEMA = '{_MSSQL_SCHEMA}'"
    )
    return [row[0] for row in cur.fetchall()]


def _reset_mssql_schema(conn) -> None:
    """Drop and recreate the scratch schema.

    SQL Server's ``DROP SCHEMA`` does not cascade, so every object
    inside it has to be dropped first.  We drop tables one by one,
    then the schema, then recreate it.
    """
    cur = conn.cursor()
    try:
        for name in _mssql_tables(cur):
            cur.execute(
                f"DROP TABLE [{_MSSQL_SCHEMA}].{_quote_mssql(name)}"
            )
        cur.execute(
            f"""
            IF SCHEMA_ID('{_MSSQL_SCHEMA}') IS NOT NULL
                DROP SCHEMA [{_MSSQL_SCHEMA}]
            """
        )
        cur.execute(f"CREATE SCHEMA [{_MSSQL_SCHEMA}]")
    finally:
        cur.close()


def _drop_mssql_schema(conn) -> None:
    """Best-effort cleanup of the scratch schema."""
    try:
        cur = conn.cursor()
        try:
            for name in _mssql_tables(cur):
                cur.execute(
                    f"DROP TABLE [{_MSSQL_SCHEMA}].{_quote_mssql(name)}"
                )
            cur.execute(
                f"""
                IF SCHEMA_ID('{_MSSQL_SCHEMA}') IS NOT NULL
                    DROP SCHEMA [{_MSSQL_SCHEMA}]
                """
            )
        finally:
            cur.close()
    except Exception:  # pragma: no cover - best-effort cleanup
        pass


@pytest.fixture()
def mssql_conn(pymssql_module: object, mssql_dsn: str) -> Iterator[object]:
    """A live pymssql connection with a scratch schema.

    pymssql defaults to manual commit; we turn autocommit on so that
    DDL and schema resets are visible to the rest of the session
    without an explicit ``conn.commit()``.
    """
    pymssql = pymssql_module
    kwargs = _parse_mssql_dsn(mssql_dsn)
    conn = pymssql.connect(**kwargs)
    conn.autocommit(True)
    try:
        _reset_mssql_schema(conn)
        yield conn
    finally:
        _drop_mssql_schema(conn)
        try:
            conn.close()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass


# ---------------------------------------------------------------------------
# Oracle (python-oracledb)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def oracle_dsn() -> str:
    dsn = _env("JUSTORM_ORACLE_DSN")
    if dsn is None:
        pytest.skip("JUSTORM_ORACLE_DSN is not set")
    return dsn


@pytest.fixture(scope="session")
def oracledb_module() -> object:
    module = _try_import("oracledb")
    if module is None:
        pytest.skip("python-oracledb is not installed")
    return module


def _parse_oracle_dsn(dsn: str) -> dict:
    """Parse an ``oracle://user:pw@host:port/service`` DSN.

    python-oracledb wants the connect identifier as a single
    ``host:port/service`` string in the ``dsn`` keyword, plus ``user``
    and ``password`` separately.  The service name is the PDB (or SID)
    at the end of the URL path.
    """
    parts = urlparse(dsn)
    if parts.scheme != "oracle":
        raise ValueError(
            f"unsupported Oracle DSN scheme: {parts.scheme!r}"
        )
    kwargs: dict = {}
    if parts.username:
        kwargs["user"] = unquote(parts.username)
    if parts.password:
        kwargs["password"] = unquote(parts.password)
    host = parts.hostname or "localhost"
    port = parts.port or 1521
    service = unquote(parts.path.lstrip("/")) if parts.path else ""
    if not service:
        raise ValueError("Oracle DSN is missing a service name")
    kwargs["dsn"] = f"{host}:{port}/{service}"
    return kwargs


def _oracle_tables(conn) -> list:
    """Return the names of every table owned by the current user."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT table_name FROM user_tables")
        return [row[0] for row in cur.fetchall()]
    finally:
        cur.close()


def _reset_oracle_schema(conn) -> None:
    """Drop every table in the current user's schema.

    Oracle treats the user as the schema; ``user_tables`` lists the
    tables the connected user owns.  Table names come back upper-cased
    (because Oracle folds unquoted identifiers), so we drop them with
    their real, quoted names.
    """
    for name in _oracle_tables(conn):
        cur = conn.cursor()
        try:
            cur.execute(f'DROP TABLE "{name}" CASCADE CONSTRAINTS')
        finally:
            cur.close()
    conn.commit()


@pytest.fixture()
def oracle_conn(oracledb_module: object, oracle_dsn: str) -> Iterator[object]:
    """A live python-oracledb connection with an empty schema.

    The schema is the connected user's own schema (Oracle user ==
    schema).  Every test starts with no tables; the fixture drops
    everything at setup and again at teardown.
    """
    oracledb = oracledb_module
    kwargs = _parse_oracle_dsn(oracle_dsn)
    conn = oracledb.connect(**kwargs)
    # Autocommit keeps DDL and DML visible immediately, since the tests
    # do not manage transactions themselves.
    conn.autocommit = True
    try:
        _reset_oracle_schema(conn)
        yield conn
    finally:
        try:
            _reset_oracle_schema(conn)
        except Exception:  # pragma: no cover - best-effort cleanup
            pass
        conn.close()


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