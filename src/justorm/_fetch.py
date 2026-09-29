"""Row conversion helpers for ``fetchone`` / ``fetchmany`` / ``fetchall``.

Every justorm cursor overrides the three ``fetch*`` methods so that the
caller can ask for a specific output format:

* ``format=None`` (the default) — return exactly what the driver
  returned: a ``tuple`` for a normal cursor, whatever the driver's row
  factory produced otherwise.  This keeps the justorm cursor a
  drop-in replacement for the native one.
* ``format=tuple`` — return each row as a plain ``tuple``.  This is
  useful when the driver is configured to yield something richer (for
  example a ``namedtuple`` via psycopg's row factory) and the caller
  wants the plain form back.
* ``format=dict`` — return each row as a ``{column: value}`` mapping,
  keyed by the column names the driver reported in ``description``.
* ``format=namedtuple`` — return each row as an instance of a
  ``namedtuple`` whose fields are the column names.  Duplicate column
  names (common with joins) are renamed to ``_0``, ``_1``, ... by
  ``namedtuple(..., rename=True)``.

Only the three values ``dict``, ``tuple`` and ``namedtuple`` are
accepted.  Passing anything else raises :class:`justorm.JustormValueError`.
This is deliberate: the parameter selects a *shape*, not a converter
function, so keeping the accepted values small makes misuse obvious.

The helpers in this module are shared by every driver-specific cursor.
They never touch a connection or a driver: they only need the
``description`` (a sequence of sequences whose first element is the
column name) and the row itself.
"""

from __future__ import annotations

from collections import namedtuple
from typing import Any, Iterable, List, Optional, Sequence

from . import JustormValueError

__all__ = [
    "FORMATS",
    "convert_row",
    "convert_rows",
    "field_names",
]


#: The set of accepted ``format=`` values.
FORMATS = (tuple, dict, namedtuple)


# Cache of namedtuple classes keyed by the tuple of field names.  This
# lets us reuse the same class for the same query shape, which makes
# ``isinstance`` checks and ``repr`` output nicer.
_NT_CACHE: dict = {}


def field_names(description: Optional[Sequence[Any]]) -> List[str]:
    """Return the column names from a DB-API ``description``.

    ``description`` is ``None`` when nothing has been executed yet; in
    that case there are no rows, so the caller will not need the names.
    The DB-API spec defines each entry as a 7-tuple whose first element
    is the column name.
    """
    if not description:
        return []
    return [item[0] for item in description]


def convert_row(
    row: Any,
    description: Optional[Sequence[Any]],
    format: Any,
) -> Any:
    """Return *row* converted to *format*.

    ``format`` may be ``None`` (return the row unchanged), ``tuple``,
    ``dict``, or ``namedtuple``.  Anything else raises
    :class:`JustormValueError`.
    """
    if row is None:
        return None
    if format is None:
        return row
    if format is tuple:
        return tuple(row)
    names = field_names(description)
    if format is dict:
        return _row_to_dict(row, names)
    if format is namedtuple:
        return _row_to_namedtuple(row, names)
    raise JustormValueError(
        f"format must be None, tuple, dict, or namedtuple; got {format!r}"
    )


def convert_rows(
    rows: Iterable[Any],
    description: Optional[Sequence[Any]],
    format: Any,
) -> List[Any]:
    """Return *rows* converted to *format*."""
    if format is None:
        return list(rows)
    # Validate once, so an empty result set still surfaces a bad format.
    if format not in (tuple, dict, namedtuple):
        raise JustormValueError(
            f"format must be None, tuple, dict, or namedtuple; "
            f"got {format!r}"
        )
    names = field_names(description)
    out: List[Any] = []
    for row in rows:
        if row is None:
            out.append(None)
        elif format is tuple:
            out.append(tuple(row))
        elif format is dict:
            out.append(_row_to_dict(row, names))
        else:
            out.append(_row_to_namedtuple(row, names))
    return out


# ---------------------------------------------------------------------------
# Internal converters
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any, names: Sequence[str]) -> dict:
    return {name: value for name, value in zip(names, row)}


def _row_to_namedtuple(row: Any, names: Sequence[str]):
    nt = _namedtuple_class(names)
    return nt(*row)


def _namedtuple_class(names: Sequence[str]):
    key = tuple(names)
    cached = _NT_CACHE.get(key)
    if cached is None:
        cached = namedtuple("Row", names, rename=True)
        _NT_CACHE[key] = cached
    return cached
