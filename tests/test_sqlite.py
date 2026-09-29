"""Integration tests for ``justorm.sqlite``.

SQLite is the easiest driver to test: it lives in the standard library,
needs no server, and supports an in-memory database.

The SQLite entry point is different from the others: ``sqlite3.Cursor``
cannot be subclassed, so ``justorm.sqlite.Cursor`` wraps an inner
cursor rather than inheriting from one.

SQLite's dialect notes:

* identifiers are quoted with backticks,
* placeholders are ``?``, so literal ``%`` does **not** need escaping,
* ``RETURNING`` is available since SQLite 3.35,
* ``ON CONFLICT`` is available since 3.24, but ``ON CONFLICT ON
  CONSTRAINT`` and the index-predicate form are not,
* ``DISTINCT ON``, ``ILIKE`` and ``FOR UPDATE`` are not supported,
* ``DEFAULT`` is not accepted inside a ``VALUES`` list, so missing
  keys are filled with ``NULL`` instead.
"""

from __future__ import annotations

import sqlite3
from collections import namedtuple

import pytest

import justorm.sqlite
from justorm import JustormDialectError, JustormError


pytestmark = pytest.mark.sqlite


# ---------------------------------------------------------------------------
# Wrapper identity and native surface
# ---------------------------------------------------------------------------


