"""Integration tests for ``justorm.psycopg2``.

These tests require a running PostgreSQL server and the ``psycopg2``
package.  Both are opt-in: set ``JUSTORM_PG2_DSN`` and install the
``psycopg2`` extra.
"""

from __future__ import annotations

from collections import namedtuple

import pytest

psycopg2 = pytest.importorskip("psycopg2")

import justorm.psycopg2
from justorm import JustormDialectError, JustormError


pytestmark = pytest.mark.psycopg2


def _cursor(conn):
    return conn.cursor()


# ---------------------------------------------------------------------------
# Cursor identity and native surface
# ---------------------------------------------------------------------------


class TestCursorIdentity:
    def test_cursor_is_psycopg2_cursor(self, pg_conn2):
        cur = _cursor(pg_conn2)
        try:
            assert isinstance(cur, psycopg2.extensions.cursor)
        finally:
            cur.close()

    def test_dialect_name(self, pg_conn2):
        cur = _cursor(pg_conn2)
        try:
            assert cur.dialect_name == "postgresql"
        finally:
            cur.close()

    def test_native_execute_returns_none(self, pg_conn2):
        cur = _cursor(pg_conn2)
        try:
            result = cur.execute("SELECT 1")
            assert result is None
            assert cur.fetchone() == (1,)
        finally:
            cur.close()

    def test_native_executemany_returns_none(self, pg_conn2):
        cur = _cursor(pg_conn2)
        try:
            cur.execute("CREATE TABLE t (x INT)")
            result = cur.executemany(
                "INSERT INTO t (x) VALUES (%s)", [(1,), (2,)]
            )
            assert result is None
            pg_conn2.commit()
        finally:
            cur.close()

    def test_table_named_like_a_cursor_attribute(self, pg_conn2):
        cur = _cursor(pg_conn2)
        try:
            assert callable(cur.execute)
            assert cur.table("execute") is not None
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def users_table(pg_conn2):
    """A small ``users`` table with a unique ``name`` column."""
    cur = _cursor(pg_conn2)
    try:
        cur.execute(
            """
            CREATE TABLE users (
                id    SERIAL PRIMARY KEY,
                name  TEXT NOT NULL UNIQUE,
                age   INTEGER,
                active BOOLEAN NOT NULL DEFAULT TRUE
            )
            """
        )
        cur.users.insert(
            [
                {"name": "Alice", "age": 30, "active": True},
                {"name": "Bob", "age": 25, "active": True},
                {"name": "Carol", "age": 40, "active": False},
            ]
        )
        pg_conn2.commit()
    finally:
        cur.close()
    return "users"


# ---------------------------------------------------------------------------
# fetch* with format=
# ---------------------------------------------------------------------------


