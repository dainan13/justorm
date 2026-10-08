"""Integration tests for ``justorm.pymssql``.

These tests require a running SQL Server instance and the ``pymssql``
package.  Both are opt-in: set ``JUSTORM_MSSQL_DSN`` and install the
``pymssql`` extra.

SQL Server is where justorm's dialect-specific surface matters most:

* identifiers are quoted with square brackets,
* ``RETURNING`` is not available (the equivalent is ``OUTPUT``),
* upserts use ``MERGE``, which justorm does not model,
* ``DISTINCT ON`` and ``ILIKE`` are not available,
* ``FOR UPDATE`` is not available (row locking is done with table
  hints),
* a bare ``LIMIT`` maps to ``SELECT TOP n`` (which needs no
  ``ORDER BY``); ``LIMIT`` with ``OFFSET`` maps to
  ``OFFSET n ROWS FETCH NEXT m ROWS ONLY`` (which does),
* ``DEFAULT`` is accepted inside a ``VALUES`` list.

The shared builder logic is exercised in ``test_builder.py``; here we
check that SQL Server accepts the SQL justorm generates, and that the
things SQL Server does not have are rejected before they reach the
server.
"""

from __future__ import annotations

from collections import namedtuple

import pytest

pymssql = pytest.importorskip("pymssql")

import justorm.pymssql
from justorm import JustormDialectError, JustormError


pytestmark = pytest.mark.pymssql


# ---------------------------------------------------------------------------
# Schema-qualified table names
#
# The conftest fixture creates a ``justorm_test`` schema inside the
# ``justorm_test`` database.  Every table we create lives in that
# schema, and every query references it explicitly.  ``cur.table``
# accepts two parts, so ``cur.table("justorm_test", "users")`` works.
# ---------------------------------------------------------------------------

_SCHEMA = "justorm_test"


def _cursor(conn):
    return justorm.pymssql.Cursor(conn)


def _tbl(cur, name):
    return cur.table(_SCHEMA, name)


# ---------------------------------------------------------------------------
# Cursor identity and native surface
# ---------------------------------------------------------------------------


class TestCursorIdentity:
    def test_cursor_wraps_pymssql_cursor(self, mssql_conn):
        cur = _cursor(mssql_conn)
        try:
            # ``justorm.pymssql.Cursor`` wraps the driver cursor rather
            # than subclassing it; the inner cursor is a pymssql one.
            assert isinstance(cur._cursor, pymssql.Cursor)
        finally:
            cur.close()

    def test_dialect_name(self, mssql_conn):
        cur = _cursor(mssql_conn)
        try:
            assert cur.dialect_name == "pymssql"
        finally:
            cur.close()

    def test_native_execute_returns_cursor(self, mssql_conn):
        cur = _cursor(mssql_conn)
        try:
            # The wrapper returns the cursor from ``execute``, matching
            # psycopg3 / sqlite3, not pymssql's native rowcount.
            result = cur.execute("SELECT 1")
            assert result is cur
            assert cur.fetchone() == (1,)
        finally:
            cur.close()

    def test_table_named_like_a_cursor_attribute(self, mssql_conn):
        cur = _cursor(mssql_conn)
        try:
            assert callable(cur.execute)
            assert cur.table("execute") is not None
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def users_table(mssql_conn):
    """A small ``users`` table in the scratch schema."""
    cur = _cursor(mssql_conn)
    try:
        cur.execute(
            f"""
            CREATE TABLE [{_SCHEMA}].users (
                id     INT IDENTITY(1,1) PRIMARY KEY,
                name   NVARCHAR(64) NOT NULL,
                age    INT,
                active BIT NOT NULL DEFAULT 1,
                CONSTRAINT uq_users_name UNIQUE (name)
            )
            """
        )
        _tbl(cur, "users").insert(
            [
                {"name": "Alice", "age": 30, "active": 1},
                {"name": "Bob", "age": 25, "active": 1},
                {"name": "Carol", "age": 40, "active": 0},
            ]
        )
    finally:
        cur.close()
    return "users"


# ---------------------------------------------------------------------------
# fetch* with format=
# ---------------------------------------------------------------------------


