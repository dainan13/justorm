"""Integration tests for ``justorm.psycopg``.

These tests require a running PostgreSQL server and the ``psycopg`` (v3)
package.  Both are opt-in: set ``JUSTORM_PG_DSN`` and install the
``psycopg`` extra.
"""

from __future__ import annotations

from collections import namedtuple

import pytest

psycopg = pytest.importorskip("psycopg")

import justorm.psycopg
from justorm import JustormDialectError, JustormError


pytestmark = pytest.mark.psycopg


def _cursor(conn):
    return conn.cursor()


# ---------------------------------------------------------------------------
# Cursor identity and native surface
# ---------------------------------------------------------------------------


class TestCursorIdentity:
    def test_cursor_is_psycopg_cursor(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            assert isinstance(cur, psycopg.Cursor)
        finally:
            cur.close()

    def test_dialect_name(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            assert cur.dialect_name == "postgresql"
        finally:
            cur.close()

    def test_native_execute_still_works(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
        finally:
            cur.close()

    def test_native_attributes_present(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            assert cur.description is None
            assert cur.rowcount == -1
            assert hasattr(cur, "execute")
            assert hasattr(cur, "fetchone")
            assert hasattr(cur, "fetchall")
        finally:
            cur.close()

    def test_table_named_like_a_cursor_attribute(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            assert callable(cur.execute)
            b = cur.table("execute")
            assert b is not None
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def users_table(pg_conn):
    """A small ``users`` table with a unique ``name`` column."""
    cur = _cursor(pg_conn)
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
        pg_conn.commit()
    finally:
        cur.close()
    return "users"


# ---------------------------------------------------------------------------
# fetch* with format=
# ---------------------------------------------------------------------------


class TestFetchFormat:
    def test_fetchone_default(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            row = cur.fetchone()
            assert isinstance(row, tuple)
            assert row[1] == "Alice"
        finally:
            cur.close()

    def test_fetchone_dict(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            row = cur.fetchone(format=dict)
            assert row == {"id": 1, "name": "Alice"}
        finally:
            cur.close()

    def test_fetchone_namedtuple(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            row = cur.fetchone(format=namedtuple)
            assert row.id == 1
            assert row.name == "Alice"
        finally:
            cur.close()

    def test_fetchone_none_with_format(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.execute("SELECT id FROM users WHERE FALSE")
            assert cur.fetchone(format=dict) is None
            assert cur.fetchone(format=namedtuple) is None
        finally:
            cur.close()

    def test_fetchmany_dict(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            rows = cur.fetchmany(2, format=dict)
            assert rows == [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ]
        finally:
            cur.close()

    def test_fetchall_dict(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            rows = cur.fetchall(format=dict)
            assert [r["name"] for r in rows] == ["Alice", "Bob", "Carol"]
        finally:
            cur.close()

    def test_fetchall_namedtuple(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            rows = cur.fetchall(format=namedtuple)
            assert rows[0].id == 1
            assert rows[2].name == "Carol"
        finally:
            cur.close()

    def test_bad_format_rejected(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
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
    def test_get_row(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            row = cur.users.where(name="Alice").get()
            assert row == {
                "id": 1,
                "name": "Alice",
                "age": 30,
                "active": True,
            }
        finally:
            cur.close()

    def test_get_missing_returns_none(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            assert cur.users.where(name="Nobody").get() is None
        finally:
            cur.close()

    def test_get_default(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            assert cur.users.where(name="Nobody").get(default={}) == {}
        finally:
            cur.close()

    def test_get_scalar(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            assert cur.users.where(name="Alice").get("name") == "Alice"
        finally:
            cur.close()

    def test_get_scalar_default(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            assert (
                cur.users.where(name="Nobody").get("name", default="?") == "?"
            )
        finally:
            cur.close()

    def test_get_tuple(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            row = cur.users.where(name="Alice").get(("id", "name"))
            assert row == (1, "Alice")
        finally:
            cur.close()

    def test_get_rejects_key(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            with pytest.raises(JustormError):
                cur.users.where(name="Alice").get(key="id")
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_select_returns_dicts(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            rows = cur.query("SELECT id, name FROM users ORDER BY id")
            assert rows == [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
                {"id": 3, "name": "Carol"},
            ]
        finally:
            cur.close()

    def test_query_select_with_params(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            rows = cur.query(
                "SELECT name FROM users WHERE age > %s ORDER BY id",
                [26],
            )
            assert rows == [{"name": "Alice"}, {"name": "Carol"}]
        finally:
            cur.close()

    def test_query_select_empty(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            assert cur.query("SELECT id FROM users WHERE FALSE") == []
        finally:
            cur.close()

    def test_query_insert_returns_rowcount(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            result = cur.query(
                "INSERT INTO users (name, age) VALUES (%s, %s)",
                ["Dave", 50],
            )
            # PG does not expose a real lastrowid; ``query`` falls back
            # to rowcount for INSERT statements.
            assert result == 1
            pg_conn.commit()
        finally:
            cur.close()

    def test_query_update_returns_rowcount(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            result = cur.query(
                "UPDATE users SET age = %s WHERE age > %s",
                [99, 28],
            )
            assert result == 2
            pg_conn.commit()
        finally:
            cur.close()

    def test_query_delete_returns_rowcount(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            result = cur.query("DELETE FROM users WHERE name = %s", ["Bob"])
            assert result == 1
            pg_conn.commit()
        finally:
            cur.close()

    def test_query_ddl_returns_rowcount(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            result = cur.query("CREATE TABLE t (id INT)")
            assert isinstance(result, int)
            pg_conn.commit()
        finally:
            cur.close()

    def test_query_bad_sql_raises(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            with pytest.raises(psycopg.Error):
                cur.query("SELECT * FROM no_such_table")
        finally:
            pg_conn.rollback()
            cur.close()


# ---------------------------------------------------------------------------
# key_conflict (A1)
# ---------------------------------------------------------------------------


class TestKeyConflict:
    @pytest.fixture()
    def events_table(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            cur.execute(
                """
                CREATE TABLE events (
                    id    SERIAL PRIMARY KEY,
                    kind  TEXT NOT NULL,
                    value INT
                )
                """
            )
            cur.events.insert([
                {"kind": "a", "value": 1},
                {"kind": "a", "value": 2},
                {"kind": "b", "value": 3},
            ])
            pg_conn.commit()
        finally:
            cur.close()
        return "events"

    def test_key_conflict_error_by_default(self, pg_conn, events_table):
        cur = _cursor(pg_conn)
        try:
            with pytest.raises(JustormError):
                cur.events.orderby("id").select("value", key="kind")
        finally:
            cur.close()

    def test_key_conflict_overwrite(self, pg_conn, events_table):
        cur = _cursor(pg_conn)
        try:
            result = cur.events.orderby("id").select(
                "value", key="kind", key_conflict="overwrite"
            )
            assert result == {"a": 2, "b": 3}
        finally:
            cur.close()

    def test_key_conflict_callable(self, pg_conn, events_table):
        cur = _cursor(pg_conn)
        try:
            result = cur.events.orderby("id").select(
                "value",
                key="kind",
                key_conflict=lambda old, new: old + new,
            )
            assert result == {"a": 3, "b": 3}
        finally:
            cur.close()

    def test_key_conflict_on_full_row(self, pg_conn, events_table):
        cur = _cursor(pg_conn)
        try:
            result = cur.events.orderby("id").select(
                key="kind", key_conflict="overwrite"
            )
            assert result["a"]["value"] == 2
            assert result["b"]["value"] == 3
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# on_conflict with partial index (A6)
# ---------------------------------------------------------------------------


class TestPartialIndex:
    @pytest.fixture()
    def partial_table(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            cur.execute("CREATE TABLE t (id INT, a INT)")
            cur.execute(
                "CREATE UNIQUE INDEX uq_t_a_active ON t (a) WHERE a > 0"
            )
            pg_conn.commit()
        finally:
            cur.close()
        return "t"

    def test_on_conflict_index_where_do_nothing(self, pg_conn, partial_table):
        cur = _cursor(pg_conn)
        try:
            cur.t.on_conflict(
                on=cur.sql.where(cur["a"] > 0).columns("a"),
                do=cur.sql.nothing(),
            ).append(id=1, a=5)
            cur.t.on_conflict(
                on=cur.sql.where(cur["a"] > 0).columns("a"),
                do=cur.sql.nothing(),
            ).append(id=2, a=5)
            pg_conn.commit()
            rows = cur.t.orderby("id").select()
            assert rows == [{"id": 1, "a": 5}]
        finally:
            cur.close()

    def test_on_conflict_index_where_do_update(self, pg_conn, partial_table):
        cur = _cursor(pg_conn)
        try:
            cur.t.on_conflict(
                on=cur.sql.where(cur["a"] > 0).columns("a"),
                do=cur.sql.update(id=cur["EXCLUDED.id"]),
            ).append(id=1, a=5)
            cur.t.on_conflict(
                on=cur.sql.where(cur["a"] > 0).columns("a"),
                do=cur.sql.update(id=cur["EXCLUDED.id"]),
            ).append(id=2, a=5)
            pg_conn.commit()
            rows = cur.t.select()
            assert rows == [{"id": 2, "a": 5}]
        finally:
            cur.close()

    def test_do_update_with_where(self, pg_conn, partial_table):
        cur = _cursor(pg_conn)
        try:
            cur.t.on_conflict(
                on=cur.sql.where(cur["a"] > 0).columns("a"),
                do=cur.sql.where(cur["t.id"] > 0).update(
                    id=cur["EXCLUDED.id"]
                ),
            ).append(id=1, a=5)
            cur.t.on_conflict(
                on=cur.sql.where(cur["a"] > 0).columns("a"),
                do=cur.sql.where(cur["t.id"] > 0).update(
                    id=cur["EXCLUDED.id"]
                ),
            ).append(id=2, a=5)
            pg_conn.commit()
            rows = cur.t.select()
            assert rows == [{"id": 2, "a": 5}]
        finally:
            cur.close()

    def test_do_update_with_false_where(self, pg_conn, partial_table):
        # The update condition is false, so the conflict leaves the
        # existing row untouched.
        cur = _cursor(pg_conn)
        try:
            cur.t.on_conflict(
                on=cur.sql.where(cur["a"] > 0).columns("a"),
                do=cur.sql.update(id=cur["EXCLUDED.id"]),
            ).append(id=1, a=5)
            cur.t.on_conflict(
                on=cur.sql.where(cur["a"] > 0).columns("a"),
                do=cur.sql.where(cur["t.id"] > 100).update(
                    id=cur["EXCLUDED.id"]
                ),
            ).append(id=2, a=5)
            pg_conn.commit()
            rows = cur.t.select()
            assert rows == [{"id": 1, "a": 5}]
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Nested subqueries (A7)
# ---------------------------------------------------------------------------


class TestNestedSubquery:
    @pytest.fixture()
    def three_tables(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            cur.execute(
                """
                CREATE TABLE users (
                    id     SERIAL PRIMARY KEY,
                    name   TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE orders (
                    id      SERIAL PRIMARY KEY,
                    user_id INT NOT NULL,
                    total   INT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE order_items (
                    id       SERIAL PRIMARY KEY,
                    order_id INT NOT NULL,
                    qty      INT NOT NULL
                )
                """
            )
            cur.users.insert([
                {"name": "Alice"},
                {"name": "Bob"},
            ])
            cur.orders.insert([
                {"user_id": 1, "total": 50},
                {"user_id": 1, "total": 200},
                {"user_id": 2, "total": 10},
            ])
            cur.order_items.insert([
                {"order_id": 2, "qty": 3},
                {"order_id": 2, "qty": 4},
                {"order_id": 3, "qty": 1},
            ])
            pg_conn.commit()
        finally:
            cur.close()
        return "users"

    def test_two_subqueries_joined(self, pg_conn, three_tables):
        cur = _cursor(pg_conn)
        try:
            big_orders = cur.orders.where(
                cur.orders["total"] > 100
            ).select_subquery({"id", "user_id"})
            items = cur.order_items.where(
                cur.order_items["qty"] > 2
            ).select_subquery({"order_id"})
            bo = big_orders.as_("bo")
            it = items.as_("it")

            rows = cur.users.join(
                bo, on=cur.users["id"] == bo["user_id"]
            ).join(
                it, on=bo["id"] == it["order_id"]
            ).select({cur.users["name"]})
            # Two order_items rows match the same big order, so Alice
            # appears twice.
            assert [r["name"] for r in rows] == ["Alice", "Alice"]
        finally:
            cur.close()

    def test_subquery_with_join_inside(self, pg_conn, three_tables):
        cur = _cursor(pg_conn)
        try:
            inner = cur.users.join(
                cur.orders,
                on=cur.users["id"] == cur.orders["user_id"],
            ).where(
                cur.orders["total"] > 100
            ).select_subquery({cur.users["id"]})
            s = inner.as_("s")

            rows = s.select()
            assert [r["id"] for r in rows] == [1]
        finally:
            cur.close()

    def test_subquery_with_group_style_filter(self, pg_conn, three_tables):
        cur = _cursor(pg_conn)
        try:
            big = cur.orders.where(
                cur.orders["total"] > 100
            ).select_subquery({"user_id"})
            s = big.as_("s")

            rows = cur.users.join(
                s, on=cur.users["id"] == s["user_id"]
            ).select({cur.users["name"]})
            assert [r["name"] for r in rows] == ["Alice"]
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# SELECT
# ---------------------------------------------------------------------------


class TestSelect:
    def test_select_all_returns_dicts(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            rows = cur.users.orderby("id").select()
            assert len(rows) == 3
            assert all(isinstance(r, dict) for r in rows)
            names = {r["name"] for r in rows}
            assert names == {"Alice", "Bob", "Carol"}
        finally:
            cur.close()

    def test_where_kwargs(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            rows = cur.users.where(name="Alice").select()
            assert len(rows) == 1
            assert rows[0]["age"] == 30
        finally:
            cur.close()

    def test_where_none_is_null(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            cur.execute("CREATE TABLE t (id SERIAL PRIMARY KEY, x TEXT)")
            cur.t.insert([{"x": None}, {"x": "a"}])
            pg_conn.commit()
            rows = cur.t.where(x=None).select()
            assert len(rows) == 1
            assert rows[0]["x"] is None
        finally:
            cur.close()

    def test_select_subset_of_columns(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            rows = cur.users.select({"name"})
            assert all(set(r.keys()) == {"name"} for r in rows)
        finally:
            cur.close()

    def test_select_tuple_rows(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            rows = cur.users.orderby("id").select(("id", "name"))
            assert all(isinstance(r, tuple) for r in rows)
            assert rows[0][1] == "Alice"
        finally:
            cur.close()

    def test_select_scalar(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            names = cur.users.orderby("id").select("name")
            assert names == ["Alice", "Bob", "Carol"]
        finally:
            cur.close()

    def test_select_keyed(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            mapping = cur.users.select("name", key="id")
            assert set(mapping.values()) == {"Alice", "Bob", "Carol"}
        finally:
            cur.close()

    def test_parameter_is_not_inlined(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
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
    def test_append_returns_none_without_returning(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            result = cur.users.append(name="Dave", age=50)
            assert result is None
            pg_conn.commit()
            assert len(cur.users.where(name="Dave").select()) == 1
        finally:
            cur.close()

    def test_append_returning_scalar(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            new_id = cur.users.returning("id").append(name="Eve", age=22)
            assert isinstance(new_id, int)
            pg_conn.commit()
        finally:
            cur.close()

    def test_append_returning_tuple(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            row = cur.users.returning("id", "name").append(
                name="Frank", age=33
            )
            assert isinstance(row, tuple)
            assert row[1] == "Frank"
            pg_conn.commit()
        finally:
            cur.close()

    def test_insert_many_rows(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.users.insert([
                {"name": "G", "age": 1},
                {"name": "H", "age": 2},
                {"name": "I", "age": 3},
            ])
            pg_conn.commit()
            assert len(cur.users.where_in(name=["G", "H", "I"]).select()) == 3
        finally:
            cur.close()

    def test_insert_missing_key_uses_default(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            cur.execute(
                "CREATE TABLE t (id SERIAL PRIMARY KEY, a INT, "
                "b INT DEFAULT 99)"
            )
            cur.t.insert([{"a": 1, "b": 2}, {"a": 3}])
            pg_conn.commit()
            rows = cur.t.orderby("a").select()
            assert [r["b"] for r in rows] == [2, 99]
        finally:
            cur.close()

    def test_insert_many_requires_columns(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            with pytest.raises(JustormError):
                cur.users.insert_many([{"name": "X"}])
        finally:
            cur.close()

    def test_insert_many_uses_executemany(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.users.insert_many(
                [{"name": "J", "age": 1}, {"name": "K", "age": 2}],
                columns=["name", "age"],
            )
            pg_conn.commit()
            assert len(cur.users.where_in(name=["J", "K"]).select()) == 2
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# UPDATE / DELETE
# ---------------------------------------------------------------------------


class TestUpdateDelete:
    def test_update_with_where(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.users.where(name="Alice").update(age=31)
            pg_conn.commit()
            row = cur.users.where(name="Alice").select()[0]
            assert row["age"] == 31
        finally:
            cur.close()

    def test_update_without_where_rejected(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            with pytest.raises(JustormError):
                cur.users.update(age=0)
        finally:
            cur.close()

    def test_update_with_all(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.users.all().update(active=False)
            pg_conn.commit()
            assert all(not r["active"] for r in cur.users.select())
        finally:
            cur.close()

    def test_delete_with_where(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.users.where(name="Bob").delete()
            pg_conn.commit()
            assert cur.users.where(name="Bob").select() == []
        finally:
            cur.close()

    def test_delete_without_where_rejected(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            with pytest.raises(JustormError):
                cur.users.delete()
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# RETURNING
# ---------------------------------------------------------------------------


class TestReturning:
    def test_update_returning_list(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            ids = cur.users.where(active=True).returning("id").update(age=100)
            pg_conn.commit()
            assert isinstance(ids, list)
            assert len(ids) == 2
        finally:
            cur.close()

    def test_delete_returning_list(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            ids = cur.users.where(name="Carol").returning("id").delete()
            pg_conn.commit()
            assert isinstance(ids, list)
            assert len(ids) == 1
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# UPSERT
# ---------------------------------------------------------------------------


class TestUpsert:
    def test_on_conflict_do_nothing(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.users.on_conflict(
                on=cur.sql.columns("name"),
                do=cur.sql.nothing(),
            ).append(name="Alice", age=999)
            pg_conn.commit()
            row = cur.users.where(name="Alice").select()[0]
            assert row["age"] == 30
        finally:
            cur.close()

    def test_on_conflict_do_update(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.users.on_conflict(
                on=cur.sql.columns("name"),
                do=cur.sql.update(age=cur["EXCLUDED.age"]),
            ).append(name="Alice", age=42)
            pg_conn.commit()
            row = cur.users.where(name="Alice").select()[0]
            assert row["age"] == 42
        finally:
            cur.close()

    def test_on_conflict_constraint(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            cur.execute(
                """
                CREATE TABLE t (
                    id INT,
                    name TEXT,
                    CONSTRAINT t_pkey PRIMARY KEY (id)
                )
                """
            )
            cur.t.on_conflict(
                on=cur.sql.constraint("t_pkey"),
                do=cur.sql.update(name=cur["EXCLUDED.name"]),
            ).append(id=1, name="a")
            cur.t.on_conflict(
                on=cur.sql.constraint("t_pkey"),
                do=cur.sql.update(name=cur["EXCLUDED.name"]),
            ).append(id=1, name="b")
            pg_conn.commit()
            rows = cur.t.select()
            assert rows == [{"id": 1, "name": "b"}]
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Dialect-specific
# ---------------------------------------------------------------------------


class TestDialectSpecific:
    def test_ilike(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            rows = cur.users.where_ilike(name="alice").select()
            assert len(rows) == 1
        finally:
            cur.close()

    def test_distinct_on(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            cur.execute("CREATE TABLE t (a INT, b INT)")
            cur.t.insert([{"a": 1, "b": 1}, {"a": 1, "b": 2}, {"a": 2, "b": 3}])
            pg_conn.commit()
            rows = (
                cur.t.distinct_on("a").orderby("a").orderby_desc("b").select()
            )
            assert len(rows) == 2
            assert {r["a"] for r in rows} == {1, 2}
        finally:
            cur.close()

    def test_for_update(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            rows = cur.users.where(name="Alice").select(for_update=True)
            pg_conn.commit()
            assert len(rows) == 1
        finally:
            cur.close()

    def test_on_duplicate_rejected(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            with pytest.raises(JustormDialectError):
                cur.users.on_duplicate(update={"age": 1}).append(name="X")
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Subquery
# ---------------------------------------------------------------------------


class TestSubquery:
    def test_subquery_join(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
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
            pg_conn.commit()

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
    def test_missing_table_raises_psycopg_error(self, pg_conn):
        cur = _cursor(pg_conn)
        try:
            with pytest.raises(psycopg.Error):
                cur.no_such_table.select()
        finally:
            pg_conn.rollback()
            cur.close()

    def test_missing_column_raises_psycopg_error(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            with pytest.raises(psycopg.Error):
                cur.users.where(no_such_column=1).select()
        finally:
            pg_conn.rollback()
            cur.close()


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TestTransactions:
    def test_rollback_discards_insert(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.users.append(name="Temp", age=1)
            pg_conn.rollback()
            assert cur.users.where(name="Temp").select() == []
        finally:
            cur.close()

    def test_commit_persists_insert(self, pg_conn, users_table):
        cur = _cursor(pg_conn)
        try:
            cur.users.append(name="Persist", age=1)
            pg_conn.commit()
            assert len(cur.users.where(name="Persist").select()) == 1
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Instrumentation hooks
# ---------------------------------------------------------------------------


class TestInstrumentation:
    def test_execute_can_be_overridden(self, pg_conn, users_table):
        seen = []

        class LoggingCursor(justorm.psycopg.Cursor):
            def _just_execute(self, sql, params):
                seen.append((sql, list(params)))
                super()._just_execute(sql, params)

            def _just_execute_and_fetch(self, sql, params):
                seen.append((sql, list(params)))
                return super()._just_execute_and_fetch(sql, params)

        old_factory = pg_conn.cursor_factory
        pg_conn.cursor_factory = LoggingCursor
        try:
            cur = pg_conn.cursor()
            try:
                cur.users.where(name="Alice").select()
                assert any("SELECT" in s for s, _ in seen)
                assert any("Alice" in p for _, p in seen)
            finally:
                cur.close()
        finally:
            pg_conn.cursor_factory = old_factory
