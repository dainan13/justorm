"""Integration tests for ``justorm.pymysql``.

These tests require a running MySQL or MariaDB server and the
``PyMySQL`` package.  Both are opt-in: set ``JUSTORM_MYSQL_DSN`` and
install the ``pymysql`` extra.
"""

from __future__ import annotations

from collections import namedtuple

import pytest

pymysql = pytest.importorskip("pymysql")

import justorm.pymysql
from justorm import JustormDialectError, JustormError


pytestmark = pytest.mark.pymysql


def _cursor(conn):
    return conn.cursor(justorm.pymysql.Cursor)


# ---------------------------------------------------------------------------
# Cursor identity and native surface
# ---------------------------------------------------------------------------


class TestCursorIdentity:
    def test_cursor_is_pymysql_cursor(self, mysql_conn):
        cur = _cursor(mysql_conn)
        try:
            assert isinstance(cur, pymysql.cursors.Cursor)
        finally:
            cur.close()

    def test_dialect_name(self, mysql_conn):
        cur = _cursor(mysql_conn)
        try:
            assert cur.dialect_name == "mysql"
        finally:
            cur.close()

    def test_native_execute_returns_rowcount(self, mysql_conn):
        cur = _cursor(mysql_conn)
        try:
            result = cur.execute("SELECT 1")
            assert result == 1
            assert cur.fetchone() == (1,)
        finally:
            cur.close()

    def test_table_named_like_a_cursor_attribute(self, mysql_conn):
        cur = _cursor(mysql_conn)
        try:
            assert callable(cur.execute)
            assert cur.table("execute") is not None
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def users_table(mysql_conn):
    cur = _cursor(mysql_conn)
    try:
        cur.execute(
            """
            CREATE TABLE users (
                id     INT AUTO_INCREMENT PRIMARY KEY,
                name   VARCHAR(64) NOT NULL,
                age    INT,
                active TINYINT(1) NOT NULL DEFAULT 1,
                UNIQUE KEY uq_users_name (name)
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
        mysql_conn.commit()
    finally:
        cur.close()
    return "users"


# ---------------------------------------------------------------------------
# fetch* with format=
# ---------------------------------------------------------------------------


class TestFetchFormat:
    def test_fetchone_dict(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            row = cur.fetchone(format=dict)
            assert row == {"id": 1, "name": "Alice"}
        finally:
            cur.close()

    def test_fetchone_namedtuple(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            row = cur.fetchone(format=namedtuple)
            assert row.id == 1
            assert row.name == "Alice"
        finally:
            cur.close()

    def test_fetchmany_dict(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            rows = cur.fetchmany(2, format=dict)
            assert [r["name"] for r in rows] == ["Alice", "Bob"]
        finally:
            cur.close()

    def test_fetchall_namedtuple(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            rows = cur.fetchall(format=namedtuple)
            assert rows[2].name == "Carol"
        finally:
            cur.close()

    def test_bad_format_rejected(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
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
    def test_get_row(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            row = cur.users.where(name="Alice").get()
            assert row == {"id": 1, "name": "Alice", "age": 30, "active": 1}
        finally:
            cur.close()

    def test_get_missing_returns_none(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            assert cur.users.where(name="Nobody").get() is None
        finally:
            cur.close()

    def test_get_default(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            assert cur.users.where(name="Nobody").get(default={}) == {}
        finally:
            cur.close()

    def test_get_scalar(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            assert cur.users.where(name="Alice").get("name") == "Alice"
        finally:
            cur.close()

    def test_get_scalar_default(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            assert (
                cur.users.where(name="Nobody").get("name", default="?") == "?"
            )
        finally:
            cur.close()

    def test_get_tuple(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            row = cur.users.where(name="Alice").get(("id", "name"))
            assert row == (1, "Alice")
        finally:
            cur.close()

    def test_get_rejects_key(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(JustormError):
                cur.users.where(name="Alice").get(key="id")
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_select_returns_dicts(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            rows = cur.query("SELECT id, name FROM users ORDER BY id")
            assert rows == [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
                {"id": 3, "name": "Carol"},
            ]
        finally:
            cur.close()

    def test_query_select_with_params(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            rows = cur.query(
                "SELECT name FROM users WHERE age > %s ORDER BY id",
                [26],
            )
            assert rows == [{"name": "Alice"}, {"name": "Carol"}]
        finally:
            cur.close()

    def test_query_select_empty(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            assert cur.query("SELECT id FROM users WHERE FALSE") == []
        finally:
            cur.close()

    def test_query_insert_returns_lastrowid(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            result = cur.query(
                "INSERT INTO users (name, age) VALUES (%s, %s)",
                ["Dave", 50],
            )
            # MySQL exposes a real lastrowid; ``query`` returns it for
            # INSERT statements.
            assert result == 4
            mysql_conn.commit()
        finally:
            cur.close()

    def test_query_update_returns_rowcount(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            result = cur.query(
                "UPDATE users SET age = %s WHERE age > %s",
                [99, 28],
            )
            assert result == 2
            mysql_conn.commit()
        finally:
            cur.close()

    def test_query_delete_returns_rowcount(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            result = cur.query("DELETE FROM users WHERE name = %s", ["Bob"])
            assert result == 1
            mysql_conn.commit()
        finally:
            cur.close()

    def test_query_ddl_returns_rowcount(self, mysql_conn):
        cur = _cursor(mysql_conn)
        try:
            result = cur.query("CREATE TABLE t (id INT)")
            assert isinstance(result, int)
            mysql_conn.commit()
        finally:
            cur.close()

    def test_query_bad_sql_raises(self, mysql_conn):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(pymysql.err.MySQLError):
                cur.query("SELECT * FROM no_such_table")
        finally:
            mysql_conn.rollback()
            cur.close()


# ---------------------------------------------------------------------------
# key_conflict (A1)
# ---------------------------------------------------------------------------


class TestKeyConflict:
    @pytest.fixture()
    def events_table(self, mysql_conn):
        cur = _cursor(mysql_conn)
        try:
            cur.execute(
                """
                CREATE TABLE events (
                    id    INT AUTO_INCREMENT PRIMARY KEY,
                    kind  VARCHAR(16) NOT NULL,
                    value INT
                )
                """
            )
            cur.events.insert([
                {"kind": "a", "value": 1},
                {"kind": "a", "value": 2},
                {"kind": "b", "value": 3},
            ])
            mysql_conn.commit()
        finally:
            cur.close()
        return "events"

    def test_key_conflict_error_by_default(self, mysql_conn, events_table):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(JustormError):
                cur.events.orderby("id").select("value", key="kind")
        finally:
            cur.close()

    def test_key_conflict_overwrite(self, mysql_conn, events_table):
        cur = _cursor(mysql_conn)
        try:
            result = cur.events.orderby("id").select(
                "value", key="kind", key_conflict="overwrite"
            )
            assert result == {"a": 2, "b": 3}
        finally:
            cur.close()

    def test_key_conflict_callable(self, mysql_conn, events_table):
        cur = _cursor(mysql_conn)
        try:
            result = cur.events.orderby("id").select(
                "value",
                key="kind",
                key_conflict=lambda old, new: old + new,
            )
            assert result == {"a": 3, "b": 3}
        finally:
            cur.close()

    def test_key_conflict_on_full_row(self, mysql_conn, events_table):
        cur = _cursor(mysql_conn)
        try:
            result = cur.events.orderby("id").select(
                key="kind", key_conflict="overwrite"
            )
            assert result["a"]["value"] == 2
            assert result["b"]["value"] == 3
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# SELECT
# ---------------------------------------------------------------------------


class TestSelect:
    def test_select_all(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            rows = cur.users.orderby("id").select()
            assert len(rows) == 3
            assert {r["name"] for r in rows} == {"Alice", "Bob", "Carol"}
        finally:
            cur.close()

    def test_identifier_quoting_uses_backticks(self, mysql_conn):
        cur = _cursor(mysql_conn)
        try:
            cur.execute("CREATE TABLE t (`select` INT, `where` INT)")
            cur.t.append(**{"select": 1, "where": 2})
            mysql_conn.commit()
            rows = cur.t.select()
            assert rows == [{"select": 1, "where": 2}]
        finally:
            cur.close()

    def test_where_kwargs(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            rows = cur.users.where(name="Alice").select()
            assert len(rows) == 1
            assert rows[0]["age"] == 30
        finally:
            cur.close()

    def test_select_scalar(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            names = cur.users.orderby("id").select("name")
            assert names == ["Alice", "Bob", "Carol"]
        finally:
            cur.close()

    def test_select_tuple(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            rows = cur.users.orderby("id").select(("id", "name"))
            assert all(isinstance(r, tuple) for r in rows)
            assert rows[0][1] == "Alice"
        finally:
            cur.close()

    def test_select_keyed(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            mapping = cur.users.select("name", key="id")
            assert set(mapping.values()) == {"Alice", "Bob", "Carol"}
        finally:
            cur.close()

    def test_limit_and_offset(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            rows = cur.users.orderby("id").limit(2).offset(1).select("name")
            assert rows == ["Bob", "Carol"]
        finally:
            cur.close()

    def test_offset_without_limit_rejected(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises((JustormError, ValueError)):
                cur.users.offset(1).select()
        finally:
            cur.close()

    def test_parameter_is_not_inlined(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
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
    def test_append(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            assert cur.users.append(name="Dave", age=50) is None
            mysql_conn.commit()
            assert len(cur.users.where(name="Dave").select()) == 1
        finally:
            cur.close()

    def test_insert_many_rows(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.users.insert([
                {"name": "G", "age": 1},
                {"name": "H", "age": 2},
                {"name": "I", "age": 3},
            ])
            mysql_conn.commit()
            assert len(cur.users.where_in(name=["G", "H", "I"]).select()) == 3
        finally:
            cur.close()

    def test_insert_missing_key_uses_default(self, mysql_conn):
        cur = _cursor(mysql_conn)
        try:
            cur.execute(
                "CREATE TABLE t (id INT AUTO_INCREMENT PRIMARY KEY, "
                "a INT, b INT DEFAULT 99)"
            )
            cur.t.insert([{"a": 1, "b": 2}, {"a": 3}])
            mysql_conn.commit()
            rows = cur.t.orderby("a").select()
            assert [r["b"] for r in rows] == [2, 99]
        finally:
            cur.close()

    def test_insert_many(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.users.insert_many(
                [{"name": "J", "age": 1}, {"name": "K", "age": 2}],
                columns=["name", "age"],
            )
            mysql_conn.commit()
            assert len(cur.users.where_in(name=["J", "K"]).select()) == 2
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# UPDATE / DELETE
# ---------------------------------------------------------------------------


class TestUpdateDelete:
    def test_update(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.users.where(name="Alice").update(age=31)
            mysql_conn.commit()
            assert cur.users.where(name="Alice").select()[0]["age"] == 31
        finally:
            cur.close()

    def test_update_without_where_rejected(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(JustormError):
                cur.users.update(age=0)
        finally:
            cur.close()

    def test_delete(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.users.where(name="Bob").delete()
            mysql_conn.commit()
            assert cur.users.where(name="Bob").select() == []
        finally:
            cur.close()

    def test_delete_without_where_rejected(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(JustormError):
                cur.users.delete()
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# RETURNING is rejected
# ---------------------------------------------------------------------------


class TestReturningRejected:
    def test_append_returning_rejected(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(JustormDialectError):
                cur.users.returning("id").append(name="X", age=1)
        finally:
            cur.close()

    def test_update_returning_rejected(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(JustormDialectError):
                cur.users.where(name="Alice").returning("id").update(age=1)
        finally:
            cur.close()

    def test_delete_returning_rejected(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(JustormDialectError):
                cur.users.where(name="Alice").returning("id").delete()
        finally:
            cur.close()

    def test_last_insert_id_workaround(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.users.append(name="Zed", age=1)
            cur.execute("SELECT LAST_INSERT_ID()")
            new_id = cur.fetchone()[0]
            assert isinstance(new_id, int)
            mysql_conn.commit()
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# UPSERT
# ---------------------------------------------------------------------------


class TestUpsert:
    def test_on_duplicate_do_nothing(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.users.on_duplicate(update={"id": cur["id"]}).append(
                name="Alice", age=999,
            )
            mysql_conn.commit()
            assert cur.users.where(name="Alice").select()[0]["age"] == 30
        finally:
            cur.close()

    def test_on_duplicate_do_update(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.users.on_duplicate(update={"age": cur["VALUES(age)"]}).append(
                name="Alice", age=42,
            )
            mysql_conn.commit()
            assert cur.users.where(name="Alice").select()[0]["age"] == 42
        finally:
            cur.close()

    def test_on_duplicate_with_insert(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.users.on_duplicate(update={"age": cur["VALUES(age)"]}).insert([
                {"name": "Alice", "age": 50},
                {"name": "New", "age": 20},
            ])
            mysql_conn.commit()
            assert cur.users.where(name="Alice").select()[0]["age"] == 50
            assert cur.users.where(name="New").select()[0]["age"] == 20
        finally:
            cur.close()

    def test_on_conflict_rejected(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(JustormDialectError):
                cur.users.on_conflict(do=cur.sql.nothing()).append(name="X", age=1)
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Dialect-specific features that MySQL does not have
# ---------------------------------------------------------------------------


class TestUnsupportedFeatures:
    def test_ilike_rejected(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(JustormDialectError):
                cur.users.where_ilike(name="alice").select()
        finally:
            cur.close()

    def test_distinct_on_rejected(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(JustormDialectError):
                cur.users.distinct_on("name").select()
        finally:
            cur.close()

    def test_for_update_supported(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            rows = cur.users.where(name="Alice").select(for_update=True)
            mysql_conn.commit()
            assert len(rows) == 1
        finally:
            cur.close()


# ---------------------------------------------------------------------------
# Subquery
# ---------------------------------------------------------------------------


class TestSubquery:
    def test_subquery_join(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.execute(
                """
                CREATE TABLE orders (
                    id      INT AUTO_INCREMENT PRIMARY KEY,
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
            mysql_conn.commit()

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
    def test_missing_table(self, mysql_conn):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(pymysql.err.MySQLError):
                cur.no_such_table.select()
        finally:
            mysql_conn.rollback()
            cur.close()

    def test_missing_column(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            with pytest.raises(pymysql.err.MySQLError):
                cur.users.where(no_such_column=1).select()
        finally:
            mysql_conn.rollback()
            cur.close()


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TestTransactions:
    def test_rollback_discards_insert(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.users.append(name="Temp", age=1)
            mysql_conn.rollback()
            assert cur.users.where(name="Temp").select() == []
        finally:
            cur.close()

    def test_commit_persists_insert(self, mysql_conn, users_table):
        cur = _cursor(mysql_conn)
        try:
            cur.users.append(name="Persist", age=1)
            mysql_conn.commit()
            assert len(cur.users.where(name="Persist").select()) == 1
        finally:
            cur.close()
