"""Query builder core.

This module contains the dialect-agnostic part of justorm:

* the expression objects (:class:`Expr`, :class:`ColumnExpr`,
  :class:`Condition`) that users create via ``cur['...']`` /
  ``cur.t['col']`` and Python operators,
* the terminal and non-terminal builders returned by attribute access
  on a cursor (``cur.t1.where(...).select()`` and friends),
* the subquery object produced by ``.select_subquery()``,
* the ``cur.sql`` namespace used by ``.on_conflict(...)``.

Builders never touch a database connection directly.  They collect
information, then call back into the cursor (which mixes in a renderer)
through a small set of well-defined methods.
"""

from __future__ import annotations

import os
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from . import (
    JustormDialectError,
    JustormError,
    JustormTypeError,
    JustormValueError,
)

__all__ = [
    "Expr",
    "ColumnExpr",
    "Condition",
    "JustBuilder",
]


# ---------------------------------------------------------------------------
# Rendering sentinels
#
# The builder produces SQL text that may contain four kinds of markers:
#
#   _PH    a placeholder for a bound parameter
#   _ID    a bare identifier that needs quoting
#   _EX    a pre-rendered expression object
#   _LIKE  / _ILIKE   dialect-dependent operators
#
# ``_render_fragment`` replaces everything *except* ``_PH``, which is
# left in place.  ``_substitute_ph`` turns ``_PH`` into the dialect's
# final placeholder marker (and, for Oracle, assigns random names).
# Splitting the two steps lets nested subqueries keep their ``_PH``
# markers until the outermost statement is complete.
# ---------------------------------------------------------------------------

_PH = "\x00justorm:ph\x00"
_ID = "\x00justorm:id:"
_ID_END = "\x00"
_EX = "\x00justorm:ex:"
_EX_END = "\x00"

_LIKE = "\x00justorm:like\x00"
_ILIKE = "\x00justorm:ilike\x00"


def _render_fragment(
    sql: str, cursor: Any, exprs: Mapping[str, Any]
) -> str:
    """Resolve identifiers, expressions, and LIKE markers in *sql*.

    ``_PH`` markers are left untouched so the caller can substitute
    them later, once the full statement is assembled.
    """
    for marker, expr in exprs.items():
        sql = sql.replace(marker, expr._render(cursor))
    while _ID in sql:
        start = sql.index(_ID) + len(_ID)
        end = sql.index(_ID_END, start)
        name = sql[start:end]
        sql = (
            sql[: start - len(_ID)]
            + cursor._render_identifier(name)
            + sql[end + len(_ID_END):]
        )
    if _ILIKE in sql:
        sql = sql.replace(_ILIKE, " ILIKE ")
    if _LIKE in sql:
        sql = sql.replace(_LIKE, " LIKE ")
    return sql


def _new_placeholder_name() -> str:
    """Return a fresh ``:p<hex>`` placeholder name (Oracle)."""
    return "p" + os.urandom(4).hex()


def _substitute_ph(
    sql: str, cursor: Any, params: Sequence[Any]
) -> Tuple[str, Union[List[Any], Dict[str, Any]]]:
    """Replace every ``_PH`` in *sql* with the dialect's placeholder.

    * *params* is the ordered list of values, one per ``_PH``.
    * If the dialect uses anonymous placeholders (the common case),
      the markers become ``%s`` / ``?`` and the params list is
      returned unchanged.
    * If the dialect uses named placeholders (Oracle), each marker
      becomes a fresh ``:p<hex>`` and the params are returned as a
      dict keyed by those names.
    """
    if cursor.uses_named_placeholders:
        result: List[str] = []
        bound: Dict[str, Any] = {}
        i = 0
        n = 0
        while True:
            idx = sql.find(_PH, i)
            if idx == -1:
                result.append(sql[i:])
                break
            result.append(sql[i:idx])
            name = _new_placeholder_name()
            result.append(":" + name)
            bound[name] = params[n]
            n += 1
            i = idx + len(_PH)
        return "".join(result), bound
    return sql.replace(_PH, cursor._render_placeholder()), list(params)


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------


class Expr:
    """An opaque SQL fragment created with ``cur['...']``."""

    __slots__ = ("_sql",)

    _FORBIDDEN = (";", "--", "/*", "*/")

    def __init__(self, sql: str) -> None:
        if not isinstance(sql, str):
            raise JustormTypeError(
                f"cur[...] expects a string, got {type(sql).__name__}"
            )
        for token in self._FORBIDDEN:
            if token in sql:
                raise JustormValueError(
                    f"cur[...] rejects {token!r}; "
                    f"use .where_raw() for raw SQL"
                )
        self._sql = sql

    @property
    def sql(self) -> str:
        return self._sql

    def _render(self, cursor: Any) -> str:
        return cursor._escape_percent(self._sql)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Expr({self._sql!r})"

    __hash__ = object.__hash__

    def _arith(self, op: str, other: Any) -> "Expr":
        rhs, params = _bind_value(other)
        return _BoundExpr(
            f"({self._sql} {op} {rhs})",
            _expr_params(self) + params,
        )

    def __add__(self, other):
        return self._arith("+", other)

    def __radd__(self, other):
        rhs, params = _bind_value(other)
        return _BoundExpr(
            f"({rhs} + {self._sql})",
            params + _expr_params(self),
        )

    def __sub__(self, other):
        return self._arith("-", other)

    def __rsub__(self, other):
        rhs, params = _bind_value(other)
        return _BoundExpr(
            f"({rhs} - {self._sql})",
            params + _expr_params(self),
        )

    def __mul__(self, other):
        return self._arith("*", other)

    def __rmul__(self, other):
        rhs, params = _bind_value(other)
        return _BoundExpr(
            f"({rhs} * {self._sql})",
            params + _expr_params(self),
        )

    def __truediv__(self, other):
        return self._arith("/", other)

    def __rtruediv__(self, other):
        rhs, params = _bind_value(other)
        return _BoundExpr(
            f"({rhs} / {self._sql})",
            params + _expr_params(self),
        )

    def __mod__(self, other):
        return self._arith("%", other)

    def __rmod__(self, other):
        rhs, params = _bind_value(other)
        return _BoundExpr(
            f"({rhs} % {self._sql})",
            params + _expr_params(self),
        )

    def __eq__(self, other):  # type: ignore[override]
        return Condition(self, "=", other)

    def __ne__(self, other):  # type: ignore[override]
        return Condition(self, "<>", other)

    def __lt__(self, other):
        return Condition(self, "<", other)

    def __le__(self, other):
        return Condition(self, "<=", other)

    def __gt__(self, other):
        return Condition(self, ">", other)

    def __ge__(self, other):
        return Condition(self, ">=", other)


class _BoundExpr(Expr):
    __slots__ = ("_params",)

    def __init__(self, sql: str, params: Sequence[Any]) -> None:
        self._sql = sql
        self._params = list(params)

    @property
    def params(self) -> List[Any]:
        return list(self._params)

    def _render(self, cursor: Any) -> str:
        return cursor._escape_percent(self._sql)


class ColumnExpr(Expr):
    """A column reference created with ``cur.t['col']``."""

    __slots__ = ("_table", "_col")

    def __init__(self, table: str, col: str) -> None:
        if not isinstance(table, str) or not table:
            raise JustormTypeError("table name must be a non-empty string")
        if not isinstance(col, str) or not col:
            raise JustormTypeError("column name must be a non-empty string")
        if col == "*":
            raise JustormValueError(
                "cur.t['*'] is not supported; use cur['t.*'] instead"
            )
        self._table = table
        self._col = col
        self._sql = ""

    @property
    def table(self) -> str:
        return self._table

    @property
    def col(self) -> str:
        return self._col

    def _render(self, cursor: Any) -> str:
        return cursor._render_identifier_multi(self._table, self._col)

    def as_(self, alias: str) -> "Expr":
        if not isinstance(alias, str) or not alias:
            raise JustormTypeError("alias must be a non-empty string")
        return _AliasedExpr(self, alias)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ColumnExpr({self._table!r}, {self._col!r})"


