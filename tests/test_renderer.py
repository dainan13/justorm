"""Tests for the dialect renderers.

The renderers are pure: they turn abstract pieces (identifiers,
placeholders, keywords, and a handful of dialect-specific clauses)
into SQL strings.  Nothing here touches a database or a driver, so
these tests run everywhere.

The goal is to pin down the *exact* text each renderer produces, so
that a regression in one dialect cannot silently change another.
"""

from __future__ import annotations

import pytest

from justorm import JustormDialectError
from justorm.renderer import (
    JustRenderABS,
    MSSQLRenderer,
    MySQLRenderer,
    OracleRenderer,
    PGRenderer,
    SQLiteRenderer,
)


# ---------------------------------------------------------------------------
# Test fixtures: one instance of each renderer.
# ---------------------------------------------------------------------------


@pytest.fixture()
def pg():
    return PGRenderer()


@pytest.fixture()
def mysql():
    return MySQLRenderer()


@pytest.fixture()
def sqlite():
    return SQLiteRenderer()


@pytest.fixture()
def mssql():
    return MSSQLRenderer()


@pytest.fixture()
def oracle():
    return OracleRenderer()


# ---------------------------------------------------------------------------
# The abstract base class.
# ---------------------------------------------------------------------------


class TestAbstractBase:
    def test_cannot_use_bare_base(self):
        base = JustRenderABS()
        with pytest.raises(NotImplementedError):
            base.render_identifier("a")
        with pytest.raises(NotImplementedError):
            base.render_placeholder()
        with pytest.raises(NotImplementedError):
            base.render_returning(["a"])

    def test_dialect_name_default(self):
        assert JustRenderABS.dialect_name == "unknown"

    def test_uses_named_placeholders_default(self):
        assert JustRenderABS.uses_named_placeholders is False


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------


class TestIdentifiers:
    def test_pg_quotes_with_double_quotes(self, pg):
        assert pg.render_identifier("users") == '"users"'

    def test_pg_doubles_embedded_quotes(self, pg):
        assert pg.render_identifier('we"ird') == '"we""ird"'

    def test_mysql_quotes_with_backticks(self, mysql):
        assert mysql.render_identifier("users") == "`users`"

    def test_mysql_doubles_embedded_backticks(self, mysql):
        assert mysql.render_identifier("we`ird") == "`we``ird`"

    def test_sqlite_quotes_with_backticks(self, sqlite):
        # SQLite accepts both ``"name"`` and ``` `name` ```.  The
        # renderer uses backticks because the double-quoted form falls
        # back to a string literal when the identifier is missing, which
        # masks "no such column" errors.
        assert sqlite.render_identifier("users") == "`users`"

    def test_sqlite_doubles_embedded_backticks(self, sqlite):
        assert sqlite.render_identifier("we`ird") == "`we``ird`"

    def test_sqlite_preserves_embedded_quotes(self, sqlite):
        # Double quotes are not special inside a backtick-quoted
        # identifier; they must not be escaped.
        assert sqlite.render_identifier('we"ird') == '`we"ird`'

    def test_mssql_quotes_with_brackets(self, mssql):
        assert mssql.render_identifier("users") == "[users]"

    def test_mssql_doubles_embedded_brackets(self, mssql):
        assert mssql.render_identifier("we]ird") == "[we]]ird]"

    def test_oracle_quotes_with_double_quotes(self, oracle):
        assert oracle.render_identifier("users") == '"users"'

    def test_oracle_doubles_embedded_quotes(self, oracle):
        assert oracle.render_identifier('we"ird') == '"we""ird"'

    def test_multi_part_pg(self, pg):
        assert pg.render_identifier_multi("public", "users") == '"public"."users"'

    def test_multi_part_mysql(self, mysql):
        assert mysql.render_identifier_multi("mydb", "users") == "`mydb`.`users`"

    def test_multi_part_mssql(self, mssql):
        assert mssql.render_identifier_multi("dbo", "users") == "[dbo].[users]"

    def test_multi_part_oracle(self, oracle):
        assert oracle.render_identifier_multi("schema", "users") == '"schema"."users"'

    def test_multi_part_requires_at_least_one(self, pg):
        with pytest.raises(ValueError):
            pg.render_identifier_multi()


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------


