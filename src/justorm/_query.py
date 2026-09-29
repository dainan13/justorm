"""The ``query()`` mixin.

``query`` is the escape hatch for SQL that the builder cannot express:
complex joins, window functions, CTEs, dialect-specific syntax.  It is
not a replacement for ``execute`` / ``fetchall``; it is a convenience
that performs those two steps and shapes the result the way the rest
of justorm does.

Result shape
------------

* If the cursor has a ``description`` (i.e. the statement returned a
  result set), ``query`` returns ``list[dict]`` — one dict per row,
  keyed by column name.  This matches what ``TableBuilder.select()``
  returns, so a query is a drop-in for a builder call that could not
  be written.

* If the cursor has no ``description`` (a DML or DDL statement), the
  return value is an ``int``:

  * ``UPDATE`` / ``DELETE`` → ``cursor.rowcount``.
  * Anything else (``INSERT``, ``CREATE``, ...) → ``cursor.lastrowid``
    when the driver provides a *real* one, otherwise ``cursor.rowcount``.

  "Real" here means an ``int`` that is neither ``None`` nor ``0``.  The
  three-way check matters because:

  * psycopg3's cursor has no ``lastrowid`` attribute at all, and
    justorm's ``__getattr__`` would otherwise turn the lookup into a
    ``TableBuilder`` (which is not an ``int``, so it is rejected by
    the ``isinstance`` check).
  * psycopg2 exposes ``lastrowid`` but always returns ``0`` (the OID),
    which is meaningless as a row identifier.
  * PyMySQL and SQLite expose a real per-INSERT row id.

The statement kind is decided by the first keyword of the SQL string
(after stripping leading whitespace and comments).  Anything that is
not recognisably ``UPDATE`` / ``DELETE`` falls into the second branch,
which is the more permissive one: it tries ``lastrowid`` first, then
``rowcount``.

``params``
----------

The ``params`` argument is passed through to ``execute`` unchanged.
Most drivers expect a list or tuple; python-oracledb accepts a dict
for named placeholders.  justorm does not normalise the type, so the
caller chooses the form their driver expects, exactly as they would
with a raw ``cursor.execute`` call.

``query`` never touches the builder state; it is a plain cursor
method.  It is provided as a mixin so every driver cursor picks it up
automatically.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from ._fetch import field_names

__all__ = ["QueryMixin"]


class QueryMixin:
    """Mixin providing the ``query`` escape hatch."""

    def query(
        self,
        sql: str,
        params: Optional[Any] = None,
    ) -> Any:
        if not isinstance(sql, str):
            raise TypeError("query() expects a string SQL statement")
        if params is None:
            self.execute(sql)
        else:
            self.execute(sql, params)

        if self.description:
            # The statement returned a result set.  Shape it like the
            # builder does: list of dicts keyed by column name.
            names = field_names(self.description)
            rows = self.fetchall()
            return [_row_to_dict(row, names) for row in rows]

        # No result set: figure out what kind of DML/DDL this was.
        first_word = _first_keyword(sql)
        if first_word in ("UPDATE", "DELETE"):
            return self.rowcount
        lastrowid = getattr(self, "lastrowid", None)
        if (
            lastrowid is not None
            and lastrowid != 0
            and isinstance(lastrowid, int)
        ):
            return lastrowid
        return self.rowcount


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_keyword(sql: str) -> str:
    """Return the first SQL keyword in *sql*, uppercased.

    Leading whitespace and ``--`` / ``/* ... */`` comments are skipped.
    The function is deliberately simple: it does not try to parse SQL,
    it only handles the cases a human would write by hand.
    """
    s = sql.lstrip()
    while s:
        if s.startswith("--"):
            nl = s.find("\n")
            if nl == -1:
                return ""
            s = s[nl + 1:].lstrip()
            continue
        if s.startswith("/*"):
            end = s.find("*/", 2)
            if end == -1:
                return ""
            s = s[end + 2:].lstrip()
            continue
        break
    if not s:
        return ""
    for i, ch in enumerate(s):
        if ch.isspace() or ch == "(":
            return s[:i].upper()
    return s.upper()


def _row_to_dict(row: Any, names: Sequence[str]) -> dict:
    return {name: value for name, value in zip(names, row)}