class _AliasedExpr(Expr):
    __slots__ = ("_inner", "_alias")

    def __init__(self, inner: Expr, alias: str) -> None:
        self._inner = inner
        self._alias = alias
        self._sql = ""

    @property
    def alias(self) -> str:
        return self._alias

    def _render(self, cursor: Any) -> str:
        return (
            f"{self._inner._render(cursor)} "
            f"AS {cursor._render_identifier(self._alias)}"
        )


def _bind_value(value: Any) -> Tuple[str, List[Any]]:
    return _PH, [value]


def _expr_params(expr: Any) -> List[Any]:
    if isinstance(expr, _BoundExpr):
        return list(expr.params)
    return []


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


class Condition:
    __slots__ = ("_sql", "_params", "_exprs", "_ilike")

    def __init__(self, left: Any, op: str, right: Any) -> None:
        self._exprs: Dict[str, Expr] = {}
        self._ilike = False
        left_sql, left_params = self._render_operand(left)
        right_sql, right_params = self._render_operand(right)

        if right is None and op in ("=", "=="):
            sql = f"{left_sql} IS NULL"
            params = list(left_params)
        elif right is None and op in ("<>", "!="):
            sql = f"{left_sql} IS NOT NULL"
            params = list(left_params)
        else:
            sql = f"{left_sql} {op} {right_sql}"
            params = list(left_params) + list(right_params)

        self._sql = sql
        self._params = params

    def _render_operand(self, value: Any) -> Tuple[str, List[Any]]:
        if isinstance(value, _AliasedExpr):
            raise JustormTypeError(
                "aliased expressions cannot appear inside a condition"
            )
        if isinstance(value, (ColumnExpr, _BoundExpr, Expr)):
            marker = f"{_EX}{id(value)}{_EX_END}"
            self._exprs[marker] = value
            params = (
                list(value.params)
                if isinstance(value, _BoundExpr)
                else []
            )
            return marker, params
        if isinstance(value, Condition):
            return f"({value._sql})", list(value._params)
        return _PH, [value]

    def __and__(self, other: "Condition") -> "Condition":
        return _combine(self, other, "AND")

    def __or__(self, other: "Condition") -> "Condition":
        return _combine(self, other, "OR")

    def __invert__(self) -> "Condition":
        out = _WrappedCondition(f"NOT ({self._sql})", list(self._params))
        out._exprs = dict(self._exprs)
        out._ilike = self._ilike
        return out

    def _render_fragment(self, cursor: Any) -> str:
        """Resolve markers, leave ``_PH`` in place."""
        return _render_fragment(self._sql, cursor, self._exprs)

    @property
    def params(self) -> List[Any]:
        return list(self._params)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Condition({self._sql!r}, {self._params!r})"


class _WrappedCondition(Condition):
    __slots__ = ()

    def __init__(self, sql: str, params: Sequence[Any]) -> None:
        self._sql = sql
        self._params = list(params)
        self._exprs = {}
        self._ilike = False


def _combine(a: Condition, b: Condition, op: str) -> Condition:
    if not isinstance(b, Condition):
        raise JustormTypeError(
            f"cannot combine Condition with {type(b).__name__}"
        )
    out = _WrappedCondition(
        f"({a._sql}) {op} ({b._sql})",
        list(a._params) + list(b._params),
    )
    out._exprs = {**a._exprs, **b._exprs}
    out._ilike = a._ilike or b._ilike
    return out


# ---------------------------------------------------------------------------
# Condition factories
# ---------------------------------------------------------------------------


def _ident_marker(key: Any, holder: "Condition") -> str:
    if isinstance(key, (ColumnExpr, Expr)):
        marker = f"{_EX}{id(key)}{_EX_END}"
        holder._exprs[marker] = key
        return marker
    if isinstance(key, str):
        return f"{_ID}{key}{_ID_END}"
    raise JustormTypeError(
        f"expected a column name (str) or Expr, got "
        f"{type(key).__name__}"
    )


def _eq_condition(key: Any, value: Any) -> Condition:
    holder = _WrappedCondition("", [])
    ident = _ident_marker(key, holder)
    if value is None:
        out = _WrappedCondition(f"{ident} IS NULL", [])
    else:
        out = _WrappedCondition(f"{ident} = {_PH}", [value])
    out._exprs = holder._exprs
    return out


def _in_condition(
    key: Any, values: Iterable[Any], *, negate: bool
) -> Condition:
    values = list(values)
    if not values:
        return _WrappedCondition("FALSE" if not negate else "TRUE", [])
    holder = _WrappedCondition("", [])
    ident = _ident_marker(key, holder)
    placeholders = ", ".join([_PH] * len(values))
    op = "NOT IN" if negate else "IN"
    out = _WrappedCondition(f"{ident} {op} ({placeholders})", values)
    out._exprs = holder._exprs
    return out


def _between_condition(key: Any, bounds: Sequence[Any]) -> Condition:
    holder = _WrappedCondition("", [])
    ident = _ident_marker(key, holder)
    out = _WrappedCondition(
        f"{ident} BETWEEN {_PH} AND {_PH}", list(bounds)
    )
    out._exprs = holder._exprs
    return out


def _is_null_condition(key: Any) -> Condition:
    holder = _WrappedCondition("", [])
    ident = _ident_marker(key, holder)
    out = _WrappedCondition(f"{ident} IS NULL", [])
    out._exprs = holder._exprs
    return out


def _like_condition(
    key: Any, pattern: str, *, ilike: bool
) -> Condition:
    holder = _WrappedCondition("", [])
    ident = _ident_marker(key, holder)
    op = _ILIKE if ilike else _LIKE
    out = _WrappedCondition(f"{ident}{op}{_PH}", [pattern])
    out._exprs = holder._exprs
    out._ilike = ilike
    return out


# ---------------------------------------------------------------------------
# WHERE collection
# ---------------------------------------------------------------------------


class _WhereClause:
    __slots__ = ("_conditions", "_allow_all")

    def __init__(self) -> None:
        self._conditions: List[Condition] = []
        self._allow_all = False

    def add(self, cond: Condition) -> None:
        self._conditions.append(cond)

    def mark_all(self) -> None:
        self._allow_all = True

    def __bool__(self) -> bool:
        return bool(self._conditions) or self._allow_all

    @property
    def has_conditions(self) -> bool:
        return bool(self._conditions)

    def render(self, cursor: Any) -> Tuple[str, List[Any]]:
        """Return the WHERE fragment with ``_PH`` markers still in place."""
        if not self._conditions:
            return "", []
        rendered: List[str] = []
        params: List[Any] = []
        for cond in self._conditions:
            if cond._ilike:
                left, _, right = cond._sql.partition(_ILIKE)
                left_rendered = _render_fragment(left, cursor, cond._exprs)
                right_rendered = _render_fragment(right, cursor, {})
                text = cursor._render_ilike(
                    left_rendered.strip(), right_rendered.strip()
                )
            else:
                text = cond._render_fragment(cursor)
            rendered.append(f"({text})")
            params.extend(cond.params)
        return " AND ".join(rendered), params

    def copy(self) -> "_WhereClause":
        out = _WhereClause()
        out._conditions = list(self._conditions)
        out._allow_all = self._allow_all
        return out


# ---------------------------------------------------------------------------
# Column list rendering
# ---------------------------------------------------------------------------


def _render_column_item(item: Any, cursor: Any) -> str:
    if isinstance(item, str) and item == "*":
        return "*"
    if isinstance(item, _AliasedExpr):
        return item._render(cursor)
    if isinstance(item, ColumnExpr):
        return item._render(cursor)
    if isinstance(item, Expr):
        return item._render(cursor)
    if isinstance(item, str):
        return cursor._render_identifier(item)
    raise JustormTypeError(
        f"column list expects str or Expr, got {type(item).__name__}"
    )