class TestPlaceholders:
    def test_pg(self, pg):
        assert pg.render_placeholder() == "%s"

    def test_mysql(self, mysql):
        assert mysql.render_placeholder() == "%s"

    def test_sqlite(self, sqlite):
        assert sqlite.render_placeholder() == "?"

    def test_mssql(self, mssql):
        assert mssql.render_placeholder() == "%s"

    def test_oracle(self, oracle):
        # Oracle actually uses named placeholders; the builder detects
        # this via ``uses_named_placeholders`` and generates its own
        # random names.  The method still returns a sensible default.
        assert oracle.render_placeholder() == ":p"

    def test_placeholder_list_pg(self, pg):
        assert pg.render_placeholder_list(3) == "%s, %s, %s"

    def test_placeholder_list_sqlite(self, sqlite):
        assert sqlite.render_placeholder_list(3) == "?, ?, ?"

    def test_placeholder_list_zero(self, pg):
        assert pg.render_placeholder_list(0) == ""

    def test_placeholder_list_negative_rejected(self, pg):
        with pytest.raises(ValueError):
            pg.render_placeholder_list(-1)


# ---------------------------------------------------------------------------
# Named placeholders flag
# ---------------------------------------------------------------------------


class TestUsesNamedPlaceholders:
    def test_pg(self, pg):
        assert pg.uses_named_placeholders is False

    def test_mysql(self, mysql):
        assert mysql.uses_named_placeholders is False

    def test_sqlite(self, sqlite):
        assert sqlite.uses_named_placeholders is False

    def test_mssql(self, mssql):
        assert mssql.uses_named_placeholders is False

    def test_oracle(self, oracle):
        assert oracle.uses_named_placeholders is True


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


class TestKeywords:
    def test_default_keyword_unchanged(self, pg):
        assert pg.render_keyword("DEFAULT") == "DEFAULT"

    def test_keyword_any_dialect(self, mysql, sqlite, mssql, oracle):
        assert mysql.render_keyword("DEFAULT") == "DEFAULT"
        assert sqlite.render_keyword("DEFAULT") == "DEFAULT"
        assert mssql.render_keyword("DEFAULT") == "DEFAULT"
        assert oracle.render_keyword("DEFAULT") == "DEFAULT"


# ---------------------------------------------------------------------------
# Percent escaping
# ---------------------------------------------------------------------------


class TestPercentEscaping:
    def test_pg_doubles_percent(self, pg):
        assert pg.escape_percent("a % b") == "a %% b"

    def test_psycopg2_shares_pg(self):
        from justorm.renderer import PGRenderer as PG2

        assert PG2 is PGRenderer

    def test_mysql_doubles_percent(self, mysql):
        assert mysql.escape_percent("a % b") == "a %% b"

    def test_sqlite_leaves_percent(self, sqlite):
        assert sqlite.escape_percent("a % b") == "a % b"

    def test_mssql_doubles_percent(self, mssql):
        assert mssql.escape_percent("a % b") == "a %% b"

    def test_oracle_leaves_percent(self, oracle):
        # Oracle uses named placeholders (``:p``), so ``%`` is a
        # literal character.
        assert oracle.escape_percent("a % b") == "a % b"

    def test_pg_doubles_multiple(self, pg):
        assert pg.escape_percent("%%") == "%%%%"

    def test_sqlite_leaves_empty(self, sqlite):
        assert sqlite.escape_percent("") == ""


# ---------------------------------------------------------------------------
# RETURNING
# ---------------------------------------------------------------------------


