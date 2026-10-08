"""Tests for the dialect-agnostic builder logic.

These tests do not touch a database and do not touch a driver.  They
exercise the builder by running it against a tiny fake cursor that
records the SQL and parameters it is asked to execute.
"""

from __future__ import annotations

from typing import Any, List, Sequence, Tuple

import pytest

from justorm import (
    JustormDialectError,
    JustormError,
    JustormTypeError,
    JustormValueError,
)


# ---------------------------------------------------------------------------
# A minimal fake cursor.
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, List[Any]]] = []
        self.rows: List[Any] = []
        self.description: Any = None

    def last(self) -> Tuple[str, List[Any]]:
        assert self.calls, "nothing was executed"
        return self.calls[-1]

    def last_sql(self) -> str:
        return self.last()[0]

    def last_params(self) -> List[Any]:
        return self.last()[1]


def _make_cursor(renderer_cls, recorder: _Recorder):
    from justorm.builder import JustBuilder

    class FakeCursor(renderer_cls, JustBuilder):
        dialect_name = getattr(renderer_cls, "dialect_name", "fake")

        def _render_identifier(self, name):
            return self.render_identifier(name)

        def _render_identifier_multi(self, *names):
            return self.render_identifier_multi(*names)

        def _render_placeholder(self):
            return self.render_placeholder()

        def _render_keyword(self, keyword):
            return self.render_keyword(keyword)

        def _escape_percent(self, text):
            return self.escape_percent(text)

        def _render_returning(self, columns):
            return self.render_returning(columns)

        def _render_on_conflict(self, target, do_clause):
            return self.render_on_conflict(target, do_clause)

        def _render_on_duplicate(self, update_clause):
            return self.render_on_duplicate(update_clause)

        def _render_limit_offset(self, limit, offset):
            return self.render_limit_offset(limit, offset)

        def _render_for_update(self, *, share=False, skip_locked=False, nowait=False):
            return self.render_for_update(
                share=share, skip_locked=skip_locked, nowait=nowait
            )

        def _render_distinct_on(self, columns):
            return self.render_distinct_on(columns)

        def _render_ilike(self, left, right):
            return self.render_ilike(left, right)

        @property
        def description(self):
            return recorder.description

        def _just_execute(self, sql, params):
            recorder.calls.append((sql, list(params)))

        def _just_execute_and_fetch(self, sql, params):
            recorder.calls.append((sql, list(params)))
            return list(recorder.rows)

        def _just_execute_and_fetch_one(self, sql, params):
            recorder.calls.append((sql, list(params)))
            return recorder.rows[0] if recorder.rows else None

        def _just_execute_many(self, sql, param_sets):
            for params in param_sets:
                recorder.calls.append((sql, list(params)))

    return FakeCursor()


@pytest.fixture()
def pg():
    from justorm.renderer import PGRenderer

    recorder = _Recorder()
    return _make_cursor(PGRenderer, recorder), recorder


@pytest.fixture()
def mysql():
    from justorm.renderer import MySQLRenderer

    recorder = _Recorder()
    return _make_cursor(MySQLRenderer, recorder), recorder


@pytest.fixture()
def sqlite():
    from justorm.renderer import SQLiteRenderer

    recorder = _Recorder()
    return _make_cursor(SQLiteRenderer, recorder), recorder


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