def _guess_output_name(item: Any) -> Optional[str]:
    if isinstance(item, str) and item == "*":
        return None
    if isinstance(item, _AliasedExpr):
        return item.alias
    if isinstance(item, ColumnExpr):
        return item.col
    if isinstance(item, str):
        return item
    return None


def _is_star_projection(projection: Sequence[Any]) -> bool:
    for item in projection:
        if isinstance(item, str) and item == "*":
            return True
    return False


def _select_shape(args: Tuple[Any, ...]) -> Tuple[str, List[Any]]:
    if not args:
        return "dict", ["*"]
    if len(args) > 1:
        raise JustormTypeError(
            "select() accepts at most one positional argument"
        )
    arg = args[0]
    if isinstance(arg, (set, list)):
        items = list(arg)
        return "dict", items or ["*"]
    if isinstance(arg, tuple):
        items = list(arg)
        return "tuple", items or ["*"]
    if isinstance(arg, str):
        if arg == "*":
            raise JustormValueError(
                "select('*') is not supported; call select() with no "
                "argument"
            )
        return "scalar", [arg]
    if isinstance(arg, Expr):
        return "scalar", [arg]
    raise JustormTypeError(
        f"select() expects a set, list, tuple, str, or Expr; "
        f"got {type(arg).__name__}"
    )


def _select_projection_key(
    projection_arg: List[Any], key: Any
) -> List[Any]:
    if key is None:
        return []
    if projection_arg == ["*"]:
        if isinstance(key, str):
            return []
        return [key]
    for item in projection_arg:
        if isinstance(key, str) and isinstance(item, str):
            if item == key:
                return []
        elif item is key:
            return []
    return [key]


def _render_projection(
    projection: List[Any], cursor: Any
) -> Tuple[List[str], List[Optional[str]]]:
    sql: List[str] = []
    names: List[Optional[str]] = []
    for item in projection:
        sql.append(_render_column_item(item, cursor))
        names.append(_guess_output_name(item))
    return sql, names


# ---------------------------------------------------------------------------
# Join description
# ---------------------------------------------------------------------------


class _Join:
    __slots__ = ("right", "on", "using", "how")

    def __init__(self, right, on, using, how):
        self.right = right
        self.on = on
        self.using = using
        self.how = how


_JOIN_KEYWORD = {
    "inner": "JOIN",
    "left": "LEFT JOIN",
    "right": "RIGHT JOIN",
    "full": "FULL JOIN",
    "cross": "CROSS JOIN",
}


# ---------------------------------------------------------------------------
# FROM-source rendering
# ---------------------------------------------------------------------------


def _render_table_alias(cursor: Any, alias: str) -> str:
    """Render ``[AS] alias`` after a table or subquery.

    Oracle does not accept ``AS`` before a table alias; every other
    dialect justorm supports does.  The renderer controls this via
    ``table_alias_uses_as``.
    """
    quoted = cursor._render_identifier(alias)
    if getattr(cursor, "table_alias_uses_as", True):
        return f" AS {quoted}"
    return f" {quoted}"


def _render_from_item(source: Any, cursor: Any) -> Tuple[str, List[Any]]:
    if isinstance(source, _SubqueryAlias):
        inner_sql, params = source.subquery._render_sql(cursor)
        return (
            f"({inner_sql}){_render_table_alias(cursor, source.alias)}",
            params,
        )
    if isinstance(source, _TableSource):
        if source.schema is None:
            base = cursor._render_identifier(source.table)
        else:
            base = cursor._render_identifier_multi(source.schema, source.table)
        if source.alias:
            base += _render_table_alias(cursor, source.alias)
        return base, []
    if isinstance(source, TableBuilder):
        return _render_from_item(source._state.from_source, cursor)
    raise JustormTypeError(
        f"FROM expects a table or subquery, got {type(source).__name__}"
    )


# ---------------------------------------------------------------------------
# Table source
# ---------------------------------------------------------------------------


class _TableSource:
    __slots__ = ("schema", "table", "alias")

    def __init__(self, schema, table, alias=None):
        self.schema = schema
        self.table = table
        self.alias = alias

    def effective_name(self) -> str:
        return self.alias or self.table

# ---------------------------------------------------------------------------
# Query state
# ---------------------------------------------------------------------------


class _QueryState:
    __slots__ = (
        "from_source",
        "joins",
        "where",
        "order",
        "limit",
        "offset",
        "distinct",
        "distinct_on",
        "for_update",
        "for_share",
        "skip_locked",
        "nowait",
    )

    def __init__(self, from_source: Any) -> None:
        self.from_source = from_source
        self.joins: List[_Join] = []
        self.where = _WhereClause()
        self.order: List[str] = []
        self.limit: Optional[int] = None
        self.offset: Optional[int] = None
        self.distinct = False
        self.distinct_on: Optional[List[str]] = None
        self.for_update = False
        self.for_share = False
        self.skip_locked = False
        self.nowait = False

    def copy(self) -> "_QueryState":
        new = _QueryState(self.from_source)
        new.joins = list(self.joins)
        new.where = self.where.copy()
        new.order = list(self.order)
        new.limit = self.limit
        new.offset = self.offset
        new.distinct = self.distinct
        new.distinct_on = list(self.distinct_on) if self.distinct_on else None
        new.for_update = self.for_update
        new.for_share = self.for_share
        new.skip_locked = self.skip_locked
        new.nowait = self.nowait
        return new


# ---------------------------------------------------------------------------
# JustBuilder: the cursor mixin
# ---------------------------------------------------------------------------


class JustBuilder:
    def __getattr__(self, name: str) -> "TableBuilder":
        if name.startswith("_"):
            raise AttributeError(name)
        if hasattr(type(self), name):
            raise AttributeError(name)
        return TableBuilder(self, name)

    def __getitem__(self, key: str) -> Expr:
        return Expr(key)

    def table(self, *names: str) -> "TableBuilder":
        if not names:
            raise JustormTypeError("cur.table() requires at least one name")
        if len(names) == 1 and "." in names[0]:
            parts = names[0].split(".")
            if len(parts) != 2:
                raise JustormValueError(
                    "cur.table('a.b.c') is not supported; "
                    "pass at most two parts"
                )
            return TableBuilder(self, parts[0], parts[1])
        if len(names) > 2:
            raise JustormValueError("cur.table() accepts at most two parts")
        return TableBuilder(self, *names)

    @property
    def sql(self) -> "_SqlNamespace":
        return _SqlNamespace(self)


# ---------------------------------------------------------------------------
# TableBuilder
# ---------------------------------------------------------------------------