class TestFetchFormat:
    def test_fetchone_dict(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            row = cur.fetchone(format=dict)
            assert row == {"id": 1, "name": "Alice"}
        finally:
            cur.close()

    def test_fetchone_namedtuple(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            row = cur.fetchone(format=namedtuple)
            assert row.id == 1
            assert row.name == "Alice"
        finally:
            cur.close()

    def test_fetchmany_dict(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            rows = cur.fetchmany(2, format=dict)
            assert [r["name"] for r in rows] == ["Alice", "Bob"]
        finally:
            cur.close()

    def test_fetchall_namedtuple(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            rows = cur.fetchall(format=namedtuple)
            assert rows[2].name == "Carol"
        finally:
            cur.close()

    def test_bad_format_rejected(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.execute("SELECT id FROM users")
            with pytest.raises(JustormError):
                cur.fetchall(format=list)
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_row(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            row = cur.users.where(name="Alice").get()
            assert row == {"id": 1, "name": "Alice", "age": 30, "active": True}
        finally:
            cur.close()

    def test_get_missing_returns_none(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            assert cur.users.where(name="Nobody").get() is None
        finally:
            cur.close()

    def test_get_default(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            assert cur.users.where(name="Nobody").get(default={}) == {}
        finally:
            cur.close()

    def test_get_scalar(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            assert cur.users.where(name="Alice").get("name") == "Alice"
        finally:
            cur.close()

    def test_get_scalar_default(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            assert (
                cur.users.where(name="Nobody").get("name", default="?") == "?"
            )
        finally:
            cur.close()

    def test_get_tuple(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            row = cur.users.where(name="Alice").get(("id", "name"))
            assert row == (1, "Alice")
        finally:
            cur.close()

    def test_get_rejects_key(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            with pytest.raises(JustormError):
                cur.users.where(name="Alice").get(key="id")
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_select_returns_dicts(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            rows = cur.query(
                "SELECT id, name FROM users ORDER BY id"
            )
            assert rows == [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
                {"id": 3, "name": "Carol"},
            ]
        finally:
            cur.close()

    def test_query_select_with_params(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            rows = cur.query(
                "SELECT name FROM users WHERE age > %s ORDER BY id",
                [26],
            )
            assert rows == [{"name": "Alice"}, {"name": "Carol"}]
        finally:
            cur.close()

    def test_query_select_empty(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            assert cur.query("SELECT id FROM users WHERE FALSE") == []
        finally:
            cur.close()

    def test_query_insert_returns_rowcount(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            result = cur.query(
                "INSERT INTO users (name, age) VALUES (%s, %s)",
                ["Dave", 50],
            )
            assert result == 1
            pg_conn2.commit()
        finally:
            cur.close()

    def test_query_update_returns_rowcount(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            result = cur.query(
                "UPDATE users SET age = %s WHERE age > %s",
                [99, 28],
            )
            assert result == 2
            pg_conn2.commit()
        finally:
            cur.close()

    def test_query_delete_returns_rowcount(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            result = cur.query(
                "DELETE FROM users WHERE name = %s", ["Bob"]
            )
            assert result == 1
            pg_conn2.commit()
        finally:
            cur.close()

    def test_query_ddl_returns_rowcount(self, pg_conn2):
        cur = _cursor(pg_conn2)
        try:
            result = cur.query("CREATE TABLE t (id INT)")
            assert isinstance(result, int)
            pg_conn2.commit()
        finally:
            cur.close()

    def test_query_bad_sql_raises(self, pg_conn2):
        cur = _cursor(pg_conn2)
        try:
            with pytest.raises(psycopg2.Error):
                cur.query("SELECT * FROM no_such_table")
        finally:
            pg_conn2.rollback()
            cur.close()


# ---------------------------------------------------------------------------
# SELECT
# ---------------------------------------------------------------------------


class TestSelect:
    def test_select_all(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            rows = cur.users.orderby("id").select()
            assert len(rows) == 3
            assert {r["name"] for r in rows} == {"Alice", "Bob", "Carol"}
        finally:
            cur.close()

    def test_where_kwargs(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            rows = cur.users.where(name="Alice").select()
            assert len(rows) == 1
            assert rows[0]["age"] == 30
        finally:
            cur.close()

    def test_select_scalar(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            names = cur.users.orderby("id").select("name")
            assert names == ["Alice", "Bob", "Carol"]
        finally:
            cur.close()

    def test_select_tuple(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            rows = cur.users.orderby("id").select(("id", "name"))
            assert all(isinstance(r, tuple) for r in rows)
            assert rows[0][1] == "Alice"
        finally:
            cur.close()

    def test_select_keyed(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            mapping = cur.users.select("name", key="id")
            assert set(mapping.values()) == {"Alice", "Bob", "Carol"}
        finally:
            cur.close()

    def test_parameter_is_not_inlined(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            rows = cur.users.where(
                name="x'; DROP TABLE users; --"
            ).select()
            assert rows == []
            assert cur.users.select() is not None
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------


class TestInsert:
    def test_append(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            assert cur.users.append(name="Dave", age=50) is None
            pg_conn2.commit()
            assert len(cur.users.where(name="Dave").select()) == 1
        finally:
            cur.close()

    def test_append_returning_scalar(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            new_id = cur.users.returning("id").append(name="Eve", age=22)
            assert isinstance(new_id, int)
            pg_conn2.commit()
        finally:
            cur.close()

    def test_append_returning_tuple(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            row = cur.users.returning("id", "name").append(
                name="Frank", age=33
            )
            assert isinstance(row, tuple)
            assert row[1] == "Frank"
            pg_conn2.commit()
        finally:
            cur.close()

    def test_insert_many_rows(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.users.insert([
                {"name": "G", "age": 1},
                {"name": "H", "age": 2},
                {"name": "I", "age": 3},
            ])
            pg_conn2.commit()
            assert len(cur.users.where_in(name=["G", "H", "I"]).select()) == 3
        finally:
            cur.close()

    def test_insert_missing_key_uses_default(self, pg_conn2):
        cur = _cursor(pg_conn2)
        try:
            cur.execute(
                "CREATE TABLE t (id SERIAL PRIMARY KEY, a INT, "
                "b INT DEFAULT 99)"
            )
            cur.t.insert([{"a": 1, "b": 2}, {"a": 3}])
            pg_conn2.commit()
            rows = cur.t.orderby("a").select()
            assert [r["b"] for r in rows] == [2, 99]
        finally:
            cur.close()

    def test_insert_many(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.users.insert_many(
                [{"name": "J", "age": 1}, {"name": "K", "age": 2}],
                columns=["name", "age"],
            )
            pg_conn2.commit()
            assert len(cur.users.where_in(name=["J", "K"]).select()) == 2
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# UPDATE / DELETE
# ---------------------------------------------------------------------------


class TestUpdateDelete:
    def test_update(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.users.where(name="Alice").update(age=31)
            pg_conn2.commit()
            row = cur.users.where(name="Alice").select()[0]
            assert row["age"] == 31
        finally:
            cur.close()

    def test_update_without_where_rejected(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            with pytest.raises(JustormError):
                cur.users.update(age=0)
        finally:
            cur.close()

    def test_delete(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.users.where(name="Bob").delete()
            pg_conn2.commit()
            assert cur.users.where(name="Bob").select() == []
        finally:
            cur.close()

    def test_delete_without_where_rejected(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            with pytest.raises(JustormError):
                cur.users.delete()
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# RETURNING
# ---------------------------------------------------------------------------


class TestReturning:
    def test_update_returning_list(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            ids = cur.users.where(active=True).returning("id").update(age=100)
            pg_conn2.commit()
            assert isinstance(ids, list)
            assert len(ids) == 2
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# UPSERT
# ---------------------------------------------------------------------------


class TestUpsert:
    def test_on_conflict_do_nothing(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.users.on_conflict(
                on=cur.sql.columns("name"),
                do=cur.sql.nothing(),
            ).append(name="Alice", age=999)
            pg_conn2.commit()
            assert cur.users.where(name="Alice").select()[0]["age"] == 30
        finally:
            cur.close()

    def test_on_conflict_do_update(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.users.on_conflict(
                on=cur.sql.columns("name"),
                do=cur.sql.update(age=cur["EXCLUDED.age"]),
            ).append(name="Alice", age=42)
            pg_conn2.commit()
            assert cur.users.where(name="Alice").select()[0]["age"] == 42
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Dialect-specific
# ---------------------------------------------------------------------------


class TestDialectSpecific:
    def test_ilike(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            assert len(cur.users.where_ilike(name="alice").select()) == 1
        finally:
            cur.close()

    def test_for_update(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            rows = cur.users.where(name="Alice").select(for_update=True)
            pg_conn2.commit()
            assert len(rows) == 1
        finally:
            cur.close()

    def test_on_duplicate_rejected(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            with pytest.raises(JustormDialectError):
                cur.users.on_duplicate(update={"age": 1}).append(name="X")
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Subquery
# ---------------------------------------------------------------------------


class TestSubquery:
    def test_subquery_join(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.execute(
                """
                CREATE TABLE orders (
                    id SERIAL PRIMARY KEY,
                    user_id INT NOT NULL,
                    total INT NOT NULL
                )
                """
            )
            cur.orders.insert(
                [
                    {"user_id": 1, "total": 50},
                    {"user_id": 1, "total": 200},
                    {"user_id": 2, "total": 10},
                ]
            )
            pg_conn2.commit()

            sub = cur.orders.where(
                cur.orders["total"] > 100
            ).select_subquery({"user_id"})
            s = sub.as_("s")

            rows = cur.users.join(
                s, on=cur.users["id"] == s["user_id"]
            ).select({cur.users["name"]})
            assert [r["name"] for r in rows] == ["Alice"]
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Errors from the server
# ---------------------------------------------------------------------------


class TestServerErrors:
    def test_missing_table(self, pg_conn2):
        cur = _cursor(pg_conn2)
        try:
            with pytest.raises(psycopg2.Error):
                cur.no_such_table.select()
        finally:
            pg_conn2.rollback()
            cur.close()

    def test_missing_column(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            with pytest.raises(psycopg2.Error):
                cur.users.where(no_such_column=1).select()
        finally:
            pg_conn2.rollback()
            cur.close()


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TestTransactions:
    def test_rollback_discards_insert(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.users.append(name="Temp", age=1)
            pg_conn2.rollback()
            assert cur.users.where(name="Temp").select() == []
        finally:
            cur.close()

    def test_commit_persists_insert(self, pg_conn2, users_table):
        cur = _cursor(pg_conn2)
        try:
            cur.users.append(name="Persist", age=1)
            pg_conn2.commit()
            assert len(cur.users.where(name="Persist").select()) == 1
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Divergence from psycopg v3
# ---------------------------------------------------------------------------


class TestDivergenceFromPsycopg3:
    def test_execute_returns_none_not_cursor(self, pg_conn2):
        cur = _cursor(pg_conn2)
        try:
            assert cur.execute("SELECT 1") is None
        finally:
            cur.close()

    def test_renderer_is_shared_with_psycopg_v3(self):
        from justorm.psycopg import PGRenderer as PG3

        from justorm.psycopg2 import PGRenderer as PG2

        assert PG3 is PG2
