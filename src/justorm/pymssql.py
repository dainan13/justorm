"""pymssql cursor.

Usage::

    import pymssql
    import justorm.pymssql

    conn = pymssql.connect(...)
    cur = justorm.pymssql.Cursor(conn)
    rows = cur.users.where(id=1).select()
    cur.fetchall(format=dict)
    cur.query("SELECT ... FROM ... JOIN ...")

Unlike the other drivers, the pymssql connection does not expose a
cursor factory: ``Connection.cursor()`` returns the driver's own
cursor class and does not accept a replacement.  And while
``pymssql.Cursor`` *can* be subclassed, its ``__init__`` requires a
positional ``as_dict`` argument that is easy to get wrong.  justorm
therefore **wraps** the driver cursor, in the same way it wraps
``sqlite3.Cursor``, rather than inheriting from it.

The wrapper:

* mixes in :class:`justorm.renderer.MSSQLRenderer`,
  :class:`justorm.builder.JustBuilder`, and
  :class:`justorm._query.QueryMixin`,
* delegates every native DB-API method (``execute``, ``fetchone``,
  ``description``, ``rowcount``, ...) to an inner ``pymssql.Cursor``,
* forwards attribute access (``cur.users``) and item access
  (``cur['...']``) to the justorm builder,
* extends the three ``fetch*`` methods with a ``format=`` keyword that
  selects ``tuple`` / ``dict`` / ``namedtuple`` output,
* adds ``query()``, a one-line "execute and shape the result" helper.

SQL Server specifics exposed by justorm:

* identifiers are quoted with square brackets,
* ``%s`` is used for placeholders, and literal ``%`` in SQL text must
  be doubled,
* ``execute`` returns the number of affected rows (PEP 249),
* ``RETURNING`` is not available; the SQL Server equivalent is the
  ``OUTPUT`` clause, which has a different shape and is best written
  as raw SQL,
* upserts use ``MERGE``, which justorm does not model,
* ``LIMIT`` / ``OFFSET`` map to ``OFFSET ... ROWS FETCH NEXT ...
  ROWS ONLY``, which requires an ``ORDER BY`` clause,
* ``FOR UPDATE`` is not a thing on SQL Server; row locking is done
  through table hints such as ``WITH (UPDLOCK)``,
* ``DISTINCT ON`` and ``ILIKE`` are not available,
* ``DEFAULT`` is accepted inside a ``VALUES`` list.
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


class Cursor(QueryMixin, MSSQLRenderer, JustBuilder):
    """A wrapper around :class:`pymssql.Cursor` with the justorm builder."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        connection: pymssql.Connection,
        *,
        cursor: Optional[_PyMSSQLCursor] = None,
    ) -> None:
        if not isinstance(connection, pymssql.Connection):
            raise TypeError(
                "justorm.pymssql.Cursor expects a pymssql.Connection, "
                f"got {type(connection).__name__}"
            )
        self._conn = connection
        # ``Connection.cursor()`` takes optional ``as_dict`` and
        # ``arraysize`` arguments; with no arguments it uses the
        # connection's defaults, which is what we want.
        self._cursor = cursor if cursor is not None else connection.cursor()

    # ------------------------------------------------------------------
    # Native DB-API delegation
    # ------------------------------------------------------------------

    @property
    def connection(self) -> pymssql.Connection:
        return self._conn

    @property
    def description(self) -> Any:
        return self._cursor.description

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> Optional[int]:
        return self._cursor.lastrowid

    @property
    def arraysize(self) -> int:
        return self._cursor.arraysize

    @arraysize.setter
    def arraysize(self, value: int) -> None:
        self._cursor.arraysize = value

    def execute(self, sql: str, parameters: Any = ()) -> "Cursor":
        self._cursor.execute(sql, parameters)
        return self

    def executemany(
        self, sql: str, seq_of_parameters: Iterable[Iterable[Any]]
    ) -> "Cursor":
        self._cursor.executemany(sql, seq_of_parameters)
        return self

    def fetchone(self, *, format: Any = None) -> Any:
        row = self._cursor.fetchone()
        return convert_row(row, self._cursor.description, format)

    def fetchmany(
        self, size: Optional[int] = None, *, format: Any = None
    ) -> List[Any]:
        if size is None:
            rows = self._cursor.fetchmany()
        else:
            rows = self._cursor.fetchmany(size)
        return convert_rows(rows, self._cursor.description, format)

    def fetchall(self, *, format: Any = None) -> List[Any]:
        rows = self._cursor.fetchall()
        return convert_rows(rows, self._cursor.description, format)

    def close(self) -> None:
        try:
            self._cursor.close()
        except Exception:
            pass

    def __iter__(self) -> Any:
        return iter(self._cursor)

    def __enter__(self) -> "Cursor":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Attribute and subscript access
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
        self._cursor.execute(sql, params)

    def _just_execute_and_fetch(
        self, sql: str, params: Any
    ) -> List[Any]:
        self._cursor.execute(sql, params)
        return self._cursor.fetchall()

    def _just_execute_and_fetch_one(
        self, sql: str, params: Any
    ) -> Any:
        self._cursor.execute(sql, params)
        return self._cursor.fetchone()

    def _just_execute_many(
        self, sql: str, param_sets: Iterable[Any]
    ) -> None:
        self._cursor.executemany(sql, list(param_sets))
        