class TableBuilder:
    __slots__ = ("_cursor", "_state", "_insert_state")

    def __init__(self, cursor: Any, *names: str) -> None:
        self._cursor = cursor
        if len(names) == 1:
            source = _TableSource(None, names[0])
        else:
            source = _TableSource(names[0], names[1])
        self._state = _QueryState(source)
        self._insert_state: Optional[_InsertState] = None

    def __getitem__(self, col: str) -> ColumnExpr:
        if col == "*":
            raise JustormValueError(
                "cur.t['*'] is not supported; use cur['t.*'] instead"
            )
        return ColumnExpr(self._state.from_source.effective_name(), col)

    def _clone(self) -> "TableBuilder":
        new = object.__new__(TableBuilder)
        new._cursor = self._cursor
        new._state = self._state.copy()
        new._insert_state = (
            self._insert_state.copy()
            if self._insert_state is not None
            else None
        )
        return new

    def as_(self, alias: str) -> "TableBuilder":
        if not isinstance(alias, str) or not alias:
            raise JustormTypeError("alias must be a non-empty string")
        new = self._clone()
        src = new._state.from_source
        if isinstance(src, _TableSource):
            new._state.from_source = _TableSource(src.schema, src.table, alias)
        return new

    def join(self, right, *, on=None, using=None, how="inner"):
        return self._add_join(right, on=on, using=using, how=how)

    def inner_join(self, right, *, on=None, using=None):
        return self._add_join(right, on=on, using=using, how="inner")

    def left_join(self, right, *, on=None, using=None):
        return self._add_join(right, on=on, using=using, how="left")

    def right_join(self, right, *, on=None, using=None):
        return self._add_join(right, on=on, using=using, how="right")

    def full_join(self, right, *, on=None, using=None):
        return self._add_join(right, on=on, using=using, how="full")

    def cross_join(self, right, *, on=None, using=None):
        if on is not None or using is not None:
            raise JustormValueError("cross join does not accept on/using")
        return self._add_join(right, on=None, using=None, how="cross")

    def _add_join(self, right, *, on, using, how):
        if how not in _JOIN_KEYWORD:
            raise JustormValueError(f"unknown join type: {how!r}")
        if how == "cross":
            if on is not None or using is not None:
                raise JustormValueError("cross join does not accept on/using")
        else:
            if (on is None) == (using is None):
                raise JustormValueError(
                    f"{how} join requires exactly one of on / using"
                )
        _render_from_item(right, self._cursor)
        new = self._clone()
        new._state.joins = new._state.joins + [
            _Join(
                right=right,
                on=on,
                using=list(using) if using else None,
                how=how,
            )
        ]
        return new

    def where(self, *conditions: Condition, **kwargs: Any) -> "TableBuilder":
        new = self._clone()
        if conditions:
            if kwargs:
                raise JustormTypeError(
                    ".where() accepts either positional Conditions or "
                    "keyword arguments, not both"
                )
            for cond in conditions:
                if not isinstance(cond, Condition):
                    raise JustormTypeError(
                        f".where() expects Condition objects, got "
                        f"{type(cond).__name__}"
                    )
                new._state.where.add(cond)
            return new
        for key, value in kwargs.items():
            new._state.where.add(_eq_condition(key, value))
        return new

    def where_in(self, mapping=None, **kwargs):
        return self._where_in_like("where_in", mapping, kwargs, negate=False)

    def where_not_in(self, mapping=None, **kwargs):
        return self._where_in_like("where_not_in", mapping, kwargs, negate=True)

    def _where_in_like(self, name, mapping, kwargs, *, negate):
        if mapping is not None and kwargs:
            raise JustormTypeError(
                f".{name}() accepts either a mapping or keyword "
                f"arguments, not both"
            )
        if mapping is not None:
            items = list(mapping.items())
        else:
            items = list(kwargs.items())
        new = self._clone()
        for key, values in items:
            new._state.where.add(_in_condition(key, values, negate=negate))
        return new

    def where_between(self, mapping=None, **kwargs):
        if mapping is not None and kwargs:
            raise JustormTypeError(
                ".where_between() accepts either a mapping or keyword "
                "arguments, not both"
            )
        if mapping is not None:
            items = list(mapping.items())
        else:
            items = list(kwargs.items())
        new = self._clone()
        for key, bounds in items:
            if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
                raise JustormValueError(
                    "where_between expects a (low, high) pair"
                )
            new._state.where.add(_between_condition(key, bounds))
        return new

    def where_is_null(self, *keys: str) -> "TableBuilder":
        new = self._clone()
        for key in keys:
            new._state.where.add(_is_null_condition(key))
        return new

    def where_like(self, mapping=None, **kwargs):
        return self._where_like_impl(
            "where_like", mapping, kwargs, ilike=False
        )

    def where_ilike(self, mapping=None, **kwargs):
        return self._where_like_impl(
            "where_ilike", mapping, kwargs, ilike=True
        )

    def _where_like_impl(self, name, mapping, kwargs, *, ilike):
        if mapping is not None and kwargs:
            raise JustormTypeError(
                f".{name}() accepts either a mapping or keyword "
                f"arguments, not both"
            )
        if mapping is not None:
            items = list(mapping.items())
        else:
            items = list(kwargs.items())
        new = self._clone()
        for key, pattern in items:
            new._state.where.add(_like_condition(key, pattern, ilike=ilike))
        return new

    def where_raw(self, sql: str, params=None) -> "TableBuilder":
        if not isinstance(sql, str):
            raise JustormTypeError("where_raw expects a string SQL fragment")
        new = self._clone()
        new._state.where.add(_WrappedCondition(sql, list(params or [])))
        return new

    def orderby(self, *exprs: Any) -> "TableBuilder":
        return self._add_order(exprs, desc=False)

    def orderby_desc(self, *exprs: Any) -> "TableBuilder":
        return self._add_order(exprs, desc=True)

    def _add_order(self, exprs, *, desc):
        new = self._clone()
        for expr in exprs:
            new._state.order.append(
                _render_order_item(expr, self._cursor, desc=desc)
            )
        return new

    def limit(self, n: int) -> "TableBuilder":
        new = self._clone()
        new._state.limit = int(n)
        return new

    def offset(self, n: int) -> "TableBuilder":
        new = self._clone()
        new._state.offset = int(n)
        return new

    def distinct(self) -> "TableBuilder":
        new = self._clone()
        new._state.distinct = True
        return new

    def distinct_on(self, *columns: str) -> "TableBuilder":
        if not columns:
            raise JustormValueError("distinct_on requires at least one column")
        for c in columns:
            if not isinstance(c, str) or not c:
                raise JustormTypeError(
                    "distinct_on columns must be non-empty strings"
                )
        new = self._clone()
        new._state.distinct_on = list(columns)
        return new

    def all(self) -> "TableBuilder":
        new = self._clone()
        new._state.where.mark_all()
        return new

    # -- SELECT ---------------------------------------------------------

    def select(self, *args: Any, **kwargs: Any) -> Any:
        shape, projection_arg = _select_shape(args)
        key = kwargs.pop("key", None)
        key_conflict = kwargs.pop("key_conflict", "error")
        for_update = kwargs.pop("for_update", False)
        share = kwargs.pop("share", False)
        skip_locked = kwargs.pop("skip_locked", False)
        nowait = kwargs.pop("nowait", False)
        if kwargs:
            raise JustormTypeError(
                f"select() got unexpected keyword arguments: "
                f"{', '.join(sorted(kwargs))}"
            )

        projection_key = _select_projection_key(projection_arg, key)
        projection = projection_arg + projection_key
        has_key_col = bool(projection_key)

        new = self._clone()
        if for_update is True:
            new._state.for_update = True
        elif for_update == "share":
            new._state.for_share = True
        elif for_update is False or for_update is None:
            pass
        else:
            raise JustormValueError(
                f"for_update must be True, 'share', or False; "
                f"got {for_update!r}"
            )
        if share:
            new._state.for_share = True
        new._state.skip_locked = bool(skip_locked)
        new._state.nowait = bool(nowait)

        sql, params, projection_names = new._render_select(projection)
        rows = new._cursor._just_execute_and_fetch(sql, params)
        return _shape_rows(
            rows,
            shape,
            key,
            key_conflict,
            projection,
            projection_names,
            new._cursor,
            has_key_col,
        )

    def get(self, *args: Any, default: Any = None, **kwargs: Any) -> Any:
        """Return the first row of the query, or *default* if there is none.

        Equivalent to ``.limit(1).select(*args)`` followed by ``[0]``,
        with the difference that an empty result returns *default*
        instead of raising ``IndexError``.

        ``key=`` is **not** supported: a single row is not something to
        index by column value.  Passing it raises
        :class:`JustormTypeError`.

        Any other keyword argument is forwarded to :meth:`select`, so
        ``for_update=True`` and friends still work.

        The method overrides any previously set ``limit``: "give me one
        row" is the whole point.
        """
        if "key" in kwargs:
            raise JustormTypeError(
                ".get() does not accept key=; use .select(key=...) "
                "for a keyed result"
            )
        new = self._clone()
        new._state.limit = 1
        rows = new.select(*args, **kwargs)
        if not rows:
            return default
        return rows[0]

    def select_subquery(self, *args: Any) -> "Subquery":
        _, projection_arg = _select_shape(args)
        new = self._clone()
        return Subquery(new, projection_arg)

    # -- INSERT ---------------------------------------------------------

    def append(self, row=None, *, columns=None, **kwargs) -> Any:
        new = self._clone()
        state = new._insert_state or _InsertState()
        row_dict = _normalise_append_row(row, columns, kwargs)
        if row_dict is None:
            return None
        if columns is None:
            columns_list = list(row_dict.keys())
        else:
            columns_list = list(columns)
        cells, params = _values_for_row(row_dict, columns_list, self._cursor)
        values = [("(" + ", ".join(cells) + ")", params)]
        sql, all_params = new._render_insert(values, columns_list)
        if state.returning is not None:
            fetched = new._cursor._just_execute_and_fetch(sql, all_params)
            row_result = fetched[0] if fetched else None
            return _shape_returning_one(row_result, state.returning)
        new._cursor._just_execute(sql, all_params)
        return None

    def insert(self, rows, *, columns=None) -> Any:
        new = self._clone()
        state = new._insert_state or _InsertState()
        prepared = _normalise_insert_rows(rows, columns)
        if not prepared:
            return None
        if columns is None:
            seen: List[str] = []
            for row in prepared:
                for k in row.keys():
                    if k not in seen:
                        seen.append(k)
            columns_list = seen
        else:
            columns_list = list(columns)
        values: List[Tuple[str, List[Any]]] = []
        for row in prepared:
            cells, params = _values_for_row(row, columns_list, self._cursor)
            values.append(("(" + ", ".join(cells) + ")", params))
        sql, all_params = new._render_insert(values, columns_list)
        if state.returning is not None:
            fetched = new._cursor._just_execute_and_fetch(sql, all_params)
            return _shape_returning_many(fetched, state.returning)
        new._cursor._just_execute(sql, all_params)
        return None

    def insert_many(self, rows, columns=None) -> Any:
        if columns is None:
            raise JustormTypeError("insert_many requires columns")
        if not all(isinstance(c, str) and c for c in columns):
            raise JustormTypeError(
                "insert_many columns must be non-empty strings"
            )
        new = self._clone()
        state = new._insert_state or _InsertState()
        cur = new._cursor

        param_sets: List[Any] = []
        for row in rows:
            param_sets.append(_row_to_param_list(row, columns))
        if not param_sets:
            return None

        sql = new._render_insert_template(columns)

        # Oracle uses named placeholders, so each row's parameters must
        # be a dict keyed by those names.
        if cur.uses_named_placeholders:
            names = _template_placeholder_names(sql)
            if len(names) != len(columns):
                raise JustormError(
                    "internal: placeholder count does not match columns"
                )
            param_sets = [dict(zip(names, ps)) for ps in param_sets]

        if state.returning is not None:
            collected: List[Any] = []
            for params in param_sets:
                fetched = cur._just_execute_and_fetch(sql, params)
                collected.extend(fetched)
            return _shape_returning_many(collected, state.returning)
        cur._just_execute_many(sql, param_sets)
        return None

    # -- UPDATE / DELETE -----------------------------------------------

    def update(self, row=None, **kwargs) -> Any:
        new = self._clone()
        if not new._state.where:
            raise JustormError(
                ".update() without .where(...) would affect the whole "
                "table; call .all() first if that is intended"
            )
        if (
            new._state.order
            or new._state.limit is not None
            or new._state.offset is not None
        ):
            raise JustormError(
                "update() does not support orderby / limit / offset"
            )
        assignments = _normalise_update(row, kwargs)
        if not assignments:
            raise JustormValueError("update() requires at least one assignment")
        sql, params = new._render_update(assignments)
        state = new._insert_state or _InsertState()
        if state.returning is not None:
            fetched = new._cursor._just_execute_and_fetch(sql, params)
            return _shape_returning_many(fetched, state.returning)
        new._cursor._just_execute(sql, params)
        return None

    def delete(self) -> Any:
        new = self._clone()
        if not new._state.where:
            raise JustormError(
                ".delete() without .where(...) would affect the whole "
                "table; call .all() first if that is intended"
            )
        if (
            new._state.order
            or new._state.limit is not None
            or new._state.offset is not None
        ):
            raise JustormError(
                "delete() does not support orderby / limit / offset"
            )
        sql, params = new._render_delete()
        state = new._insert_state or _InsertState()
        if state.returning is not None:
            fetched = new._cursor._just_execute_and_fetch(sql, params)
            return _shape_returning_many(fetched, state.returning)
        new._cursor._just_execute(sql, params)
        return None

    # -- RETURNING / UPSERT --------------------------------------------

    def returning(self, *columns: Any) -> "TableBuilder":
        if not columns:
            raise JustormValueError("returning requires at least one column")
        new = self._clone()
        state = new._insert_state or _InsertState()
        state = state.copy()
        state.returning = tuple(columns)
        new._insert_state = state
        return new

    def on_conflict(self, on=None, do=None) -> "TableBuilder":
        if do is None:
            raise JustormTypeError("on_conflict requires do=...")
        new = self._clone()
        state = new._insert_state or _InsertState()
        state = state.copy()
        state.on_conflict = _OnConflict(on=on, do=do)
        new._insert_state = state
        return new

    def on_duplicate(self, *, update) -> "TableBuilder":
        if not update:
            raise JustormValueError(
                "on_duplicate requires a non-empty update mapping"
            )
        new = self._clone()
        state = new._insert_state or _InsertState()
        state = state.copy()
        state.on_duplicate = dict(update)
        new._insert_state = state
        return new

    # -- rendering ------------------------------------------------------

    def _render_select(
        self, projection: List[Any], nested: bool = False
    ) -> Tuple[str, Any, List[Optional[str]]]:
        cur = self._cursor
        state = self._state
        select_head: List[str] = ["SELECT"]

        # SQL Server rejects ``OFFSET ... FETCH`` without an ``ORDER
        # BY``, so a limit with no offset is rendered as
        # ``SELECT TOP n`` instead.  The renderer declares this via
        # ``limit_without_offset_uses_top``.
        use_top = (
            getattr(cur, "limit_without_offset_uses_top", False)
            and state.limit is not None
            and state.offset is None
        )

        if state.distinct_on:
            select_head.append(cur._render_distinct_on(list(state.distinct_on)))
        elif state.distinct:
            select_head.append("DISTINCT")
        if use_top:
            select_head.append(cur.render_limit_top(state.limit))

        sql_items, names = _render_projection(projection, cur)
        select_head.append(", ".join(sql_items))
        sql = " ".join(select_head)
        from_sql, join_params = self._render_from_and_joins()
        sql += " " + from_sql
        where_sql, where_params = state.where.render(cur)
        if where_sql:
            sql += " WHERE " + where_sql
        if state.order:
            sql += " ORDER BY " + ", ".join(state.order)

        # ``TOP n`` already carries the limit; skip the LIMIT / OFFSET
        # suffix in that case.
        if not use_top:
            limit_offset = cur._render_limit_offset(state.limit, state.offset)
            if limit_offset:
                sql += " " + limit_offset

        if state.for_update or state.for_share:
            sql += " " + cur._render_for_update(
                share=state.for_share,
                skip_locked=state.skip_locked,
                nowait=state.nowait,
            )
        params = join_params + where_params
        if nested:
            return sql, params, names
        sql, bound = _substitute_ph(sql, cur, params)
        return sql, bound, names

    def _render_from_and_joins(self) -> Tuple[str, List[Any]]:
        cur = self._cursor
        state = self._state
        from_sql, params = _render_from_item(state.from_source, cur)
        sql = "FROM " + from_sql
        for join in state.joins:
            join_sql, join_params = _render_from_item(join.right, cur)
            sql += " " + _JOIN_KEYWORD[join.how] + " " + join_sql
            params.extend(join_params)
            if join.using is not None:
                sql += " USING (" + ", ".join(
                    cur._render_identifier(c) for c in join.using
                ) + ")"
            elif join.on is not None:
                sql += " ON " + join.on._render_fragment(cur)
                params.extend(join.on.params)
        return sql, params

    def _render_insert(
        self, values: List[Tuple[str, List[Any]]], columns: List[str]
    ) -> Tuple[str, Any]:
        cur = self._cursor
        from_sql, from_params = _render_from_item(
            self._state.from_source, cur
        )
        sql = "INSERT INTO " + from_sql
        sql += " (" + ", ".join(
            cur._render_identifier(c) for c in columns
        ) + ")"
        rows_sql: List[str] = []
        params: List[Any] = list(from_params)
        for row_sql, row_params in values:
            rows_sql.append(row_sql)
            params.extend(row_params)
        sql += " VALUES " + ", ".join(rows_sql)
        sql, extra = self._append_upsert(sql)
        params.extend(extra)
        sql += self._append_returning()
        sql, bound = _substitute_ph(sql, cur, params)
        return sql, bound

    def _render_insert_template(self, columns: Sequence[str]) -> str:
        cur = self._cursor
        from_sql, _ = _render_from_item(self._state.from_source, cur)
        sql = "INSERT INTO " + from_sql
        sql += " (" + ", ".join(
            cur._render_identifier(c) for c in columns
        ) + ")"
        if cur.uses_named_placeholders:
            # Oracle needs stable names so each row can bind its own
            # values to the same template.  Random names would change
            # per call; use sequential ones instead.
            names = [f"p{i + 1}" for i in range(len(columns))]
            sql += " VALUES (" + ", ".join(":" + n for n in names) + ")"
        else:
            placeholders = ", ".join([_PH] * len(columns))
            sql += f" VALUES ({placeholders})"
        sql, _ = self._append_upsert(sql)
        if not cur.uses_named_placeholders:
            sql = sql.replace(_PH, cur._render_placeholder())
        return sql

    def _render_update(
        self, assignments: Sequence[Tuple[str, Any]]
    ) -> Tuple[str, Any]:
        cur = self._cursor
        from_sql, from_params = _render_from_item(
            self._state.from_source, cur
        )
        sql = "UPDATE " + from_sql
        sets: List[str] = []
        params: List[Any] = list(from_params)
        for name, value in assignments:
            ident = cur._render_identifier(name)
            frag, val_params = _render_value(value, cur)
            sets.append(f"{ident} = {frag}")
            params.extend(val_params)
        sql += " SET " + ", ".join(sets)
        where_sql, where_params = self._state.where.render(cur)
        if where_sql:
            sql += " WHERE " + where_sql
            params.extend(where_params)
        sql += self._append_returning()
        sql, bound = _substitute_ph(sql, cur, params)
        return sql, bound

    def _render_delete(self) -> Tuple[str, Any]:
        cur = self._cursor
        from_sql, from_params = _render_from_item(
            self._state.from_source, cur
        )
        sql = "DELETE FROM " + from_sql
        params: List[Any] = list(from_params)
        where_sql, where_params = self._state.where.render(cur)
        if where_sql:
            sql += " WHERE " + where_sql
            params.extend(where_params)
        sql += self._append_returning()
        sql, bound = _substitute_ph(sql, cur, params)
        return sql, bound

    def _append_upsert(self, sql: str) -> Tuple[str, List[Any]]:
        cur = self._cursor
        state = self._insert_state
        if state is None:
            return sql, []
        if state.on_conflict is not None:
            target = state.on_conflict.on
            columns: Optional[List[str]] = None
            constraint: Optional[str] = None
            index_where: Optional[str] = None
            index_params: List[Any] = []
            if isinstance(target, _SqlColumns):
                columns = target.names
                if target.where_conditions:
                    index_where, index_params = _render_conditions(
                        target.where_conditions, cur
                    )
            elif isinstance(target, _SqlConstraint):
                constraint = target.name
            elif target is not None:
                raise JustormTypeError(
                    f"on_conflict(on=...) expects cur.sql.columns(...) "
                    f"or cur.sql.constraint(...); got "
                    f"{type(target).__name__}"
                )
            target_sql = cur.render_on_conflict_target(
                columns, constraint, index_where
            )
            do_sql, do_params = _render_on_conflict_do(
                state.on_conflict.do, cur
            )
            return (
                sql + " " + cur._render_on_conflict(target_sql, do_sql),
                index_params + do_params,
            )
        if state.on_duplicate is not None:
            assignments: List[str] = []
            params: List[Any] = []
            for name, value in state.on_duplicate.items():
                ident = cur._render_identifier(name)
                frag, val_params = _render_value(value, cur)
                assignments.append(f"{ident} = {frag}")
                params.extend(val_params)
            return (
                sql + " " + cur._render_on_duplicate(", ".join(assignments)),
                params,
            )
        return sql, []

    def _append_returning(self) -> str:
        state = self._insert_state
        if state is None or state.returning is None:
            return ""
        cur = self._cursor
        items = [_render_column_item(c, cur) for c in state.returning]
        rendered = cur._render_returning(items)
        if not rendered:
            return ""
        return " " + rendered

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        src = self._state.from_source
        if isinstance(src, _TableSource):
            name = src.effective_name()
        else:
            name = "?"
        return f"<TableBuilder table={name!r}>"