class TestCursorIdentity:
    def test_rejects_non_connection(self):
        with pytest.raises(TypeError):
            justorm.sqlite.Cursor("not a connection")

    def test_wraps_connection(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        assert cur.connection is sqlite_conn

    def test_dialect_name(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        assert cur.dialect_name == "sqlite"

    def test_native_execute_returns_cursor(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        result = cur.execute("SELECT 1")
        assert result is cur
        assert cur.fetchone() == (1,)

    def test_native_fetchmany(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("CREATE TABLE t (x INT)")
        cur.executemany("INSERT INTO t (x) VALUES (?)", [(1,), (2,), (3,)])
        cur.execute("SELECT x FROM t ORDER BY x")
        assert cur.fetchmany(2) == [(1,), (2,)]
        assert cur.fetchall() == [(3,)]

    def test_native_description(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("SELECT 1 AS n")
        assert cur.description[0][0] == "n"

    def test_native_rowcount(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("CREATE TABLE t (x INT)")
        cur.execute("INSERT INTO t (x) VALUES (1)")
        assert cur.rowcount == 1

    def test_native_lastrowid(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, x INT)")
        cur.execute("INSERT INTO t (x) VALUES (1)")
        assert cur.lastrowid == 1

    def test_wrapper_is_iterable(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("CREATE TABLE t (x INT)")
        cur.executemany("INSERT INTO t (x) VALUES (?)", [(1,), (2,)])
        cur.execute("SELECT x FROM t ORDER BY x")
        assert [row for row in cur] == [(1,), (2,)]

    def test_wrapper_is_context_manager(self, sqlite_conn):
        with justorm.sqlite.Cursor(sqlite_conn) as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)

    def test_table_named_like_a_cursor_attribute(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        assert callable(cur.execute)
        assert cur.table("execute") is not None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def users_table(sqlite_conn):
    cur = justorm.sqlite.Cursor(sqlite_conn)
    cur.execute(
        """
        CREATE TABLE users (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            name   TEXT NOT NULL UNIQUE,
            age    INTEGER,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    cur.users.insert(
        [
            {"name": "Alice", "age": 30, "active": 1},
            {"name": "Bob", "age": 25, "active": 1},
            {"name": "Carol", "age": 40, "active": 0},
        ]
    )
    sqlite_conn.commit()
    return "users"


# ---------------------------------------------------------------------------
# fetch* with format=
# ---------------------------------------------------------------------------


class TestFetchFormat:
    def test_fetchone_dict(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("SELECT id, name FROM users ORDER BY id")
        row = cur.fetchone(format=dict)
        assert row == {"id": 1, "name": "Alice"}

    def test_fetchone_namedtuple(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("SELECT id, name FROM users ORDER BY id")
        row = cur.fetchone(format=namedtuple)
        assert row.id == 1
        assert row.name == "Alice"

    def test_fetchmany_dict(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("SELECT id, name FROM users ORDER BY id")
        rows = cur.fetchmany(2, format=dict)
        assert [r["name"] for r in rows] == ["Alice", "Bob"]

    def test_fetchall_namedtuple(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("SELECT id, name FROM users ORDER BY id")
        rows = cur.fetchall(format=namedtuple)
        assert rows[2].name == "Carol"

    def test_fetchone_none_with_format(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("SELECT id FROM users WHERE FALSE")
        assert cur.fetchone(format=dict) is None

    def test_bad_format_rejected(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("SELECT id FROM users")
        with pytest.raises(JustormError):
            cur.fetchall(format=list)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_row(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        row = cur.users.where(name="Alice").get()
        assert row == {"id": 1, "name": "Alice", "age": 30, "active": 1}

    def test_get_missing_returns_none(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        assert cur.users.where(name="Nobody").get() is None

    def test_get_default(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        assert cur.users.where(name="Nobody").get(default={}) == {}

    def test_get_scalar(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        assert cur.users.where(name="Alice").get("name") == "Alice"

    def test_get_scalar_default(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        assert (
            cur.users.where(name="Nobody").get("name", default="?") == "?"
        )

    def test_get_tuple(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        row = cur.users.where(name="Alice").get(("id", "name"))
        assert row == (1, "Alice")

    def test_get_rejects_key(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        with pytest.raises(JustormError):
            cur.users.where(name="Alice").get(key="id")


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_select_returns_dicts(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        rows = cur.query("SELECT id, name FROM users ORDER BY id")
        assert rows == [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Carol"},
        ]

    def test_query_select_with_params(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        rows = cur.query(
            "SELECT name FROM users WHERE age > ? ORDER BY id",
            [26],
        )
        assert rows == [{"name": "Alice"}, {"name": "Carol"}]

    def test_query_select_empty(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        assert cur.query("SELECT id FROM users WHERE 0") == []

    def test_query_insert_returns_lastrowid(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        result = cur.query(
            "INSERT INTO users (name, age) VALUES (?, ?)", ["Dave", 50]
        )
        # SQLite exposes a real lastrowid; ``query`` returns it for
        # INSERT statements.
        assert result == 4
        sqlite_conn.commit()

    def test_query_update_returns_rowcount(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        result = cur.query(
            "UPDATE users SET age = ? WHERE age > ?", [99, 28]
        )
        assert result == 2
        sqlite_conn.commit()

    def test_query_delete_returns_rowcount(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        result = cur.query("DELETE FROM users WHERE name = ?", ["Bob"])
        assert result == 1
        sqlite_conn.commit()

    def test_query_ddl_returns_rowcount(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        result = cur.query("CREATE TABLE t (id INT)")
        assert isinstance(result, int)
        sqlite_conn.commit()

    def test_query_bad_sql_raises(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        with pytest.raises(sqlite3.OperationalError):
            cur.query("SELECT * FROM no_such_table")


# ---------------------------------------------------------------------------
# key_conflict (A1)
# ---------------------------------------------------------------------------


class TestKeyConflict:
    @pytest.fixture()
    def events_table(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute(
            """
            CREATE TABLE events (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
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
        sqlite_conn.commit()
        return "events"

    def test_key_conflict_error_by_default(self, sqlite_conn, events_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        with pytest.raises(JustormError):
            cur.events.orderby("id").select("value", key="kind")

    def test_key_conflict_overwrite(self, sqlite_conn, events_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        result = cur.events.orderby("id").select(
            "value", key="kind", key_conflict="overwrite"
        )
        assert result == {"a": 2, "b": 3}

    def test_key_conflict_callable(self, sqlite_conn, events_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        result = cur.events.orderby("id").select(
            "value",
            key="kind",
            key_conflict=lambda old, new: old + new,
        )
        assert result == {"a": 3, "b": 3}

    def test_key_conflict_on_full_row(self, sqlite_conn, events_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        result = cur.events.orderby("id").select(
            key="kind", key_conflict="overwrite"
        )
        assert result["a"]["value"] == 2
        assert result["b"]["value"] == 3


# ---------------------------------------------------------------------------
# Nested subqueries (A7)
# ---------------------------------------------------------------------------


class TestNestedSubquery:
    @pytest.fixture()
    def three_tables(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute(
            """
            CREATE TABLE users (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE orders (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INT NOT NULL,
                total   INT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE order_items (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
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
        sqlite_conn.commit()
        return "users"

    def test_two_subqueries_joined(self, sqlite_conn, three_tables):
        cur = justorm.sqlite.Cursor(sqlite_conn)
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

    def test_subquery_with_join_inside(self, sqlite_conn, three_tables):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        inner = cur.users.join(
            cur.orders,
            on=cur.users["id"] == cur.orders["user_id"],
        ).where(
            cur.orders["total"] > 100
        ).select_subquery({cur.users["id"]})
        s = inner.as_("s")

        rows = s.select()
        assert [r["id"] for r in rows] == [1]

    def test_subquery_with_group_style_filter(self, sqlite_conn, three_tables):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        big = cur.orders.where(
            cur.orders["total"] > 100
        ).select_subquery({"user_id"})
        s = big.as_("s")

        rows = cur.users.join(
            s, on=cur.users["id"] == s["user_id"]
        ).select({cur.users["name"]})
        assert [r["name"] for r in rows] == ["Alice"]


# ---------------------------------------------------------------------------
# SELECT
# ---------------------------------------------------------------------------


class TestSelect:
    def test_select_all(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        rows = cur.users.orderby("id").select()
        assert len(rows) == 3
        assert {r["name"] for r in rows} == {"Alice", "Bob", "Carol"}

    def test_where_kwargs(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        rows = cur.users.where(name="Alice").select()
        assert len(rows) == 1
        assert rows[0]["age"] == 30

    def test_where_none_is_null(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, x TEXT)")
        cur.t.insert([{"x": None}, {"x": "a"}])
        sqlite_conn.commit()
        rows = cur.t.where(x=None).select()
        assert len(rows) == 1
        assert rows[0]["x"] is None

    def test_select_scalar(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        names = cur.users.orderby("id").select("name")
        assert names == ["Alice", "Bob", "Carol"]

    def test_select_tuple(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        rows = cur.users.orderby("id").select(("id", "name"))
        assert all(isinstance(r, tuple) for r in rows)
        assert rows[0][1] == "Alice"

    def test_select_keyed(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        mapping = cur.users.select("name", key="id")
        assert set(mapping.values()) == {"Alice", "Bob", "Carol"}

    def test_select_subset_of_columns(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        rows = cur.users.select({"name"})
        assert all(set(r.keys()) == {"name"} for r in rows)

    def test_limit_and_offset(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        rows = cur.users.orderby("id").limit(2).offset(1).select("name")
        assert rows == ["Bob", "Carol"]

    def test_offset_without_limit(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        rows = cur.users.orderby("id").offset(1).select("name")
        assert rows == ["Bob", "Carol"]

    def test_parameter_is_not_inlined(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        rows = cur.users.where(
            name="x'; DROP TABLE users; --"
        ).select()
        assert rows == []
        assert cur.users.select() is not None

    def test_percent_is_literal(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.users.append(name="100%", age=1)
        sqlite_conn.commit()
        rows = cur.users.where(
            cur["name LIKE '100%'"] == 1
        ).select("name")
        assert rows == ["100%"]


# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------


class TestInsert:
    def test_append(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        assert cur.users.append(name="Dave", age=50) is None
        sqlite_conn.commit()
        assert len(cur.users.where(name="Dave").select()) == 1

    def test_append_returning_scalar(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        new_id = cur.users.returning("id").append(name="Eve", age=22)
        sqlite_conn.commit()
        assert isinstance(new_id, int)

    def test_append_returning_tuple(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        row = cur.users.returning("id", "name").append(
            name="Frank", age=33
        )
        sqlite_conn.commit()
        assert isinstance(row, tuple)
        assert row[1] == "Frank"

    def test_insert_many_rows(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.users.insert([
            {"name": "G", "age": 1},
            {"name": "H", "age": 2},
            {"name": "I", "age": 3},
        ])
        sqlite_conn.commit()
        assert len(cur.users.where_in(name=["G", "H", "I"]).select()) == 3

    def test_insert_missing_key_uses_null(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute(
            "CREATE TABLE t (id INTEGER PRIMARY KEY, a INT, b INT)"
        )
        cur.t.insert([{"a": 1, "b": 2}, {"a": 3}])
        sqlite_conn.commit()
        rows = cur.t.orderby("a").select()
        assert rows[0]["b"] == 2
        assert rows[1]["b"] is None

    def test_insert_many(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.users.insert_many(
            [{"name": "J", "age": 1}, {"name": "K", "age": 2}],
            columns=["name", "age"],
        )
        sqlite_conn.commit()
        assert len(cur.users.where_in(name=["J", "K"]).select()) == 2


# ---------------------------------------------------------------------------
# UPDATE / DELETE
# ---------------------------------------------------------------------------


class TestUpdateDelete:
    def test_update(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.users.where(name="Alice").update(age=31)
        sqlite_conn.commit()
        assert cur.users.where(name="Alice").select()[0]["age"] == 31

    def test_update_without_where_rejected(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        with pytest.raises(JustormError):
            cur.users.update(age=0)

    def test_delete(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.users.where(name="Bob").delete()
        sqlite_conn.commit()
        assert cur.users.where(name="Bob").select() == []

    def test_delete_without_where_rejected(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        with pytest.raises(JustormError):
            cur.users.delete()

    def test_delete_returning(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        ids = cur.users.where(name="Carol").returning("id").delete()
        sqlite_conn.commit()
        assert isinstance(ids, list)
        assert len(ids) == 1


# ---------------------------------------------------------------------------
# RETURNING (SQLite 3.35+)
# ---------------------------------------------------------------------------


class TestReturning:
    def test_update_returning_list(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        ids = cur.users.where(active=1).returning("id").update(age=100)
        sqlite_conn.commit()
        assert isinstance(ids, list)
        assert len(ids) == 2


# ---------------------------------------------------------------------------
# UPSERT
# ---------------------------------------------------------------------------


class TestUpsert:
    def test_on_conflict_do_nothing(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.users.on_conflict(
            on=cur.sql.columns("name"),
            do=cur.sql.nothing(),
        ).append(name="Alice", age=999)
        sqlite_conn.commit()
        assert cur.users.where(name="Alice").select()[0]["age"] == 30

    def test_on_conflict_do_update(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.users.on_conflict(
            on=cur.sql.columns("name"),
            do=cur.sql.update(age=cur["EXCLUDED.age"]),
        ).append(name="Alice", age=42)
        sqlite_conn.commit()
        assert cur.users.where(name="Alice").select()[0]["age"] == 42

    def test_on_conflict_constraint_rejected(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        with pytest.raises(JustormDialectError):
            cur.users.on_conflict(
                on=cur.sql.constraint("some_constraint"),
                do=cur.sql.nothing(),
            ).append(name="X", age=1)

    def test_on_duplicate_rejected(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        with pytest.raises(JustormDialectError):
            cur.users.on_duplicate(update={"age": 1}).append(name="X", age=1)


# ---------------------------------------------------------------------------
# Dialect-specific features that SQLite does not have
# ---------------------------------------------------------------------------


class TestUnsupportedFeatures:
    def test_ilike_rejected(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        with pytest.raises(JustormDialectError):
            cur.users.where_ilike(name="alice").select()

    def test_distinct_on_rejected(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        with pytest.raises(JustormDialectError):
            cur.users.distinct_on("name").select()

    def test_for_update_rejected(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        with pytest.raises(JustormDialectError):
            cur.users.where(name="Alice").select(for_update=True)

    def test_distinct_works(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute("CREATE TABLE t (a INT)")
        cur.t.insert([{"a": 1}, {"a": 1}, {"a": 2}])
        sqlite_conn.commit()
        rows = cur.t.distinct().orderby("a").select("a")
        assert rows == [1, 2]


# ---------------------------------------------------------------------------
# Subquery
# ---------------------------------------------------------------------------


class TestSubquery:
    def test_subquery_join(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.execute(
            """
            CREATE TABLE orders (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INT NOT NULL,
                total   INT NOT NULL
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
        sqlite_conn.commit()

        sub = cur.orders.where(
            cur.orders["total"] > 100
        ).select_subquery({"user_id"})
        s = sub.as_("s")

        rows = cur.users.join(
            s, on=cur.users["id"] == s["user_id"]
        ).select({cur.users["name"]})
        assert [r["name"] for r in rows] == ["Alice"]


# ---------------------------------------------------------------------------
# Errors from the server
# ---------------------------------------------------------------------------


class TestServerErrors:
    def test_missing_table(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        with pytest.raises(sqlite3.OperationalError):
            cur.no_such_table.select()

    def test_missing_column(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        with pytest.raises(sqlite3.OperationalError):
            cur.users.where(no_such_column=1).select()


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TestTransactions:
    def test_rollback_discards_insert(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.users.append(name="Temp", age=1)
        sqlite_conn.rollback()
        assert cur.users.where(name="Temp").select() == []

    def test_commit_persists_insert(self, sqlite_conn, users_table):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.users.append(name="Persist", age=1)
        sqlite_conn.commit()
        assert len(cur.users.where(name="Persist").select()) == 1


# ---------------------------------------------------------------------------
# Wrapper-specific behaviour
# ---------------------------------------------------------------------------


class TestWrapperBehaviour:
    def test_arraysize_property(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.arraysize = 5
        assert cur.arraysize == 5

    def test_close_is_idempotent(self, sqlite_conn):
        cur = justorm.sqlite.Cursor(sqlite_conn)
        cur.close()
        cur.close()

    def test_exit_closes_cursor(self, sqlite_conn):
        with justorm.sqlite.Cursor(sqlite_conn) as cur:
            cur.execute("SELECT 1")
        with pytest.raises(sqlite3.ProgrammingError):
            cur.execute("SELECT 1")
