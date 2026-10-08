"""python-oracledb cursor.

Usage::

    import oracledb
    import justorm.oracledb

    conn = oracledb.connect(...)
    cur = conn.cursor(justorm.oracledb.Cursor)
    rows = cur.users.where(id=1).select()
    cur.fetchall(format=dict)
    cur.query("SELECT ... FROM ... JOIN ...")

The cursor is a subclass of :class:`oracledb.Cursor`, so every native
attribute (``execute``, ``fetchone``, ``description``, ``rowcount``,
...) keeps working exactly as before.  justorm only *adds* the fluent
query builder on top, extends the ``fetch*`` methods with a
``format=`` keyword, and adds the ``query`` escape hatch.

python-oracledb notes:

* ``execute`` returns the cursor (like psycopg3), so the cursor can be
  iterated directly after ``execute``,
* placeholders are **named** (``:name``); :class:`justorm.renderer.OracleRenderer`
  sets ``uses_named_placeholders = True``, which makes the builder
  generate random ``:p<hex>`` names and pass parameters as a dict,
* ``lastrowid`` returns the rowid of the last modified row as a
  **string** (or ``None``); this is not an auto-increment id, so
  ``justorm._query`` treats it as "not a real lastrowid" and falls
  back to ``rowcount`` for INSERT statements,
* ``RETURNING`` requires an OUT bind variable and is not modelled,
* upserts use ``MERGE``, which justorm does not model,
* identifiers are quoted with double quotes (Oracle folds unquoted
  identifiers to uppercase, which surprises most users, so justorm
  always quotes),
* ``LIMIT`` / ``OFFSET`` map to ``OFFSET ... ROWS FETCH NEXT ...
  ROWS ONLY`` (12c+),
* ``FOR UPDATE`` is supported, with ``NOWAIT`` / ``SKIP LOCKED``,
* ``DEFAULT`` is not accepted inside a ``VALUES`` list.

Attribute access for table names goes through
:class:`justorm.builder.JustBuilder`; ``__getattr__`` is overridden
here for consistency with the other drivers and to avoid surprises
if a future version of python-oracledb adds its own.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence

import oracledb
from oracledb import Cursor as _OracleCursor

from justorm._fetch import convert_row, convert_rows
from justorm._query import QueryMixin
from justorm.builder import JustBuilder, TableBuilder
from justorm.renderer import OracleRenderer

__all__ = ["Cursor"]


class Cursor(QueryMixin, _OracleCursor, OracleRenderer, JustBuilder):
    """A python-oracledb cursor with the justorm query builder mixed in."""

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

    def _just_execute(self, sql: str, params: Any) -> None:
        self.execute(sql, params)

    def _just_execute_and_fetch(
        self, sql: str, params: Any
    ) -> List[Any]:
        self.execute(sql, params)
        return self.fetchall()

    def _just_execute_and_fetch_one(
        self, sql: str, params: Any
    ) -> Any:
        self.execute(sql, params)
        return self.fetchone()

    def _just_execute_many(
        self, sql: str, param_sets: Iterable[Any]
    ) -> None:
        self.executemany(sql, list(param_sets))