# ---------------------------------------------------------------------------
# Insert / upsert state
# ---------------------------------------------------------------------------


class _InsertState:
    __slots__ = ("returning", "on_conflict", "on_duplicate")

    def __init__(self) -> None:
        self.returning: Optional[Tuple[Any, ...]] = None
        self.on_conflict: Optional["_OnConflict"] = None
        self.on_duplicate: Optional[Dict[str, Any]] = None

    def copy(self) -> "_InsertState":
        new = _InsertState()
        new.returning = self.returning
        new.on_conflict = self.on_conflict
        new.on_duplicate = (
            dict(self.on_duplicate) if self.on_duplicate is not None else None
        )
        return new


class _OnConflict:
    __slots__ = ("on", "do")

    def __init__(self, on: Any, do: Any) -> None:
        self.on = on
        self.do = do


# ---------------------------------------------------------------------------
# cur.sql namespace
# ---------------------------------------------------------------------------


class _SqlNamespace:
    __slots__ = ("_cursor",)

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def nothing(self):
        return _SqlDoNothing()

    def update(self, **kwargs):
        if not kwargs:
            raise JustormValueError(
                "cur.sql.update() requires at least one assignment"
            )
        return _SqlDoUpdate(kwargs)

    def columns(self, *names):
        if not names:
            raise JustormValueError(
                "cur.sql.columns() requires at least one column"
            )
        for n in names:
            if not isinstance(n, str) or not n:
                raise JustormTypeError(
                    "cur.sql.columns() names must be non-empty strings"
                )
        return _SqlColumns(list(names))

    def constraint(self, name):
        if not isinstance(name, str) or not name:
            raise JustormTypeError(
                "cur.sql.constraint() expects a non-empty string"
            )
        return _SqlConstraint(name)

    def where(self, *conditions, **kwargs):
        if conditions and kwargs:
            raise JustormTypeError(
                "cur.sql.where() got both positional and keyword arguments"
            )
        conds: List[Condition] = []
        if conditions:
            for c in conditions:
                if not isinstance(c, Condition):
                    raise JustormTypeError(
                        "cur.sql.where() positional arguments must be "
                        "Conditions"
                    )
                conds.append(c)
        for k, v in kwargs.items():
            conds.append(_eq_condition(k, v))
        return _SqlWhere(conds)