class TestReturning:
    def test_pg_single(self, pg):
        assert pg.render_returning(["id"]) == "RETURNING id"

    def test_pg_multiple(self, pg):
        assert pg.render_returning(["id", "name"]) == "RETURNING id, name"

    def test_pg_empty(self, pg):
        assert pg.render_returning([]) == ""

    def test_sqlite_single(self, sqlite):
        assert sqlite.render_returning(["id"]) == "RETURNING id"

    def test_mysql_rejects(self, mysql):
        with pytest.raises(JustormDialectError):
            mysql.render_returning(["id"])

    def test_mssql_rejects(self, mssql):
        with pytest.raises(JustormDialectError):
            mssql.render_returning(["id"])

    def test_oracle_rejects(self, oracle):
        with pytest.raises(JustormDialectError):
            oracle.render_returning(["id"])


# ---------------------------------------------------------------------------
# ON CONFLICT / ON DUPLICATE
# ---------------------------------------------------------------------------


class TestOnConflict:
    def test_pg_no_target(self, pg):
        assert pg.render_on_conflict(None, "DO NOTHING") == "ON CONFLICT DO NOTHING"

    def test_pg_with_target(self, pg):
        out = pg.render_on_conflict('"id"', "DO NOTHING")
        assert out == 'ON CONFLICT "id" DO NOTHING'

    def test_pg_do_update(self, pg):
        out = pg.render_on_conflict('"id"', 'DO UPDATE SET "name" = EXCLUDED.name')
        assert out == 'ON CONFLICT "id" DO UPDATE SET "name" = EXCLUDED.name'

    def test_sqlite_no_target(self, sqlite):
        assert sqlite.render_on_conflict(None, "DO NOTHING") == "ON CONFLICT DO NOTHING"

    def test_sqlite_with_target(self, sqlite):
        out = sqlite.render_on_conflict('"id"', "DO NOTHING")
        assert out == 'ON CONFLICT "id" DO NOTHING'

    def test_mysql_rejects_on_conflict(self, mysql):
        with pytest.raises(JustormDialectError):
            mysql.render_on_conflict(None, "DO NOTHING")

    def test_mssql_rejects_on_conflict(self, mssql):
        with pytest.raises(JustormDialectError):
            mssql.render_on_conflict(None, "DO NOTHING")

    def test_oracle_rejects_on_conflict(self, oracle):
        with pytest.raises(JustormDialectError):
            oracle.render_on_conflict(None, "DO NOTHING")


class TestOnConflictTarget:
    def test_pg_columns(self, pg):
        assert pg.render_on_conflict_target(["id"], None, None) == '("id")'

    def test_pg_columns_multi(self, pg):
        assert pg.render_on_conflict_target(["a", "b"], None, None) == '("a", "b")'

    def test_pg_constraint(self, pg):
        assert (
            pg.render_on_conflict_target(None, "users_pkey", None)
            == 'ON CONSTRAINT "users_pkey"'
        )

    def test_pg_columns_with_index_where(self, pg):
        out = pg.render_on_conflict_target(["email"], None, "deleted_at IS NULL")
        assert out == '("email") WHERE deleted_at IS NULL'

    def test_pg_no_target(self, pg):
        assert pg.render_on_conflict_target(None, None, None) == ""

    def test_sqlite_columns(self, sqlite):
        assert sqlite.render_on_conflict_target(["id"], None, None) == "(`id`)"

    def test_sqlite_constraint_rejected(self, sqlite):
        with pytest.raises(JustormDialectError):
            sqlite.render_on_conflict_target(None, "some_name", None)

    def test_sqlite_index_where_rejected(self, sqlite):
        with pytest.raises(JustormDialectError):
            sqlite.render_on_conflict_target(["email"], None, "deleted_at IS NULL")

    def test_mysql_rejects(self, mysql):
        with pytest.raises(JustormDialectError):
            mysql.render_on_conflict_target(["id"], None, None)

    def test_mssql_rejects(self, mssql):
        with pytest.raises(JustormDialectError):
            mssql.render_on_conflict_target(["id"], None, None)

    def test_oracle_rejects(self, oracle):
        with pytest.raises(JustormDialectError):
            oracle.render_on_conflict_target(["id"], None, None)