class TestEntryPoints:
    def test_table_single_name(self, pg):
        cur, rec = pg
        rec.description = [("id",), ("name",)]
        cur.table("users").select()
        assert rec.last_sql() == 'SELECT * FROM "users"'

    def test_table_schema_and_name(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.table("public", "users").select()
        assert rec.last_sql() == 'SELECT * FROM "public"."users"'

    def test_table_dotted_name(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.table("public.users").select()
        assert rec.last_sql() == 'SELECT * FROM "public"."users"'

    def test_table_three_parts_rejected(self, pg):
        cur, _ = pg
        with pytest.raises(JustormValueError):
            cur.table("a.b.c")

    def test_attribute_access(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.select()
        assert rec.last_sql() == 'SELECT * FROM "users"'

    def test_attribute_access_skips_private(self, pg):
        cur, _ = pg
        with pytest.raises(AttributeError):
            cur._not_a_table

    def test_table_name_with_quote_is_escaped(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.table('we"ird').select()
        assert rec.last_sql() == 'SELECT * FROM "we""ird"'

    def test_cursor_subscript_creates_expr(self, pg):
        cur, _ = pg
        expr = cur["lower(name)"]
        from justorm.builder import Expr

        assert isinstance(expr, Expr)
        assert expr.sql == "lower(name)"


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------


class TestExpr:
    def test_verbatim(self, pg):
        cur, _ = pg
        assert cur["lower(name)"].sql == "lower(name)"

    def test_non_string_rejected(self, pg):
        cur, _ = pg
        with pytest.raises(JustormTypeError):
            cur[123]

    @pytest.mark.parametrize("bad", ["a; b", "a -- b", "a /* b", "a */ b"])
    def test_forbidden_tokens_rejected(self, pg, bad):
        cur, _ = pg
        with pytest.raises(JustormValueError):
            cur[bad]

    def test_arithmetic_binds_rhs(self, pg):
        cur, rec = pg
        rec.description = [("age",)]
        cur.users.where(cur["age"] + 1 > 18).select()
        sql, params = rec.last()
        assert "(age + %s) > %s" in sql
        assert params == [1, 18]

    def test_verbatim_arithmetic_inlines(self, pg):
        cur, rec = pg
        rec.description = [("age",)]
        cur.users.where(cur["age + 1"] > 18).select()
        sql, params = rec.last()
        assert "age + 1" in sql
        assert params == [18]

    def test_compare_expr_to_expr(self, pg):
        cur, rec = pg
        rec.description = [("a",)]
        cur.users.where(cur["a"] == cur["b"]).select()
        sql, params = rec.last()
        assert "a = b" in sql
        assert params == []

    def test_none_comparison_is_null(self, pg):
        cur, rec = pg
        rec.description = [("deleted_at",)]
        cur.users.where(cur["deleted_at"] == None).select()  # noqa: E711
        sql, params = rec.last()
        assert "deleted_at IS NULL" in sql
        assert params == []

    def test_none_ne_comparison_is_not_null(self, pg):
        cur, rec = pg
        rec.description = [("deleted_at",)]
        cur.users.where(cur["deleted_at"] != None).select()  # noqa: E711
        sql, params = rec.last()
        assert "deleted_at IS NOT NULL" in sql
        assert params == []

    def test_percent_escaped_on_pg(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        cur.users.where(cur["name LIKE 'a%'"] == True).select()  # noqa: E712
        sql, _ = rec.last()
        assert "a%%" in sql

    def test_percent_not_escaped_on_sqlite(self, sqlite):
        cur, rec = sqlite
        rec.description = [("name",)]
        cur.users.where(cur["name LIKE 'a%'"] == True).select()  # noqa: E712
        sql, _ = rec.last()
        assert "a%" in sql
        assert "a%%" not in sql


class TestExprReverseOps:
    def test_radd(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        cur.users.where((1 + cur["a"]) > 0).select()
        sql, params = rec.last()
        assert "(%s + a) > %s" in sql
        assert params == [1, 0]

    def test_rsub(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        cur.users.where((1 - cur["a"]) > 0).select()
        sql, params = rec.last()
        assert "(%s - a) > %s" in sql
        assert params == [1, 0]

    def test_rmul(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        cur.users.where((2 * cur["a"]) > 0).select()
        sql, params = rec.last()
        assert "(%s * a) > %s" in sql
        assert params == [2, 0]

    def test_rtruediv(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        cur.users.where((10 / cur["a"]) > 0).select()
        sql, params = rec.last()
        assert "(%s / a) > %s" in sql
        assert params == [10, 0]

    def test_rmod(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        cur.users.where((10 % cur["a"]) > 0).select()
        sql, params = rec.last()
        # ``%`` is escaped for psycopg.
        assert "(%s %% a) > %s" in sql
        assert params == [10, 0]

    def test_reverse_ops_chain(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        cur.users.where((1 + cur["a"] * 2) > 0).select()
        sql, params = rec.last()
        # ``a * 2`` is bound first, then ``1 + (...)``.
        assert "a * %s" in sql
        assert "(%s + " in sql
        assert params == [1, 2, 0]

    def test_arith_chain_keeps_all_params(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        cur.users.where((cur["a"] + 1 + 2) > 0).select()
        sql, params = rec.last()
        # The inner ``a + 1`` carries its param; the outer ``+ 2``
        # appends its own; the comparison adds the final ``0``.
        assert params == [1, 2, 0]

    def test_arith_and_compare_keep_params(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        cur.users.where((cur["a"] + 5) == (cur["b"] + 10)).select()
        sql, params = rec.last()
        assert params == [5, 10]


class TestColumnExpr:
    def test_quotes_table_and_column(self, pg):
        cur, rec = pg
        rec.description = [("age",)]
        cur.users.where(cur.users["age"] > 18).select()
        assert '"users"."age" > %s' in rec.last_sql()

    def test_quotes_table_and_column_mysql(self, mysql):
        cur, rec = mysql
        rec.description = [("age",)]
        cur.users.where(cur.users["age"] > 18).select()
        assert "`users`.`age` > %s" in rec.last_sql()

    def test_star_rejected(self, pg):
        cur, _ = pg
        with pytest.raises(JustormValueError):
            cur.users["*"]

    def test_alias(self, pg):
        cur, rec = pg
        rec.description = [("n",)]
        cur.users.select({cur.users["name"].as_("n")})
        assert '"users"."name" AS "n"' in rec.last_sql()


class TestAliasedExprOutputName:
    def test_aliased_column_returns_alias_key(self, pg):
        cur, rec = pg
        rec.rows = [("Alice",)]
        rec.description = [("n",)]
        rows = cur.users.select({cur.users["name"].as_("n")})
        assert rows == [{"n": "Alice"}]
        assert '"users"."name" AS "n"' in rec.last_sql()

    def test_aliased_expr_in_list_projection(self, pg):
        cur, rec = pg
        rec.rows = [("Alice",)]
        rec.description = [("n",)]
        rows = cur.users.select([cur.users["name"].as_("n")])
        assert rows == [{"n": "Alice"}]

    def test_two_aliases_same_column(self, pg):
        cur, rec = pg
        rec.rows = [("Alice", "Bob")]
        rec.description = [("a",), ("b",)]
        rows = cur.users.select({
            cur.users["name"].as_("a"),
            cur.users["name"].as_("b"),
        })
        # set is unordered, so assert on the key set.
        assert len(rows) == 1
        assert set(rows[0].keys()) == {"a", "b"}


class TestConditionCombination:
    def test_and(self, pg):
        cur, rec = pg
        rec.description = [("a",)]
        cond = (cur["a"] > 1) & (cur["b"] < 5)
        cur.users.where(cond).select()
        assert "(a > %s) AND (b < %s)" in rec.last_sql()

    def test_or(self, pg):
        cur, rec = pg
        rec.description = [("a",)]
        cond = (cur["a"] > 1) | (cur["b"] < 5)
        cur.users.where(cond).select()
        assert "(a > %s) OR (b < %s)" in rec.last_sql()

    def test_not(self, pg):
        cur, rec = pg
        rec.description = [("a",)]
        cur.users.where(~(cur["a"] > 1)).select()
        assert "(NOT (a > %s))" in rec.last_sql()

    def test_params_order_is_left_to_right(self, pg):
        cur, rec = pg
        rec.description = [("a",)]
        cond = (cur["a"] > 1) & (cur["b"] < 5)
        cur.users.where(cond).select()
        assert rec.last_params() == [1, 5]


# ---------------------------------------------------------------------------
# WHERE
# ---------------------------------------------------------------------------


class TestWhere:
    def test_kwargs(self, pg):
        cur, rec = pg
        rec.description = [("age",)]
        cur.users.where(age=30).select()
        sql, params = rec.last()
        assert sql == 'SELECT * FROM "users" WHERE ("age" = %s)'
        assert params == [30]

    def test_kwargs_none_is_null(self, pg):
        cur, rec = pg
        rec.description = [("age",)]
        cur.users.where(age=None).select()
        assert '("age" IS NULL)' in rec.last_sql()
        assert rec.last_params() == []

    def test_where_chained_with_and(self, pg):
        cur, rec = pg
        rec.description = [("a",)]
        cur.users.where(a=1).where(b=2).select()
        sql, params = rec.last()
        assert '("a" = %s) AND ("b" = %s)' in sql
        assert params == [1, 2]

    def test_where_no_args_is_noop(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.where().select()
        assert "WHERE" not in rec.last_sql()

    def test_where_positional_condition(self, pg):
        cur, rec = pg
        rec.description = [("age",)]
        cur.users.where(cur["age"] > 18).select()
        assert "(age > %s)" in rec.last_sql()
        assert rec.last_params() == [18]

    def test_where_mixing_positional_and_kwargs_rejected(self, pg):
        cur, _ = pg
        with pytest.raises(JustormTypeError):
            cur.users.where(cur["a"] > 1, b=2)

    def test_where_positional_must_be_condition(self, pg):
        cur, _ = pg
        with pytest.raises(JustormTypeError):
            cur.users.where("a > 1")

    def test_where_in(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.where_in(id=[1, 2, 3]).select()
        sql, params = rec.last()
        assert sql == 'SELECT * FROM "users" WHERE ("id" IN (%s, %s, %s))'
        assert params == [1, 2, 3]

    def test_where_in_empty_is_false(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.where_in(id=[]).select()
        assert rec.last_sql() == 'SELECT * FROM "users" WHERE (FALSE)'
        assert rec.last_params() == []

    def test_where_in_empty_mapping_is_noop(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.where_in({}).select()
        assert "WHERE" not in rec.last_sql()

    def test_where_in_mapping_with_expr_key(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        cur.users.where_in({cur["lower(name)"]: ["a", "b"]}).select()
        sql, params = rec.last()
        assert "lower(name) IN (%s, %s)" in sql
        assert params == ["a", "b"]

    def test_where_not_in(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.where_not_in(id=[1, 2]).select()
        assert '("id" NOT IN (%s, %s))' in rec.last_sql()

    def test_where_not_in_empty_is_true(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.where_not_in(id=[]).select()
        assert rec.last_sql() == 'SELECT * FROM "users" WHERE (TRUE)'

    def test_where_between(self, pg):
        cur, rec = pg
        rec.description = [("age",)]
        cur.users.where_between(age=(18, 65)).select()
        sql, params = rec.last()
        assert '("age" BETWEEN %s AND %s)' in sql
        assert params == [18, 65]

    def test_where_between_requires_pair(self, pg):
        cur, _ = pg
        with pytest.raises(JustormValueError):
            cur.users.where_between(age=(1, 2, 3)).select()

    def test_where_is_null(self, pg):
        cur, rec = pg
        rec.description = [("deleted_at",)]
        cur.users.where_is_null("deleted_at").select()
        assert '("deleted_at" IS NULL)' in rec.last_sql()

    def test_where_like(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        cur.users.where_like(name="A%").select()
        sql, params = rec.last()
        assert '("name" LIKE %s)' in sql
        assert params == ["A%"]

    def test_where_ilike(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        cur.users.where_ilike(name="A%").select()
        assert '("name" ILIKE %s)' in rec.last_sql()

    def test_where_ilike_rejected_on_mysql(self, mysql):
        cur, _ = mysql
        with pytest.raises(JustormDialectError):
            cur.users.where_ilike(name="A%").select()

    def test_where_raw(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        cur.users.where_raw("length(name) > %s", [5]).select()
        sql, params = rec.last()
        assert "length(name) > %s" in sql
        assert params == [5]

    def test_where_raw_no_params(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        cur.users.where_raw("1=1").select()
        sql, params = rec.last()
        assert "1=1" in sql
        assert params == []


class TestWhereBetweenEdge:
    def test_between_expr_key(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        cur.users.where_between({cur["a"]: (1, 10)}).select()
        sql, params = rec.last()
        assert "a BETWEEN %s AND %s" in sql
        assert params == [1, 10]

    def test_between_column_expr(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        cur.users.where_between({cur.users["age"]: (18, 65)}).select()
        sql, params = rec.last()
        assert '"users"."age" BETWEEN %s AND %s' in sql
        assert params == [18, 65]

    def test_between_none_bounds(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        cur.users.where_between(a=(None, 10)).select()
        sql, params = rec.last()
        assert '"a" BETWEEN %s AND %s' in sql
        assert params == [None, 10]

    def test_between_no_mapping_is_noop(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.where_between().select()
        assert "BETWEEN" not in rec.last_sql()

    def test_between_mapping_and_kwargs_rejected(self, pg):
        cur, _ = pg
        with pytest.raises(JustormTypeError):
            cur.users.where_between({cur["a"]: (1, 2)}, b=(3, 4))


# ---------------------------------------------------------------------------
# SELECT shape
# ---------------------------------------------------------------------------


class TestSelectShape:
    def test_default_is_all_columns(self, pg):
        cur, rec = pg
        rec.description = [("id",), ("name",)]
        cur.users.select()
        assert rec.last_sql() == 'SELECT * FROM "users"'

    def test_set_selects_columns(self, pg):
        cur, rec = pg
        rec.description = [("name",), ("age",)]
        result = cur.users.select({"name", "age"})
        sql = rec.last_sql()
        assert "SELECT" in sql
        assert '"name"' in sql
        assert '"age"' in sql
        assert result == []

    def test_list_preserves_order(self, pg):
        cur, rec = pg
        rec.description = [("name",), ("age",)]
        cur.users.select(["name", "age"])
        assert '"name", "age"' in rec.last_sql()

    def test_tuple_selects_columns(self, pg):
        cur, rec = pg
        rec.description = [("name",), ("age",)]
        cur.users.select(("name", "age"))
        assert '"name", "age"' in rec.last_sql()

    def test_str_selects_single_column(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        cur.users.select("name")
        assert rec.last_sql() == 'SELECT "name" FROM "users"'

    def test_star_string_rejected(self, pg):
        cur, _ = pg
        with pytest.raises(JustormValueError):
            cur.users.select("*")

    def test_column_name_with_space_is_quoted(self, pg):
        cur, rec = pg
        rec.description = [("a b",)]
        cur.users.select({"a b"})
        assert '"a b"' in rec.last_sql()


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_returns_first_row(self, pg):
        cur, rec = pg
        rec.rows = [(1, "Alice")]
        rec.description = [("id",), ("name",)]
        row = cur.users.where(id=1).get()
        assert row == {"id": 1, "name": "Alice"}
        assert rec.last_sql().endswith("LIMIT 1")

    def test_get_returns_none_when_empty(self, pg):
        cur, rec = pg
        rec.rows = []
        rec.description = [("id",), ("name",)]
        row = cur.users.where(id=999).get()
        assert row is None

    def test_get_default(self, pg):
        cur, rec = pg
        rec.rows = []
        rec.description = [("id",), ("name",)]
        row = cur.users.where(id=999).get(default={})
        assert row == {}

    def test_get_default_scalar(self, pg):
        cur, rec = pg
        rec.rows = []
        rec.description = [("name",)]
        row = cur.users.where(id=999).get("name", default="unknown")
        assert row == "unknown"

    def test_get_scalar(self, pg):
        cur, rec = pg
        rec.rows = [("Alice",)]
        rec.description = [("name",)]
        row = cur.users.where(id=1).get("name")
        assert row == "Alice"

    def test_get_tuple(self, pg):
        cur, rec = pg
        rec.rows = [(1, "Alice")]
        rec.description = [("id",), ("name",)]
        row = cur.users.where(id=1).get(("id", "name"))
        assert row == (1, "Alice")

    def test_get_set_projection(self, pg):
        cur, rec = pg
        rec.rows = [("Alice",)]
        rec.description = [("name",)]
        row = cur.users.where(id=1).get({"name"})
        assert row == {"name": "Alice"}

    def test_get_rejects_key(self, pg):
        cur, _ = pg
        with pytest.raises(JustormTypeError):
            cur.users.where(id=1).get(key="id")

    def test_get_overrides_limit(self, pg):
        cur, rec = pg
        rec.rows = [(1,)]
        rec.description = [("id",)]
        cur.users.limit(10).get()
        assert rec.last_sql().endswith("LIMIT 1")

    def test_get_does_not_mutate_builder(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        rec.rows = [(1,)]
        base = cur.users.limit(10)
        base.get()
        rec.rows = []
        base.select()
        assert rec.last_sql().endswith("LIMIT 10")


# ---------------------------------------------------------------------------
# ORDER / LIMIT / OFFSET / DISTINCT / FOR UPDATE
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_orderby_single(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.orderby("name").select()
        assert 'ORDER BY "name"' in rec.last_sql()

    def test_orderby_desc(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.orderby_desc("age").select()
        assert 'ORDER BY "age" DESC' in rec.last_sql()

    def test_orderby_chain_appends(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.orderby("name").orderby_desc("age").select()
        assert 'ORDER BY "name", "age" DESC' in rec.last_sql()

    def test_orderby_multiple_args(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.orderby_desc("age", "name").select()
        assert 'ORDER BY "age" DESC, "name" DESC' in rec.last_sql()

    def test_orderby_expr(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.orderby(cur["length(name) DESC"]).select()
        assert "ORDER BY length(name) DESC" in rec.last_sql()


class TestLimitOffset:
    def test_limit(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.limit(10).select()
        assert rec.last_sql().endswith("LIMIT 10")

    def test_offset(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.limit(10).offset(20).select()
        assert rec.last_sql().endswith("LIMIT 10 OFFSET 20")

    def test_limit_overwrites(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.limit(10).limit(20).select()
        assert rec.last_sql().endswith("LIMIT 20")

    def test_mysql_offset_without_limit_rejected(self, mysql):
        cur, _ = mysql
        with pytest.raises(ValueError):
            cur.users.offset(20).select()


class TestDistinct:
    def test_distinct(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.distinct().select()
        assert "SELECT DISTINCT *" in rec.last_sql()

    def test_distinct_on_pg(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.distinct_on("name").select()
        assert 'SELECT DISTINCT ON ("name") *' in rec.last_sql()

    def test_distinct_on_mysql_rejected(self, mysql):
        cur, _ = mysql
        with pytest.raises(JustormDialectError):
            cur.users.distinct_on("name").select()


class TestForUpdate:
    def test_for_update(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.select(for_update=True)
        assert rec.last_sql().endswith("FOR UPDATE")

    def test_for_share(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.select(for_update="share")
        assert rec.last_sql().endswith("FOR SHARE")

    def test_skip_locked(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.select(for_update=True, skip_locked=True)
        assert rec.last_sql().endswith("FOR UPDATE SKIP LOCKED")

    def test_nowait_and_skip_locked_conflict(self, pg):
        cur, _ = pg
        with pytest.raises(ValueError):
            cur.users.select(for_update=True, nowait=True, skip_locked=True)

    def test_sqlite_rejected(self, sqlite):
        cur, _ = sqlite
        with pytest.raises(JustormDialectError):
            cur.users.select(for_update=True)


# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------


class TestInsert:
    def test_append_kwargs(self, pg):
        cur, rec = pg
        cur.users.append(name="Alice", age=30)
        sql, params = rec.last()
        assert sql == 'INSERT INTO "users" ("name", "age") VALUES (%s, %s)'
        assert params == ["Alice", 30]

    def test_append_dict(self, pg):
        cur, rec = pg
        cur.users.append({"name": "Alice", "age": 30})
        sql, params = rec.last()
        assert '"name", "age"' in sql
        assert params == ["Alice", 30]

    def test_append_empty_list_noop(self, pg):
        cur, rec = pg
        cur.users.append([])
        assert rec.calls == []

    def test_insert_many_rows(self, pg):
        cur, rec = pg
        cur.users.insert([{"name": "A"}, {"name": "B"}])
        sql, params = rec.last()
        assert "VALUES (%s), (%s)" in sql
        assert params == ["A", "B"]

    def test_insert_tuple_rows_with_columns(self, pg):
        cur, rec = pg
        cur.users.insert([("A", 1), ("B", 2)], columns=["name", "age"])
        sql, params = rec.last()
        assert "VALUES (%s, %s), (%s, %s)" in sql
        assert params == ["A", 1, "B", 2]

    def test_insert_missing_key_uses_default(self, pg):
        cur, rec = pg
        cur.users.insert([{"a": 1, "b": 2}, {"a": 3}])
        sql, params = rec.last()
        assert "DEFAULT" in sql
        assert params == [1, 2, 3]

    def test_insert_extra_key_ignored(self, pg):
        cur, rec = pg
        cur.users.insert([{"a": 1}, {"a": 2, "b": 3}])
        sql, params = rec.last()
        assert "DEFAULT" in sql
        assert params == [1, 2, 3]

    def test_insert_empty_list_noop(self, pg):
        cur, rec = pg
        cur.users.insert([])
        assert rec.calls == []

    def test_insert_many_requires_columns(self, pg):
        cur, _ = pg
        with pytest.raises(JustormTypeError):
            cur.users.insert_many([{"a": 1}])

    def test_insert_many_uses_execute_many(self, pg):
        cur, rec = pg
        cur.users.insert_many([{"a": 1}, {"a": 2}], columns=["a"])
        assert len(rec.calls) == 2
        assert rec.calls[0][1] == [1]
        assert rec.calls[1][1] == [2]


# ---------------------------------------------------------------------------
# UPDATE / DELETE
# ---------------------------------------------------------------------------


class TestUpdateDelete:
    def test_update_with_where(self, pg):
        cur, rec = pg
        cur.users.where(id=1).update(name="Alice")
        sql, params = rec.last()
        assert sql == 'UPDATE "users" SET "name" = %s WHERE ("id" = %s)'
        assert params == ["Alice", 1]

    def test_update_none_is_assignment(self, pg):
        cur, rec = pg
        cur.users.where(id=1).update(deleted_at=None)
        sql, params = rec.last()
        assert '"deleted_at" = %s' in sql
        assert params == [None, 1]

    def test_update_without_where_rejected(self, pg):
        cur, _ = pg
        with pytest.raises(JustormError):
            cur.users.update(name="Alice")

    def test_update_with_all(self, pg):
        cur, rec = pg
        cur.users.all().update(active=True)
        sql, params = rec.last()
        assert sql == 'UPDATE "users" SET "active" = %s'
        assert params == [True]

    def test_delete_with_where(self, pg):
        cur, rec = pg
        cur.users.where(id=1).delete()
        sql, params = rec.last()
        assert sql == 'DELETE FROM "users" WHERE ("id" = %s)'
        assert params == [1]

    def test_delete_without_where_rejected(self, pg):
        cur, _ = pg
        with pytest.raises(JustormError):
            cur.users.delete()

    def test_delete_with_all(self, pg):
        cur, rec = pg
        cur.users.all().delete()
        assert rec.last_sql() == 'DELETE FROM "users"'

    def test_update_limit_rejected(self, pg):
        cur, _ = pg
        with pytest.raises(JustormError):
            cur.users.where(id=1).limit(1).update(name="x")

    def test_delete_orderby_rejected(self, pg):
        cur, _ = pg
        with pytest.raises(JustormError):
            cur.users.where(id=1).orderby("id").delete()


# ---------------------------------------------------------------------------
# RETURNING
# ---------------------------------------------------------------------------


class TestReturning:
    def test_returning_scalar_on_append(self, pg):
        cur, rec = pg
        rec.rows = [(7,)]
        result = cur.users.returning("id").append(name="Alice")
        assert result == 7
        assert "RETURNING" in rec.last_sql()

    def test_returning_tuple_on_append(self, pg):
        cur, rec = pg
        rec.rows = [(7, "Alice")]
        result = cur.users.returning("id", "name").append(name="Alice")
        assert result == (7, "Alice")

    def test_returning_list_on_insert(self, pg):
        cur, rec = pg
        rec.rows = [(1,), (2,)]
        result = cur.users.returning("id").insert([{"name": "A"}, {"name": "B"}])
        assert result == [1, 2]

    def test_returning_rejected_on_mysql(self, mysql):
        cur, _ = mysql
        with pytest.raises(JustormDialectError):
            cur.users.returning("id").append(name="Alice")


# ---------------------------------------------------------------------------
# UPSERT
# ---------------------------------------------------------------------------


class TestUpsert:
    def test_on_conflict_nothing(self, pg):
        cur, rec = pg
        cur.users.on_conflict(do=cur.sql.nothing()).append(id=1)
        assert "ON CONFLICT DO NOTHING" in rec.last_sql()

    def test_on_conflict_columns(self, pg):
        cur, rec = pg
        cur.users.on_conflict(
            on=cur.sql.columns("id"),
            do=cur.sql.nothing(),
        ).append(id=1)
        assert 'ON CONFLICT ("id") DO NOTHING' in rec.last_sql()

    def test_on_conflict_update(self, pg):
        cur, rec = pg
        cur.users.on_conflict(
            on=cur.sql.columns("id"),
            do=cur.sql.update(name=cur["EXCLUDED.name"]),
        ).append(id=1, name="Alice")
        sql = rec.last_sql()
        assert 'ON CONFLICT ("id") DO UPDATE SET' in sql
        assert "EXCLUDED.name" in sql

    def test_on_conflict_constraint(self, pg):
        cur, rec = pg
        cur.users.on_conflict(
            on=cur.sql.constraint("users_pkey"),
            do=cur.sql.nothing(),
        ).append(id=1)
        assert 'ON CONFLICT ON CONSTRAINT "users_pkey" DO NOTHING' in rec.last_sql()

    def test_on_conflict_requires_do(self, pg):
        cur, _ = pg
        with pytest.raises(JustormTypeError):
            cur.users.on_conflict()

    def test_on_conflict_constraint_rejected_on_sqlite(self, sqlite):
        cur, _ = sqlite
        with pytest.raises(JustormDialectError):
            cur.users.on_conflict(
                on=cur.sql.constraint("users_pkey"),
                do=cur.sql.nothing(),
            ).append(id=1)

    def test_on_duplicate(self, mysql):
        cur, rec = mysql
        cur.users.on_duplicate(update={"name": cur["VALUES(name)"]}).append(id=1)
        sql = rec.last_sql()
        assert "ON DUPLICATE KEY UPDATE" in sql
        assert "VALUES(name)" in sql

    def test_on_duplicate_rejected_on_pg(self, pg):
        cur, _ = pg
        with pytest.raises(JustormDialectError):
            cur.users.on_duplicate(update={"name": "x"}).append(id=1)


class TestOnConflictIndexWhere:
    def test_index_where_in_target(self, pg):
        cur, rec = pg
        cur.users.on_conflict(
            on=cur.sql.where(cur["a"] > 0).columns("a"),
            do=cur.sql.nothing(),
        ).append(id=1, a=5)
        sql, params = rec.last()
        assert 'ON CONFLICT ("a") WHERE a > %s DO NOTHING' in sql
        # Placeholder order in the SQL: INSERT's two, then the
        # ON CONFLICT WHERE clause.
        assert params == [1, 5, 0]

    def test_do_update_with_where(self, pg):
        cur, rec = pg
        cur.users.on_conflict(
            on=cur.sql.columns("a"),
            do=cur.sql.where(cur["t.id"] > 0).update(id=cur["EXCLUDED.id"]),
        ).append(id=2, a=5)
        sql, params = rec.last()
        assert (
            'ON CONFLICT ("a") DO UPDATE SET "id" = EXCLUDED.id '
            "WHERE t.id > %s"
        ) in sql
        # Placeholder order: INSERT's two, then DO UPDATE's WHERE.
        assert params == [2, 5, 0]

    def test_index_where_rejected_on_sqlite(self, sqlite):
        cur, _ = sqlite
        with pytest.raises(JustormDialectError):
            cur.users.on_conflict(
                on=cur.sql.where(cur["a"] > 0).columns("a"),
                do=cur.sql.nothing(),
            ).append(id=1, a=5)

# ---------------------------------------------------------------------------
# JOIN
# ---------------------------------------------------------------------------


class TestJoin:
    def test_inner_join(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.join(
            cur.orders,
            on=cur.users["id"] == cur.orders["user_id"],
        ).select()
        sql = rec.last_sql()
        assert 'FROM "users"' in sql
        assert 'JOIN "orders" ON "users"."id" = "orders"."user_id"' in sql

    def test_left_join(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.left_join(
            cur.orders,
            on=cur.users["id"] == cur.orders["user_id"],
        ).select()
        assert 'LEFT JOIN "orders"' in rec.last_sql()

    def test_using(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.join(cur.orders, using=("user_id",)).select()
        assert 'JOIN "orders" USING ("user_id")' in rec.last_sql()

    def test_on_and_using_mutually_exclusive(self, pg):
        cur, _ = pg
        with pytest.raises(JustormValueError):
            cur.users.join(
                cur.orders,
                on=cur.users["id"] == cur.orders["id"],
                using=("id",),
            )

    def test_join_requires_on_or_using(self, pg):
        cur, _ = pg
        with pytest.raises(JustormValueError):
            cur.users.join(cur.orders)

    def test_cross_join(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        cur.users.cross_join(cur.regions).select()
        assert 'CROSS JOIN "regions"' in rec.last_sql()

    def test_cross_join_rejects_on(self, pg):
        cur, _ = pg
        with pytest.raises(JustormValueError):
            cur.users.cross_join(
                cur.regions,
                on=cur.users["id"] == cur.regions["id"],
            )

    def test_how_and_typed_method_conflict(self, pg):
        cur, _ = pg
        with pytest.raises(TypeError):
            cur.users.left_join(
                cur.orders,
                on=cur.users["id"] == cur.orders["id"],
                how="right",
            )

    def test_alias(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        u = cur.users.as_("u")
        o = cur.orders.as_("o")
        u.join(o, on=u["id"] == o["user_id"]).select()
        sql = rec.last_sql()
        assert 'FROM "users" AS "u"' in sql
        assert 'JOIN "orders" AS "o"' in sql


# ---------------------------------------------------------------------------
# Subquery
# ---------------------------------------------------------------------------


class TestSubquery:
    def test_subquery_requires_alias(self, pg):
        cur, _ = pg
        sub = cur.orders.select_subquery({"user_id"})
        with pytest.raises((JustormTypeError, JustormValueError)):
            cur.users.join(sub, on=cur.users["id"] == sub["user_id"])

    def test_subquery_join(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        sub = cur.orders.where(
            cur.orders["total"] > 100
        ).select_subquery({"user_id"})
        s = sub.as_("s")
        cur.users.join(s, on=cur.users["id"] == s["user_id"]).select()
        sql = rec.last_sql()
        assert "JOIN (SELECT" in sql
        assert 'AS "s"' in sql


class TestSelectSubqueryShapes:
    def test_subquery_default_projection(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        sub = cur.orders.select_subquery()
        s = sub.as_("s")
        cur.users.join(s, on=cur.users["id"] == s["id"]).select()
        sql = rec.last_sql()
        assert 'JOIN (SELECT * FROM "orders") AS "s"' in sql

    def test_subquery_tuple_projection(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        sub = cur.orders.select_subquery(("id", "total"))
        s = sub.as_("s")
        cur.users.join(s, on=cur.users["id"] == s["id"]).select()
        sql = rec.last_sql()
        assert 'SELECT "id", "total" FROM "orders"' in sql

    def test_subquery_scalar_projection(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        sub = cur.orders.select_subquery("total")
        s = sub.as_("s")
        cur.users.join(s, on=cur.users["id"] == s["id"]).select()
        sql = rec.last_sql()
        assert 'SELECT "total" FROM "orders"' in sql

    def test_subquery_set_projection(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        sub = cur.orders.select_subquery({"id", "total"})
        s = sub.as_("s")
        cur.users.join(s, on=cur.users["id"] == s["id"]).select()
        sql = rec.last_sql()
        assert '"id"' in sql
        assert '"total"' in sql

    def test_subquery_where_carries_params(self, pg):
        cur, rec = pg
        rec.description = [("name",)]
        sub = cur.orders.where(
            cur.orders["total"] > 100
        ).select_subquery({"user_id"})
        s = sub.as_("s")
        cur.users.join(s, on=cur.users["id"] == s["user_id"]).select()
        sql, params = rec.last()
        assert (
            'SELECT "user_id" FROM "orders" '
            'WHERE ("orders"."total" > %s)'
        ) in sql
        assert params == [100]


class TestSubqueryNesting:
    def test_two_subqueries_joined(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        sub1 = cur.orders.where(
            cur.orders["total"] > 100
        ).select_subquery({"user_id"})
        sub2 = cur.users.where(
            cur.users["active"] == True  # noqa: E712
        ).select_subquery({"id"})
        s1 = sub1.as_("o")
        s2 = sub2.as_("u")
        cur.regions.join(s1, on=cur.regions["x"] == s1["user_id"]).join(
            s2, on=cur.regions["y"] == s2["id"]
        ).select()
        sql = rec.last_sql()
        assert "JOIN (SELECT" in sql
        assert 'AS "o"' in sql
        assert 'AS "u"' in sql

    def test_subquery_with_join_inside(self, pg):
        cur, rec = pg
        rec.description = [("x",)]
        inner = cur.users.join(
            cur.orders, on=cur.users["id"] == cur.orders["user_id"]
        ).where(cur.orders["total"] > 100).select_subquery(
            {cur.users["id"]}
        )
        s = inner.as_("s")
        cur.regions.join(s, on=cur.regions["x"] == s["id"]).select()
        sql = rec.last_sql()
        assert "JOIN (SELECT" in sql
        assert 'JOIN "orders" ON "users"."id" = "orders"."user_id"' in sql


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_where_returns_new_builder(self, pg):
        cur, rec = pg
        base = cur.users
        filtered = base.where(id=1)
        assert base is not filtered
        rec.description = [("id",)]
        base.select()
        filtered.select()
        assert rec.calls[0][0] == 'SELECT * FROM "users"'
        assert 'WHERE ("id" = %s)' in rec.calls[1][0]

    def test_reusing_builder_executes_twice(self, pg):
        cur, rec = pg
        rec.description = [("id",)]
        b = cur.users.where(id=1)
        b.select()
        b.select()
        assert len(rec.calls) == 2
        assert rec.calls[0] == rec.calls[1]