class _SqlDoNothing:
    __slots__ = ()
    kind = "nothing"


class _SqlDoUpdate:
    __slots__ = ("_assignments",)
    kind = "update"

    def __init__(self, assignments):
        self._assignments = dict(assignments)

    @property
    def assignments(self):
        return dict(self._assignments)


class _SqlColumns:
    __slots__ = ("_names", "_where")
    kind = "columns"

    def __init__(self, names, where=None):
        self._names = names
        self._where = where or []

    @property
    def names(self):
        return list(self._names)

    @property
    def where_conditions(self):
        return list(self._where)


class _SqlConstraint:
    __slots__ = ("_name",)
    kind = "constraint"

    def __init__(self, name):
        self._name = name

    @property
    def name(self):
        return self._name


class _SqlWhere:
    __slots__ = ("_conditions",)

    def __init__(self, conditions):
        self._conditions = conditions

    def columns(self, *names):
        if not names:
            raise JustormValueError(
                "cur.sql.where(...).columns() requires names"
            )
        for n in names:
            if not isinstance(n, str) or not n:
                raise JustormTypeError(
                    "column names must be non-empty strings"
                )
        return _SqlColumns(list(names), self._conditions)

    def update(self, **kwargs):
        if not kwargs:
            raise JustormValueError(
                "update() requires at least one assignment"
            )
        return _SqlDoUpdateWith(self._conditions, kwargs)