class TestOnDuplicate:
    def test_mysql(self, mysql):
        out = mysql.render_on_duplicate('`name` = VALUES(name)')
        assert out == "ON DUPLICATE KEY UPDATE `name` = VALUES(name)"

    def test_mysql_empty_rejected(self, mysql):
        with pytest.raises(ValueError):
            mysql.render_on_duplicate("")

    def test_pg_rejects(self, pg):
        with pytest.raises(JustormDialectError):
            pg.render_on_duplicate('"name" = 1')

    def test_sqlite_rejects(self, sqlite):
        with pytest.raises(JustormDialectError):
            sqlite.render_on_duplicate('"name" = 1')

    def test_mssql_rejects(self, mssql):
        with pytest.raises(JustormDialectError):
            mssql.render_on_duplicate('"name" = 1')

    def test_oracle_rejects(self, oracle):
        with pytest.raises(JustormDialectError):
            oracle.render_on_duplicate('"name" = 1')


# ---------------------------------------------------------------------------
# LIMIT / OFFSET
# ---------------------------------------------------------------------------


class TestLimitOffset:
    def test_pg_both(self, pg):
        assert pg.render_limit_offset(10, 20) == "LIMIT 10 OFFSET 20"

    def test_pg_limit_only(self, pg):
        assert pg.render_limit_offset(10, None) == "LIMIT 10"

    def test_pg_offset_only(self, pg):
        assert pg.render_limit_offset(None, 20) == "OFFSET 20"

    def test_pg_neither(self, pg):
        assert pg.render_limit_offset(None, None) == ""

    def test_mysql_both(self, mysql):
        assert mysql.render_limit_offset(10, 20) == "LIMIT 10 OFFSET 20"

    def test_mysql_offset_without_limit_rejected(self, mysql):
        with pytest.raises(ValueError):
            mysql.render_limit_offset(None, 20)

    def test_sqlite_both(self, sqlite):
        assert sqlite.render_limit_offset(10, 20) == "LIMIT 10 OFFSET 20"

    def test_sqlite_offset_without_limit_uses_negative(self, sqlite):
        assert sqlite.render_limit_offset(None, 20) == "LIMIT -1 OFFSET 20"

    def test_pg_values_are_integers(self, pg):
        assert pg.render_limit_offset("10", "20") == "LIMIT 10 OFFSET 20"

    def test_mssql_both(self, mssql):
        assert (
            mssql.render_limit_offset(10, 20)
            == "OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY"
        )

    def test_mssql_limit_only(self, mssql):
        # SQL Server requires OFFSET before FETCH, so a bare LIMIT
        # becomes ``OFFSET 0 ROWS FETCH NEXT n ROWS ONLY``.
        assert (
            mssql.render_limit_offset(10, None)
            == "OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY"
        )

    def test_mssql_offset_only(self, mssql):
        assert (
            mssql.render_limit_offset(None, 20)
            == "OFFSET 20 ROWS"
        )

    def test_mssql_neither(self, mssql):
        assert mssql.render_limit_offset(None, None) == ""

    def test_oracle_both(self, oracle):
        assert (
            oracle.render_limit_offset(10, 20)
            == "OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY"
        )

    def test_oracle_limit_only(self, oracle):
        assert (
            oracle.render_limit_offset(10, None)
            == "FETCH NEXT 10 ROWS ONLY"
        )

    def test_oracle_offset_only(self, oracle):
        assert (
            oracle.render_limit_offset(None, 20)
            == "OFFSET 20 ROWS"
        )

    def test_oracle_neither(self, oracle):
        assert oracle.render_limit_offset(None, None) == ""


# ---------------------------------------------------------------------------
# FOR UPDATE / FOR SHARE
# ---------------------------------------------------------------------------