class TestFetchFormat:
    def test_fetchone_default(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            cur.execute(
                f"SELECT id, name FROM [{_SCHEMA}].users ORDER BY id"
            )
            row = cur.fetchone()
            assert isinstance(row, tuple)
            assert row[1] == "Alice"
        finally:
            cur.close()

    def test_fetchone_dict(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            cur.execute(
                f"SELECT id, name FROM [{_SCHEMA}].users ORDER BY id"
            )
            row = cur.fetchone(format=dict)
            assert row == {"id": 1, "name": "Alice"}
        finally:
            cur.close()

    def test_fetchone_namedtuple(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            cur.execute(
                f"SELECT id, name FROM [{_SCHEMA}].users ORDER BY id"
            )
            row = cur.fetchone(format=namedtuple)
            assert row.id == 1
            assert row.name == "Alice"
        finally:
            cur.close()

    def test_fetchone_none_with_format(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            cur.execute(
                f"SELECT id FROM [{_SCHEMA}].users WHERE 1 = 0"
            )
            assert cur.fetchone(format=dict) is None
            assert cur.fetchone(format=namedtuple) is None
        finally:
            cur.close()

    def test_fetchmany_dict(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            cur.execute(
                f"SELECT id, name FROM [{_SCHEMA}].users ORDER BY id"
            )
            rows = cur.fetchmany(2, format=dict)
            assert rows == [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ]
        finally:
            cur.close()

    def test_fetchall_namedtuple(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            cur.execute(
                f"SELECT id, name FROM [{_SCHEMA}].users ORDER BY id"
            )
            rows = cur.fetchall(format=namedtuple)
            assert rows[2].name == "Carol"
        finally:
            cur.close()

    def test_bad_format_rejected(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            cur.execute(f"SELECT id FROM [{_SCHEMA}].users")
            with pytest.raises(JustormError):
                cur.fetchall(format=list)
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_row(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            row = _tbl(cur, "users").where(name="Alice").get()
            assert row == {
                "id": 1,
                "name": "Alice",
                "age": 30,
                "active": 1,
            }
        finally:
            cur.close()

    def test_get_missing_returns_none(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            assert _tbl(cur, "users").where(name="Nobody").get() is None
        finally:
            cur.close()

    def test_get_default(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            assert _tbl(cur, "users").where(name="Nobody").get(default={}) == {}
        finally:
            cur.close()

    def test_get_scalar(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            assert _tbl(cur, "users").where(name="Alice").get("name") == "Alice"
        finally:
            cur.close()

    def test_get_tuple(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            row = _tbl(cur, "users").where(name="Alice").get(("id", "name"))
            assert row == (1, "Alice")
        finally:
            cur.close()

    def test_get_rejects_key(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(JustormError):
                _tbl(cur, "users").where(name="Alice").get(key="id")
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_select_returns_dicts(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            rows = cur.query(
                f"SELECT id, name FROM [{_SCHEMA}].users ORDER BY id"
            )
            assert rows == [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
                {"id": 3, "name": "Carol"},
            ]
        finally:
            cur.close()

    def test_query_select_with_params(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            rows = cur.query(
                f"SELECT name FROM [{_SCHEMA}].users "
                f"WHERE age > %s ORDER BY id",
                [26],
            )
            assert rows == [{"name": "Alice"}, {"name": "Carol"}]
        finally:
            cur.close()

    def test_query_select_empty(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            assert (
                cur.query(
                    f"SELECT id FROM [{_SCHEMA}].users WHERE 1 = 0"
                )
                == []
            )
        finally:
            cur.close()

    def test_query_insert_returns_rowcount(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            result = cur.query(
                f"INSERT INTO [{_SCHEMA}].users (name, age) "
                f"VALUES (%s, %s)",
                ["Dave", 50],
            )
            # pymssql does not expose a real lastrowid; ``query`` falls
            # back to rowcount for INSERT statements.
            assert result == 1
        finally:
            cur.close()

    def test_query_update_returns_rowcount(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            result = cur.query(
                f"UPDATE [{_SCHEMA}].users SET age = %s WHERE age > %s",
                [99, 28],
            )
            assert result == 2
        finally:
            cur.close()

    def test_query_delete_returns_rowcount(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            result = cur.query(
                f"DELETE FROM [{_SCHEMA}].users WHERE name = %s",
                ["Bob"],
            )
            assert result == 1
        finally:
            cur.close()

    def test_query_ddl_returns_int(self, mssql_conn):
        cur = _cursor(mssql_conn)
        try:
            result = cur.query(
                f"CREATE TABLE [{_SCHEMA}].t (id INT)"
            )
            assert isinstance(result, int)
        finally:
            cur.close()

    def test_query_bad_sql_raises(self, mssql_conn):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(pymssql.Error):
                cur.query(f"SELECT * FROM [{_SCHEMA}].no_such_table")
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# SELECT
# ---------------------------------------------------------------------------


class TestSelect:
    def test_select_all(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            rows = _tbl(cur, "users").orderby("id").select()
            assert len(rows) == 3
            assert {r["name"] for r in rows} == {"Alice", "Bob", "Carol"}
        finally:
            cur.close()

    def test_identifier_quoting_uses_brackets(self, mssql_conn):
        cur = _cursor(mssql_conn)
        try:
            cur.execute(
                f"CREATE TABLE [{_SCHEMA}].[select] "
                f"([where] INT, [order] INT)"
            )
            cur.table(_SCHEMA, "select").append(
                **{"where": 1, "order": 2}
            )
            rows = cur.table(_SCHEMA, "select").select()
            assert rows == [{"where": 1, "order": 2}]
        finally:
            cur.close()

    def test_where_kwargs(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            rows = _tbl(cur, "users").where(name="Alice").select()
            assert len(rows) == 1
            assert rows[0]["age"] == 30
        finally:
            cur.close()

    def test_select_scalar(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            names = _tbl(cur, "users").orderby("id").select("name")
            assert names == ["Alice", "Bob", "Carol"]
        finally:
            cur.close()

    def test_select_tuple(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            rows = _tbl(cur, "users").orderby("id").select(("id", "name"))
            assert all(isinstance(r, tuple) for r in rows)
            assert rows[0][1] == "Alice"
        finally:
            cur.close()

    def test_select_keyed(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            mapping = _tbl(cur, "users").select("name", key="id")
            assert set(mapping.values()) == {"Alice", "Bob", "Carol"}
        finally:
            cur.close()

    def test_limit_and_offset(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            rows = (
                _tbl(cur, "users")
                .orderby("id")
                .limit(2)
                .offset(1)
                .select("name")
            )
            assert rows == ["Bob", "Carol"]
        finally:
            cur.close()

    def test_limit_without_offset(self, mssql_conn, users_table):
        # SQL Server rejects ``OFFSET ... FETCH`` without an ORDER BY,
        # so a bare limit is rendered as ``SELECT TOP n``.
        cur = _cursor(mssql_conn)
        try:
            rows = _tbl(cur, "users").limit(2).select("name")
            assert len(rows) == 2
        finally:
            cur.close()

    def test_parameter_is_not_inlined(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            rows = (
                _tbl(cur, "users")
                .where(name="x'; DROP TABLE users; --")
                .select()
            )
            assert rows == []
            assert _tbl(cur, "users").select() is not None
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------


class TestInsert:
    def test_append(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            assert (
                _tbl(cur, "users").append(name="Dave", age=50) is None
            )
            assert (
                len(_tbl(cur, "users").where(name="Dave").select()) == 1
            )
        finally:
            cur.close()

    def test_insert_many_rows(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            _tbl(cur, "users").insert([
                {"name": "G", "age": 1},
                {"name": "H", "age": 2},
                {"name": "I", "age": 3},
            ])
            assert (
                len(
                    _tbl(cur, "users")
                    .where_in(name=["G", "H", "I"])
                    .select()
                )
                == 3
            )
        finally:
            cur.close()

    def test_insert_missing_key_uses_default(self, mssql_conn):
        cur = _cursor(mssql_conn)
        try:
            cur.execute(
                f"""
                CREATE TABLE [{_SCHEMA}].t (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    a  INT,
                    b  INT DEFAULT 99
                )
                """
            )
            _tbl(cur, "t").insert([{"a": 1, "b": 2}, {"a": 3}])
            rows = _tbl(cur, "t").orderby("a").select()
            assert [r["b"] for r in rows] == [2, 99]
        finally:
            cur.close()

    def test_insert_many(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            _tbl(cur, "users").insert_many(
                [{"name": "J", "age": 1}, {"name": "K", "age": 2}],
                columns=["name", "age"],
            )
            assert (
                len(
                    _tbl(cur, "users")
                    .where_in(name=["J", "K"])
                    .select()
                )
                == 2
            )
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# UPDATE / DELETE
# ---------------------------------------------------------------------------


class TestUpdateDelete:
    def test_update(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            _tbl(cur, "users").where(name="Alice").update(age=31)
            assert (
                _tbl(cur, "users").where(name="Alice").select()[0]["age"]
                == 31
            )
        finally:
            cur.close()

    def test_update_without_where_rejected(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(JustormError):
                _tbl(cur, "users").update(age=0)
        finally:
            cur.close()

    def test_delete(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            _tbl(cur, "users").where(name="Bob").delete()
            assert _tbl(cur, "users").where(name="Bob").select() == []
        finally:
            cur.close()

    def test_delete_without_where_rejected(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(JustormError):
                _tbl(cur, "users").delete()
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# RETURNING is rejected
# ---------------------------------------------------------------------------


class TestReturningRejected:
    def test_append_returning_rejected(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(JustormDialectError):
                _tbl(cur, "users").returning("id").append(
                    name="X", age=1
                )
        finally:
            cur.close()

    def test_update_returning_rejected(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(JustormDialectError):
                _tbl(cur, "users").where(name="Alice").returning("id").update(
                    age=1
                )
        finally:
            cur.close()

    def test_delete_returning_rejected(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(JustormDialectError):
                _tbl(cur, "users").where(name="Alice").returning("id").delete()
        finally:
            cur.close()

    def test_output_workaround(self, mssql_conn, users_table):
        # The documented workaround on SQL Server: an OUTPUT clause
        # written as raw SQL.
        cur = _cursor(mssql_conn)
        try:
            rows = cur.query(
                f"""
                INSERT INTO [{_SCHEMA}].users (name, age)
                OUTPUT INSERTED.id
                VALUES (%s, %s)
                """,
                ["Zed", 1],
            )
            assert rows[0]["id"] == 4
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# UPSERT is rejected
# ---------------------------------------------------------------------------


class TestUpsertRejected:
    def test_on_conflict_rejected(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(JustormDialectError):
                _tbl(cur, "users").on_conflict(
                    do=cur.sql.nothing()
                ).append(name="X", age=1)
        finally:
            cur.close()

    def test_on_duplicate_rejected(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(JustormDialectError):
                _tbl(cur, "users").on_duplicate(
                    update={"age": 1}
                ).append(name="X", age=1)
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Dialect-specific features that SQL Server does not have
# ---------------------------------------------------------------------------


class TestUnsupportedFeatures:
    def test_ilike_rejected(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(JustormDialectError):
                _tbl(cur, "users").where_ilike(name="alice").select()
        finally:
            cur.close()

    def test_distinct_on_rejected(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(JustormDialectError):
                _tbl(cur, "users").distinct_on("name").select()
        finally:
            cur.close()

    def test_for_update_rejected(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(JustormDialectError):
                _tbl(cur, "users").where(name="Alice").select(
                    for_update=True
                )
        finally:
            cur.close()

    def test_distinct_works(self, mssql_conn):
        cur = _cursor(mssql_conn)
        try:
            cur.execute(
                f"CREATE TABLE [{_SCHEMA}].t (a INT)"
            )
            _tbl(cur, "t").insert([{"a": 1}, {"a": 1}, {"a": 2}])
            rows = _tbl(cur, "t").distinct().orderby("a").select("a")
            assert rows == [1, 2]
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Subquery
# ---------------------------------------------------------------------------


class TestSubquery:
    def test_subquery_join(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            cur.execute(
                f"""
                CREATE TABLE [{_SCHEMA}].orders (
                    id      INT IDENTITY(1,1) PRIMARY KEY,
                    user_id INT NOT NULL,
                    total   INT NOT NULL
                )
                """
            )
            _tbl(cur, "orders").insert(
                [
                    {"user_id": 1, "total": 50},
                    {"user_id": 1, "total": 200},
                    {"user_id": 2, "total": 10},
                ]
            )

            users = _tbl(cur, "users")
            orders = _tbl(cur, "orders")

            sub = orders.where(
                orders["total"] > 100
            ).select_subquery({"user_id"})
            s = sub.as_("s")

            rows = users.join(
                s, on=users["id"] == s["user_id"]
            ).select({users["name"]})
            assert [r["name"] for r in rows] == ["Alice"]
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Nested subqueries (A7)
# ---------------------------------------------------------------------------


class TestNestedSubquery:
    @pytest.fixture()
    def three_tables(self, mssql_conn):
        cur = _cursor(mssql_conn)
        try:
            cur.execute(
                f"""
                CREATE TABLE [{_SCHEMA}].users (
                    id   INT IDENTITY(1,1) PRIMARY KEY,
                    name NVARCHAR(64) NOT NULL
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE [{_SCHEMA}].orders (
                    id      INT IDENTITY(1,1) PRIMARY KEY,
                    user_id INT NOT NULL,
                    total   INT NOT NULL
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE [{_SCHEMA}].order_items (
                    id       INT IDENTITY(1,1) PRIMARY KEY,
                    order_id INT NOT NULL,
                    qty      INT NOT NULL
                )
                """
            )
            _tbl(cur, "users").insert([
                {"name": "Alice"},
                {"name": "Bob"},
            ])
            _tbl(cur, "orders").insert([
                {"user_id": 1, "total": 50},
                {"user_id": 1, "total": 200},
                {"user_id": 2, "total": 10},
            ])
            _tbl(cur, "order_items").insert([
                {"order_id": 2, "qty": 3},
                {"order_id": 2, "qty": 4},
                {"order_id": 3, "qty": 1},
            ])
        finally:
            cur.close()
        return "users"

    def test_two_subqueries_joined(self, mssql_conn, three_tables):
        cur = _cursor(mssql_conn)
        try:
            users = _tbl(cur, "users")
            orders = _tbl(cur, "orders")
            items = _tbl(cur, "order_items")

            big_orders = orders.where(
                orders["total"] > 100
            ).select_subquery({"id", "user_id"})
            item_ids = items.where(
                items["qty"] > 2
            ).select_subquery({"order_id"})
            bo = big_orders.as_("bo")
            it = item_ids.as_("it")

            rows = users.join(
                bo, on=users["id"] == bo["user_id"]
            ).join(
                it, on=bo["id"] == it["order_id"]
            ).select({users["name"]})
            # Two order_items rows match the same big order, so Alice
            # appears twice.
            assert [r["name"] for r in rows] == ["Alice", "Alice"]
        finally:
            cur.close()

    def test_subquery_with_join_inside(self, mssql_conn, three_tables):
        cur = _cursor(mssql_conn)
        try:
            users = _tbl(cur, "users")
            orders = _tbl(cur, "orders")

            inner = users.join(
                orders,
                on=users["id"] == orders["user_id"],
            ).where(
                orders["total"] > 100
            ).select_subquery({users["id"]})
            s = inner.as_("s")

            rows = s.select()
            assert [r["id"] for r in rows] == [1]
        finally:
            cur.close()

    def test_subquery_with_group_style_filter(self, mssql_conn, three_tables):
        cur = _cursor(mssql_conn)
        try:
            users = _tbl(cur, "users")
            orders = _tbl(cur, "orders")

            big = orders.where(
                orders["total"] > 100
            ).select_subquery({"user_id"})
            s = big.as_("s")

            rows = users.join(
                s, on=users["id"] == s["user_id"]
            ).select({users["name"]})
            assert [r["name"] for r in rows] == ["Alice"]
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Errors from the server
# ---------------------------------------------------------------------------


class TestServerErrors:
    def test_missing_table(self, mssql_conn):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(pymssql.Error):
                cur.table(_SCHEMA, "no_such_table").select()
        finally:
            cur.close()

    def test_missing_column(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            with pytest.raises(pymssql.Error):
                _tbl(cur, "users").where(no_such_column=1).select()
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TestTransactions:
    def test_rollback_discards_insert(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            # The fixture runs with autocommit on, so to test rollback
            # we explicitly disable it for the duration of the test.
            mssql_conn.autocommit(False)
            _tbl(cur, "users").append(name="Temp", age=1)
            mssql_conn.rollback()
            assert _tbl(cur, "users").where(name="Temp").select() == []
        finally:
            mssql_conn.autocommit(True)
            cur.close()

    def test_commit_persists_insert(self, mssql_conn, users_table):
        cur = _cursor(mssql_conn)
        try:
            mssql_conn.autocommit(False)
            _tbl(cur, "users").append(name="Persist", age=1)
            mssql_conn.commit()
            assert (
                len(_tbl(cur, "users").where(name="Persist").select()) == 1
            )
        finally:
            mssql_conn.autocommit(True)
            cur.close()