class _SqlDoUpdateWith:
    __slots__ = ("_conditions", "_assignments")
    kind = "update_with_where"

    def __init__(self, conditions, assignments):
        self._conditions = conditions
        self._assignments = dict(assignments)

    @property
    def assignments(self):
        return dict(self._assignments)

    @property
    def where_conditions(self):
        return list(self._conditions)


def _render_on_conflict_do(do, cursor):
    if isinstance(do, _SqlDoNothing):
        return "DO NOTHING", []
    if isinstance(do, _SqlDoUpdate):
        return _render_do_update(do.assignments, [], cursor)
    if isinstance(do, _SqlDoUpdateWith):
        return _render_do_update(do.assignments, do.where_conditions, cursor)
    raise JustormTypeError(
        f"on_conflict(do=...) expects cur.sql.nothing() or "
        f"cur.sql.update(...); got {type(do).__name__}"
    )


def _render_do_update(assignments, where_conditions, cursor):
    sets: List[str] = []
    params: List[Any] = []
    for name, value in assignments.items():
        ident = cursor._render_identifier(name)
        frag, val_params = _render_value(value, cursor)
        sets.append(f"{ident} = {frag}")
        params.extend(val_params)
    sql = "DO UPDATE SET " + ", ".join(sets)
    if where_conditions:
        where_sql, where_params = _render_conditions(where_conditions, cursor)
        sql += " WHERE " + where_sql
        params.extend(where_params)
    return sql, params


def _render_conditions(conditions, cursor):
    parts: List[str] = []
    params: List[Any] = []
    for c in conditions:
        parts.append(c._render_fragment(cursor))
        params.extend(c.params)
    return " AND ".join(parts), params


def _render_value(value, cursor):
    if isinstance(value, _AliasedExpr):
        raise JustormTypeError("aliased expressions are not valid here")
    if isinstance(value, ColumnExpr):
        return value._render(cursor), []
    if isinstance(value, _BoundExpr):
        return value._render(cursor), list(value.params)
    if isinstance(value, Expr):
        return value._render(cursor), []
    return _PH, [value]


def _render_order_item(expr, cursor, *, desc):
    suffix = " DESC" if desc else ""
    if isinstance(expr, str):
        return cursor._render_identifier(expr) + suffix
    if isinstance(expr, (ColumnExpr, Expr)):
        return expr._render(cursor) + suffix
    raise JustormTypeError(
        f"orderby expects str or Expr, got {type(expr).__name__}"
    )


def _values_for_row(row, columns, cursor):
    supports_default = getattr(cursor, "supports_values_default", True)
    cells: List[str] = []
    params: List[Any] = []
    for col in columns:
        if col in row:
            cells.append(_PH)
            params.append(row[col])
        else:
            cells.append("DEFAULT" if supports_default else "NULL")
    return cells, params


def _normalise_append_row(row, columns, kwargs):
    if row is None:
        row_dict: Dict[str, Any] = {}
    elif isinstance(row, dict):
        row_dict = dict(row)
    elif isinstance(row, (list, tuple)):
        if len(row) == 0:
            return None
        if columns is None:
            raise JustormTypeError(
                "append() with a tuple/list requires columns=[...]"
            )
        if len(row) != len(columns):
            raise JustormValueError(
                "append() row length does not match columns"
            )
        row_dict = dict(zip(columns, row))
    else:
        raise JustormTypeError(
            f"append() expects a dict, tuple, or kwargs; "
            f"got {type(row).__name__}"
        )
    if kwargs:
        row_dict.update(kwargs)
    return row_dict