class TestForUpdate:
    def test_pg_update(self, pg):
        assert pg.render_for_update() == "FOR UPDATE"

    def test_pg_share(self, pg):
        assert pg.render_for_update(share=True) == "FOR SHARE"

    def test_pg_nowait(self, pg):
        assert pg.render_for_update(nowait=True) == "FOR UPDATE NOWAIT"

    def test_pg_skip_locked(self, pg):
        assert pg.render_for_update(skip_locked=True) == "FOR UPDATE SKIP LOCKED"

    def test_pg_nowait_and_skip_locked_conflict(self, pg):
        with pytest.raises(ValueError):
            pg.render_for_update(nowait=True, skip_locked=True)

    def test_mysql_update(self, mysql):
        assert mysql.render_for_update() == "FOR UPDATE"

    def test_mysql_share(self, mysql):
        assert mysql.render_for_update(share=True) == "FOR SHARE"

    def test_mysql_nowait(self, mysql):
        assert mysql.render_for_update(nowait=True) == "FOR UPDATE NOWAIT"

    def test_mysql_skip_locked(self, mysql):
        assert mysql.render_for_update(skip_locked=True) == "FOR UPDATE SKIP LOCKED"

    def test_sqlite_rejects(self, sqlite):
        with pytest.raises(JustormDialectError):
            sqlite.render_for_update()

    def test_mssql_rejects(self, mssql):
        with pytest.raises(JustormDialectError):
            mssql.render_for_update()

    def test_oracle_update(self, oracle):
        assert oracle.render_for_update() == "FOR UPDATE"

    def test_oracle_nowait(self, oracle):
        assert oracle.render_for_update(nowait=True) == "FOR UPDATE NOWAIT"

    def test_oracle_skip_locked(self, oracle):
        assert oracle.render_for_update(skip_locked=True) == "FOR UPDATE SKIP LOCKED"

    def test_oracle_share_treated_as_update(self, oracle):
        # Oracle has no FOR SHARE; the renderer emits FOR UPDATE so the
        # caller's intent (lock the rows) still holds.
        assert oracle.render_for_update(share=True) == "FOR UPDATE"


# ---------------------------------------------------------------------------
# DISTINCT ON
# ---------------------------------------------------------------------------


class TestDistinctOn:
    def test_pg(self, pg):
        assert pg.render_distinct_on(["name"]) == 'DISTINCT ON ("name")'

    def test_pg_multiple(self, pg):
        assert pg.render_distinct_on(["name", "age"]) == 'DISTINCT ON ("name", "age")'

    def test_pg_empty_rejected(self, pg):
        with pytest.raises(ValueError):
            pg.render_distinct_on([])

    def test_mysql_rejects(self, mysql):
        with pytest.raises(JustormDialectError):
            mysql.render_distinct_on(["name"])

    def test_sqlite_rejects(self, sqlite):
        with pytest.raises(JustormDialectError):
            sqlite.render_distinct_on(["name"])

    def test_mssql_rejects(self, mssql):
        with pytest.raises(JustormDialectError):
            mssql.render_distinct_on(["name"])

    def test_oracle_rejects(self, oracle):
        with pytest.raises(JustormDialectError):
            oracle.render_distinct_on(["name"])


# ---------------------------------------------------------------------------
# ILIKE
# ---------------------------------------------------------------------------


class TestIlike:
    def test_pg(self, pg):
        assert pg.render_ilike('"name"', "%s") == '"name" ILIKE %s'

    def test_mysql_rejects(self, mysql):
        with pytest.raises(JustormDialectError):
            mysql.render_ilike("`name`", "%s")

    def test_sqlite_rejects(self, sqlite):
        with pytest.raises(JustormDialectError):
            sqlite.render_ilike('"name"', "?")

    def test_mssql_rejects(self, mssql):
        with pytest.raises(JustormDialectError):
            mssql.render_ilike("[name]", "%s")

    def test_oracle_rejects(self, oracle):
        with pytest.raises(JustormDialectError):
            oracle.render_ilike('"name"', ":p1")


