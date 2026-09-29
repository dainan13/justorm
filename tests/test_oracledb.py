"""Smoke tests for ``justorm.oracledb``.

The python-oracledb driver requires a running Oracle instance (or the
Oracle client libraries at least) and is not assumed to be available
in the test environment.  These tests only check the *shape* of the
module: it imports cleanly (when oracledb is installed), the
``Cursor`` class subclasses the driver's own cursor, and it mixes in
the correct renderer and builder.  No database connection is opened.

If ``oracledb`` is not installed the whole module is skipped by
pytest.
"""

from __future__ import annotations

import pytest

oracledb = pytest.importorskip("oracledb")

import justorm.oracledb
from justorm.builder import JustBuilder
from justorm.renderer import OracleRenderer


pytestmark = pytest.mark.oracledb


class TestCursorClass:
    def test_module_imports(self):
        assert justorm.oracledb is not None

    def test_cursor_is_an_oracledb_cursor(self):
        assert issubclass(justorm.oracledb.Cursor, oracledb.Cursor)

    def test_cursor_is_an_oracle_renderer(self):
        assert issubclass(justorm.oracledb.Cursor, OracleRenderer)

    def test_cursor_is_a_just_builder(self):
        assert issubclass(justorm.oracledb.Cursor, JustBuilder)

    def test_dialect_name(self):
        assert justorm.oracledb.Cursor.dialect_name == "oracledb"

    def test_uses_named_placeholders(self):
        assert justorm.oracledb.Cursor.uses_named_placeholders is True

    def test_supports_values_default(self):
        assert justorm.oracledb.Cursor.supports_values_default is False

    def test_render_identifier_uses_double_quotes(self):
        cur = justorm.oracledb.Cursor.__new__(justorm.oracledb.Cursor)
        assert cur.render_identifier("users") == '"users"'
        assert cur.render_identifier('we"ird') == '"we""ird"'

    def test_render_placeholder_default(self):
        cur = justorm.oracledb.Cursor.__new__(justorm.oracledb.Cursor)
        # The builder does not use this method when
        # ``uses_named_placeholders`` is True; it generates random
        # names of its own.  The method still returns a useful default.
        assert cur.render_placeholder() == ":p"

    def test_render_returning_is_rejected(self):
        from justorm import JustormDialectError

        cur = justorm.oracledb.Cursor.__new__(justorm.oracledb.Cursor)
        with pytest.raises(JustormDialectError):
            cur.render_returning(["id"])

    def test_render_on_conflict_is_rejected(self):
        from justorm import JustormDialectError

        cur = justorm.oracledb.Cursor.__new__(justorm.oracledb.Cursor)
        with pytest.raises(JustormDialectError):
            cur.render_on_conflict(None, "DO NOTHING")

    def test_render_on_duplicate_is_rejected(self):
        from justorm import JustormDialectError

        cur = justorm.oracledb.Cursor.__new__(justorm.oracledb.Cursor)
        with pytest.raises(JustormDialectError):
            cur.render_on_duplicate("x = 1")

    def test_render_limit_offset(self):
        cur = justorm.oracledb.Cursor.__new__(justorm.oracledb.Cursor)
        assert (
            cur.render_limit_offset(10, 20)
            == "OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY"
        )
        assert cur.render_limit_offset(10, None) == "FETCH NEXT 10 ROWS ONLY"
        assert cur.render_limit_offset(None, 20) == "OFFSET 20 ROWS"

    def test_render_for_update(self):
        cur = justorm.oracledb.Cursor.__new__(justorm.oracledb.Cursor)
        assert cur.render_for_update() == "FOR UPDATE"
        assert cur.render_for_update(nowait=True) == "FOR UPDATE NOWAIT"
        assert cur.render_for_update(skip_locked=True) == "FOR UPDATE SKIP LOCKED"
        # Oracle has no FOR SHARE; the renderer maps ``share`` to
        # FOR UPDATE so the caller's lock intent still holds.
        assert cur.render_for_update(share=True) == "FOR UPDATE"

    def test_fetch_methods_accept_format(self):
        import inspect

        for name in ("fetchone", "fetchmany", "fetchall"):
            sig = inspect.signature(getattr(justorm.oracledb.Cursor, name))
            assert "format" in sig.parameters

    def test_has_query_method(self):
        assert hasattr(justorm.oracledb.Cursor, "query")