def _normalise_insert_rows(rows, columns):
    if isinstance(rows, (str, bytes)):
        raise JustormTypeError("insert() expects an iterable of rows")
    out: List[Dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(dict(row))
        elif isinstance(row, (list, tuple)):
            if columns is None:
                raise JustormTypeError(
                    "insert() with tuple/list rows requires columns=[...]"
                )
            if len(row) != len(columns):
                raise JustormValueError(
                    "insert() row length does not match columns"
                )
            out.append(dict(zip(columns, row)))
        else:
            raise JustormTypeError(
                f"insert() rows must be dicts or tuples; "
                f"got {type(row).__name__}"
            )
    return out


def _row_to_param_list(row, columns):
    if isinstance(row, dict):
        return [row.get(c) for c in columns]
    if isinstance(row, (list, tuple)):
        if len(row) != len(columns):
            raise JustormValueError(
                "insert_many row length does not match columns"
            )
        return list(row)
    raise JustormTypeError(
        f"insert_many rows must be dicts or tuples; "
        f"got {type(row).__name__}"
    )


def _normalise_update(row, kwargs):
    assignments: List[Tuple[str, Any]] = []
    if row is not None:
        if not isinstance(row, dict):
            raise JustormTypeError(
                f"update() first argument must be a dict, "
                f"got {type(row).__name__}"
            )
        for k, v in row.items():
            assignments.append((k, v))
    for k, v in kwargs.items():
        assignments = [(n, val) for n, val in assignments if n != k]
        assignments.append((k, v))
    return assignments


def _template_placeholder_names(sql: str) -> List[str]:
    """Return the ``:p<n>`` names embedded in a template SQL string."""
    names: List[str] = []
    i = 0
    while True:
        idx = sql.find(":", i)
        if idx == -1:
            break
        # Expect ``:p`` followed by a digit.
        if not sql.startswith(":p", idx):
            i = idx + 1
            continue
        j = idx + 2
        while j < len(sql) and sql[j].isdigit():
            j += 1
        names.append(sql[idx + 1 : j])
        i = j
    return names


# ---------------------------------------------------------------------------
# Result shaping
# ---------------------------------------------------------------------------


def _shape_rows(
    rows, shape, key, key_conflict, projection,
    projection_names, cursor, has_key_col,
):
    if key is None:
        if shape == "scalar":
            return [r[0] for r in rows]
        if shape == "tuple":
            return [tuple(r) for r in rows]
        return _rows_to_dicts(rows, projection, projection_names, cursor)

    if has_key_col:
        return _group_by_last_column(
            rows, shape, key_conflict, projection,
            projection_names, cursor,
        )

    if _is_star_projection(projection):
        idx = _find_key_index_in_description(key, cursor)
        if idx is None:
            raise JustormValueError(
                f"key={key!r} is not part of the selected columns"
            )
        return _group_by_index(
            rows, shape, idx, key_conflict, projection,
            projection_names, cursor,
        )

    idx = _find_key_index(projection, key)
    if idx is None:
        raise JustormValueError(
            f"key={key!r} is not part of the selected columns"
        )
    return _group_by_index(
        rows, shape, idx, key_conflict, projection,
        projection_names, cursor,
    )


def _find_key_index(projection, key):
    for i, item in enumerate(projection):
        if isinstance(key, str) and isinstance(item, str):
            if item == key:
                return i
        elif item is key:
            return i
    return None


def _find_key_index_in_description(key, cursor):
    desc = cursor.description
    if desc is None:
        return None
    if isinstance(key, str):
        for i, item in enumerate(desc):
            if item[0] == key:
                return i
        return None
    return None


def _group_by_last_column(
    rows, shape, key_conflict, projection,
    projection_names, cursor,
):
    out = {}
    for row in rows:
        k = row[-1]
        value = _shape_grouped_value(
            row[:-1], shape, projection, projection_names, cursor,
        )
        if k in out:
            out[k] = _resolve_conflict(out[k], value, key_conflict)
        else:
            out[k] = value
    return out


def _group_by_index(
    rows, shape, idx, key_conflict, projection,
    projection_names, cursor,
):
    out = {}
    for row in rows:
        k = row[idx]
        value = _shape_grouped_value(
            row, shape, projection, projection_names, cursor,
        )
        if k in out:
            out[k] = _resolve_conflict(out[k], value, key_conflict)
        else:
            out[k] = value
    return out


def _shape_grouped_value(row, shape, projection, projection_names, cursor):
    if shape == "scalar":
        return row[0]
    if shape == "tuple":
        return tuple(row)
    return _row_to_dict(row, projection, projection_names, cursor)


def _rows_to_dicts(rows, projection, projection_names, cursor):
    if not rows:
        return []
    names = _column_names(rows, projection, projection_names, cursor)
    return [_row_to_dict_with_names(r, names) for r in rows]


def _row_to_dict(row, projection, projection_names, cursor):
    names = _column_names([row], projection, projection_names, cursor)
    return _row_to_dict_with_names(row, names)


def _row_to_dict_with_names(row, names):
    d: Dict[str, Any] = {}
    for i, val in enumerate(row):
        name = names[i] if i < len(names) else f"col{i}"
        d[name] = val
    return d


def _column_names(rows, projection, projection_names, cursor):
    if _is_star_projection(projection):
        description = cursor.description
        if description is None:
            raise JustormError(
                "cannot determine column names: cursor has no description"
            )
        return [d[0] for d in description]
    names: List[str] = []
    for i, item in enumerate(projection):
        guess = projection_names[i] if i < len(projection_names) else None
        if guess is None:
            desc = cursor.description
            if desc is not None and i < len(desc):
                guess = desc[i][0]
            else:
                guess = f"col{i}"
        names.append(guess)
    return names


def _resolve_conflict(old, new, policy):
    if policy == "error":
        raise JustormValueError("key_conflict: duplicate key")
    if policy == "overwrite":
        return new
    if callable(policy):
        return policy(old, new)
    raise JustormValueError(f"unknown key_conflict policy: {policy!r}")


def _shape_returning_one(row, returning):
    if row is None:
        return None
    if len(returning) == 1:
        return row[0]
    return tuple(row)


def _shape_returning_many(rows, returning):
    if len(returning) == 1:
        return [r[0] for r in rows]
    return [tuple(r) for r in rows]


# ---------------------------------------------------------------------------
# Subquery
# ---------------------------------------------------------------------------


class Subquery:
    __slots__ = ("_builder", "_projection")

    def __init__(self, builder, projection):
        self._builder = builder
        self._projection = projection

    def as_(self, alias):
        if not isinstance(alias, str) or not alias:
            raise JustormTypeError(
                "subquery alias must be a non-empty string"
            )
        return _SubqueryAlias(self, alias)

    def __getitem__(self, col):
        raise JustormValueError(
            "a subquery must be aliased before its columns can be "
            "referenced: use sub.as_('x')['col']"
        )

    def _render_sql(self, cursor):
        # ``nested=True`` keeps ``_PH`` markers in place so the outer
        # statement can bind them together with its own.
        sql, params, _ = self._builder._render_select(
            self._projection, nested=True
        )
        return sql, params


class _SubqueryAlias:
    __slots__ = ("subquery", "alias", "_cursor", "_state")

    def __init__(self, subquery, alias):
        self.subquery = subquery
        self.alias = alias
        self._cursor = subquery._builder._cursor
        self._state = _QueryState(_TableSource(None, alias))

    def __getitem__(self, col):
        if col == "*":
            raise JustormValueError(
                "subquery['*'] is not supported; use cur['alias.*'] instead"
            )
        return ColumnExpr(self.alias, col)

    def _clone(self):
        new = object.__new__(_SubqueryAlias)
        new.subquery = self.subquery
        new.alias = self.alias
        new._cursor = self._cursor
        new._state = self._state.copy()
        return new

    def join(self, right, *, on=None, using=None, how="inner"):
        return _subquery_alias_join(self, right, on=on, using=using, how=how)

    def inner_join(self, right, *, on=None, using=None):
        return _subquery_alias_join(self, right, on=on, using=using, how="inner")

    def left_join(self, right, *, on=None, using=None):
        return _subquery_alias_join(self, right, on=on, using=using, how="left")

    def right_join(self, right, *, on=None, using=None):
        return _subquery_alias_join(self, right, on=on, using=using, how="right")

    def full_join(self, right, *, on=None, using=None):
        return _subquery_alias_join(self, right, on=on, using=using, how="full")

    def cross_join(self, right):
        return _subquery_alias_join(self, right, on=None, using=None, how="cross")

    def where(self, *conditions, **kwargs):
        return _subquery_alias_where(self, conditions, kwargs)

    def where_raw(self, sql, params=None):
        new = self._clone()
        new._state.where.add(_WrappedCondition(sql, list(params or [])))
        return new

    def orderby(self, *exprs):
        new = self._clone()
        for e in exprs:
            new._state.order.append(
                _render_order_item(e, self._cursor, desc=False)
            )
        return new

    def orderby_desc(self, *exprs):
        new = self._clone()
        for e in exprs:
            new._state.order.append(
                _render_order_item(e, self._cursor, desc=True)
            )
        return new

    def limit(self, n):
        new = self._clone()
        new._state.limit = int(n)
        return new

    def offset(self, n):
        new = self._clone()
        new._state.offset = int(n)
        return new

    def all(self):
        new = self._clone()
        new._state.where.mark_all()
        return new

    def select(self, *args, **kwargs):
        return _subquery_alias_select(self, args, kwargs)

    def select_subquery(self, *args):
        return _subquery_alias_select_subquery(self, args)


def _subquery_alias_join(alias, right, *, on, using, how):
    if how not in _JOIN_KEYWORD:
        raise JustormValueError(f"unknown join type: {how!r}")
    if how == "cross":
        if on is not None or using is not None:
            raise JustormValueError("cross join does not accept on/using")
    else:
        if (on is None) == (using is None):
            raise JustormValueError(
                f"{how} join requires exactly one of on / using"
            )
    _render_from_item(right, alias._cursor)
    new = alias._clone()
    new._state.joins = new._state.joins + [
        _Join(
            right=right,
            on=on,
            using=list(using) if using else None,
            how=how,
        )
    ]
    return new


def _subquery_alias_where(alias, conditions, kwargs):
    new = alias._clone()
    if conditions:
        if kwargs:
            raise JustormTypeError(
                ".where() accepts either positional Conditions or "
                "keyword arguments, not both"
            )
        for cond in conditions:
            if not isinstance(cond, Condition):
                raise JustormTypeError(
                    f".where() expects Condition objects, got "
                    f"{type(cond).__name__}"
                )
            new._state.where.add(cond)
        return new
    for k, v in kwargs.items():
        new._state.where.add(_eq_condition(k, v))
    return new


def _subquery_alias_select(alias, args, kwargs):
    return _SubqueryFacade(alias).select(*args, **kwargs)


def _subquery_alias_select_subquery(alias, args):
    return _SubqueryFacade(alias).select_subquery(*args)


class _SubqueryFacade:
    __slots__ = ("_alias",)

    def __init__(self, alias):
        self._alias = alias

    def _as_table_builder(self):
        tb = object.__new__(TableBuilder)
        tb._cursor = self._alias._cursor
        tb._state = self._alias._state
        tb._insert_state = None
        tb._state.from_source = self._alias
        return tb

    def select(self, *args, **kwargs):
        return self._as_table_builder().select(*args, **kwargs)

    def select_subquery(self, *args):
        return self._as_table_builder().select_subquery(*args)