# ---------------------------------------------------------------------------
# supports_values_default
# ---------------------------------------------------------------------------


class TestSupportsValuesDefault:
    def test_pg_supports_default(self, pg):
        assert pg.supports_values_default is True

    def test_mysql_supports_default(self, mysql):
        assert mysql.supports_values_default is True

    def test_sqlite_does_not_support_default(self, sqlite):
        assert sqlite.supports_values_default is False

    def test_mssql_supports_default(self, mssql):
        assert mssql.supports_values_default is True

    def test_oracle_does_not_support_default(self, oracle):
        assert oracle.supports_values_default is False



class TestTableAliasUsesAs:
    def test_pg(self, pg):
        assert pg.table_alias_uses_as is True

    def test_mysql(self, mysql):
        assert mysql.table_alias_uses_as is True

    def test_sqlite(self, sqlite):
        assert sqlite.table_alias_uses_as is True

    def test_mssql(self, mssql):
        assert mssql.table_alias_uses_as is True

    def test_oracle(self, oracle):
        assert oracle.table_alias_uses_as is False
        
# ---------------------------------------------------------------------------
# Cross-dialect sanity
# ---------------------------------------------------------------------------


class TestCrossDialect:
    def test_identifier_quoting_differs(self):
        assert PGRenderer().render_identifier("a") == '"a"'
        assert MySQLRenderer().render_identifier("a") == "`a`"
        assert SQLiteRenderer().render_identifier("a") == "`a`"
        assert MSSQLRenderer().render_identifier("a") == "[a]"
        assert OracleRenderer().render_identifier("a") == '"a"'

    def test_placeholder_differs(self):
        assert PGRenderer().render_placeholder() == "%s"
        assert MySQLRenderer().render_placeholder() == "%s"
        assert SQLiteRenderer().render_placeholder() == "?"
        assert MSSQLRenderer().render_placeholder() == "%s"
        assert OracleRenderer().render_placeholder() == ":p"

    def test_percent_escaping_differs(self):
        assert PGRenderer().escape_percent("%") == "%%"
        assert MySQLRenderer().escape_percent("%") == "%%"
        assert SQLiteRenderer().escape_percent("%") == "%"
        assert MSSQLRenderer().escape_percent("%") == "%%"
        assert OracleRenderer().escape_percent("%") == "%"

    def test_dialect_names(self):
        assert PGRenderer.dialect_name == "postgresql"
        assert MySQLRenderer.dialect_name == "mysql"
        assert SQLiteRenderer.dialect_name == "sqlite"
        assert MSSQLRenderer.dialect_name == "pymssql"
        assert OracleRenderer.dialect_name == "oracledb"

    def test_all_renderers_are_just_render_abc(self):
        for cls in (
            PGRenderer,
            MySQLRenderer,
            SQLiteRenderer,
            MSSQLRenderer,
            OracleRenderer,
        ):
            assert issubclass(cls, JustRenderABS)

    def test_psycopg_and_psycopg2_share_renderer(self):
        from justorm.renderer import PGRenderer as Renderer

        assert Renderer is PGRenderer

    def test_only_oracle_uses_named_placeholders(self):
        named = [
            cls.__name__
            for cls in (
                PGRenderer,
                MySQLRenderer,
                SQLiteRenderer,
                MSSQLRenderer,
                OracleRenderer,
            )
            if cls.uses_named_placeholders
        ]
        assert named == ["OracleRenderer"]

    def test_only_sqlite_and_oracle_lack_values_default(self):
        no_default = [
            cls.__name__
            for cls in (
                PGRenderer,
                MySQLRenderer,
                SQLiteRenderer,
                MSSQLRenderer,
                OracleRenderer,
            )
            if not cls.supports_values_default
        ]
        assert sorted(no_default) == ["OracleRenderer", "SQLiteRenderer"]
