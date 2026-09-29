"""pymssql cursor.

Usage::

    import pymssql
    import justorm.pymssql

    conn = pymssql.connect(...)
    cur = conn.cursor(justorm.pymssql.Cursor)
    rows = cur.users.where(id=1).select()
    cur.fetchall(format=dict)
    cur.query("SELECT ... FROM ... JOIN ...")

The cursor is a subclass of :class:`pymssql.Cursor`, so every native
attribute (``execute``, ``fetchone``, ``description``, ``rowcount``,
...) keeps working exactly as before.  justorm only *adds* the fluent
query builder on top, extends the ``fetch*`` methods with a
``format=`` keyword, and adds the ``query`` escape hatch.

PyMSSQL notes:

* the cursor can be subclassed (it is implemented in Cython, but the
  resulting type supports Python subclassing),
* ``%s`` is used for placeholders, and literal ``%`` in SQL text must
  be doubled,
* ``execute`` returns the number of affected rows (PEP 249),
* ``RETURNING`` is not available; the SQL Server equivalent is the
  ``OUTPUT`` clause, which justorm does not model,
* upserts use ``MERGE``, which justorm does not model,
* identifiers are quoted with square brackets.

Because pymssql ships no ``__getattr__``, attribute access for table
names goes through :class:`justorm.builder.JustBuilder` naturally.
We still override ``__getattr__`` on this class for consistency with
:mod:`justorm.pymysql`, where the override is required.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence

import pymssql
from pymssql import Cursor as _PyMSSQLCursor

from justorm._fetch import convert_row, convert_rows
from justorm._query import QueryMixin
from justorm.builder import JustBuilder, TableBuilder
from justorm.renderer import MSSQLRenderer

__all__ = ["Cursor"]


class Cursor(QueryMixin, _PyMSSQLCursor, MSSQLRenderer, JustBuilder):
    """A pymssql cursor with the justorm query builder mixed in."""

    # ------------------------------------------------------------------
    # fetch* with format=
    # ------------------------------------------------------------------

    def fetchone(self, *, format: Any = None) -> Any:
        row = super().fetchone()
        return convert_row(row, self.description, format)

    def fetchmany(
        self, size: Optional[int] = None, *, format: Any = None
    ) -> List[Any]:
        if size is None:
            rows = super().fetchmany()
        else:
            rows = super().fetchmany(size)
        return convert_rows(rows, self.description, format)

    def fetchall(self, *, format: Any = None) -> List[Any]:
        rows = super().fetchall()
        return convert_rows(rows, self.description, format)

    # ------------------------------------------------------------------
    # Attribute access
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> TableBuilder:
        if name.startswith("_"):
            raise AttributeError(name)
        if hasattr(type(self), name):
            raise AttributeError(name)
        return TableBuilder(self, name)

    def __getitem__(self, key: str):
        return JustBuilder.__getitem__(self, key)

    def table(self, *names: str) -> TableBuilder:
        return JustBuilder.table(self, *names)

    @property
    def sql(self):
        return JustBuilder.sql.fget(self)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Builder -> cursor glue
    # ------------------------------------------------------------------

    def _render_identifier(self, name: str) -> str:
        return self.render_identifier(name)

    def _render_identifier_multi(self, *names: str) -> str:
        return self.render_identifier_multi(*names)

    def _render_placeholder(self) -> str:
        return self.render_placeholder()

    def _render_keyword(self, keyword: str) -> str:
        return self.render_keyword(keyword)

    def _escape_percent(self, text: str) -> str:
        return self.escape_percent(text)

    def _render_returning(self, columns: Sequence[str]) -> str:
        return self.render_returning(columns)

    def _render_on_conflict(
        self, target: Optional[str], do_clause: str
    ) -> str:
        return self.render_on_conflict(target, do_clause)

    def _render_on_duplicate(self, update_clause: str) -> str:
        return self.render_on_duplicate(update_clause)

    def _render_limit_offset(
        self, limit: Optional[int], offset: Optional[int]
    ) -> str:
        return self.render_limit_offset(limit, offset)

    def _render_for_update(
        self,
        *,
        share: bool = False,
        skip_locked: bool = False,
        nowait: bool = False,
    ) -> str:
        return self.render_for_update(
            share=share,
            skip_locked=skip_locked,
            nowait=nowait,
        )

    def _render_distinct_on(self, columns: Sequence[str]) -> str:
        return self.render_distinct_on(columns)

    def _render_ilike(self, left: str, right: str) -> str:
        return self.render_ilike(left, right)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute(self, sql: str, params: Any) -> None:
        self.execute(sql, params)

    def _execute_and_fetch(
        self, sql: str, params: Any
    ) -> List[Any]:
        self.execute(sql, params)
        return self.fetchall()

    def _execute_and_fetch_one(
        self, sql: str, params: Any
    ) -> Any:
        self.execute(sql, params)
        return self.fetchone()

    def _execute_many(
        self, sql: str, param_sets: Iterable[Any]
    ) -> None:
        self.executemany(sql, list(param_sets))
