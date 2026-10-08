"""sqlite3 cursor.

Usage::

    import sqlite3
    import justorm.sqlite

    conn = sqlite3.connect(":memory:")
    cur = justorm.sqlite.Cursor(conn)
    rows = cur.users.where(id=1).select()
    cur.fetchall(format=dict)
    cur.query("SELECT ... FROM ... JOIN ...")

Unlike the other drivers, ``sqlite3.Cursor`` is implemented in C and
**cannot be subclassed**.  justorm therefore wraps it instead of
inheriting from it.  The wrapper:

* mixes in :class:`justorm.renderer.SQLiteRenderer`,
  :class:`justorm.builder.JustBuilder`, and
  :class:`justorm._query.QueryMixin`,
* delegates every native DB-API method (``execute``, ``fetchone``,
  ``description``, ``rowcount``, ...) to an inner ``sqlite3.Cursor``,
* forwards attribute access (``cur.users``) and item access
  (``cur['...']``) to the justorm builder,
* extends the three ``fetch*`` methods with a ``format=`` keyword that
  selects ``tuple`` / ``dict`` / ``namedtuple`` output,
* adds ``query()``, a one-line "execute and shape the result" helper.

SQLite specifics exposed by justorm:

* identifiers are quoted with backticks,
* placeholders are ``?`` (so literal ``%`` does **not** need escaping),
* ``RETURNING`` is supported since SQLite 3.35,
* ``ON CONFLICT`` is supported since SQLite 3.24, but
  ``ON CONFLICT ON CONSTRAINT ...`` and the index predicate form are
  not,
* ``DISTINCT ON``, ``ILIKE`` and ``FOR UPDATE`` / ``FOR SHARE`` are
  not supported,
* ``DEFAULT`` is not accepted inside a ``VALUES`` list; missing keys
  are filled with ``NULL`` instead.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, List, Optional, Sequence

from justorm._fetch import convert_row, convert_rows
from justorm._query import QueryMixin
from justorm.builder import JustBuilder, TableBuilder
from justorm.renderer import SQLiteRenderer

__all__ = ["Cursor"]


class Cursor(QueryMixin, SQLiteRenderer, JustBuilder):
    """A wrapper around :class:`sqlite3.Cursor` with the justorm builder."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        cursor: Optional[sqlite3.Cursor] = None,
    ) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError(
                "justorm.sqlite.Cursor expects a sqlite3.Connection, "
                f"got {type(connection).__name__}"
            )
        self._conn = connection
        self._cursor = cursor if cursor is not None else connection.cursor()

    # ------------------------------------------------------------------
    # Native DB-API delegation
    # ------------------------------------------------------------------

    @property
    def connection(self) -> sqlite3.Connection:
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

    def execute(
        self, sql: str, parameters: Iterable[Any] = ()
    ) -> "Cursor":
        self._cursor.execute(sql, parameters)
        return self

    def executemany(
        self, sql: str, seq_of_parameters: Iterable[Iterable[Any]]
    ) -> "Cursor":
        self._cursor.executemany(sql, seq_of_parameters)
        return self

    def executescript(self, sql_script: str) -> "Cursor":
        self._cursor.executescript(sql_script)
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

    def setinputsizes(self, sizes: Any) -> None:
        self._cursor.setinputsizes(sizes)

    def setoutputsize(self, size: Any, column: Any = None) -> None:
        self._cursor.setoutputsize(size, column)

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
