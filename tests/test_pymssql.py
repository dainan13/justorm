"""Smoke tests for ``justorm.pymssql``.

The pymssql driver requires a running SQL Server instance and the
``pymssql`` C extension.  Neither is assumed to be available in the
test environment, so these tests only check the *shape* of the module:
it imports cleanly (when pymssql is installed), the ``Cursor`` class
subclasses the driver's own cursor, and it mixes in the correct
renderer and builder.  No database connection is opened.

If ``pymssql`` is not installed the whole module is skipped by pytest.
"""

from __future__ import annotations

import pytest

pymssql = pytest.importorskip("pymssql")

import justorm.pymssql
from justorm.builder import JustBuilder
from justorm.renderer import MSSQLRenderer


pytestmark = pytest.mark.pymssql


class TestCursorClass:
    def test_module_imports(self):
        # The import at the top of this module is the real check; if it
        # fails, the test never runs.  This test exists so that the
        # module shows up in the test count.
        assert justorm.pymssql is not None

    def test_cursor_is_a_pymssql_cursor(self):
        assert issubclass(justorm.pymssql.Cursor, pymssql.Cursor)

    def test_cursor_is_a_mssql_renderer(self):
        assert issubclass(justorm.pymssql.Cursor, MSSQLRenderer)

    def test_cursor_is_a_just_builder(self):
        assert issubclass(justorm.pymssql.Cursor, JustBuilder)

    def test_dialect_name(self):
        assert justorm.pymssql.Cursor.dialect_name == "pymssql"

    def test_uses_named_placeholders(self):
        assert justorm.pymssql.Cursor.uses_named_placeholders is False

    def test_supports_values_default(self):
        assert justorm.pymssql.Cursor.supports_values_default is True

    def test_render_identifier_uses_brackets(self):
        cur = justorm.pymssql.Cursor.__new__(justorm.pymssql.Cursor)
        assert cur.render_identifier("users") == "[users]"
        assert cur.render_identifier("we]ird") == "[we]]ird]"

    def test_render_placeholder_is_percent_s(self):
        cur = justorm.pymssql.Cursor.__new__(justorm.pymssql.Cursor)
        assert cur.render_placeholder() == "%s"

    def test_render_returning_is_rejected(self):
        from justorm import JustormDialectError

        cur = justorm.pymssql.Cursor.__new__(justorm.pymssql.Cursor)
        with pytest.raises(JustormDialectError):
            cur.render_returning(["id"])

    def test_render_limit_offset(self):
        cur = justorm.pymssql.Cursor.__new__(justorm.pymssql.Cursor)
        assert (
            cur.render_limit_offset(10, 20)
            == "OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY"
        )

    def test_fetch_methods_accept_format(self):
        # We cannot call fetch without a live cursor, but we can check
        # that the signature accepts the ``format`` keyword.
        import inspect

        for name in ("fetchone", "fetchmany", "fetchall"):
            sig = inspect.signature(getattr(justorm.pymssql.Cursor, name))
            assert "format" in sig.parameters

    def test_has_query_method(self):
        assert hasattr(justorm.pymssql.Cursor, "query")
