"""Dialect renderers.

A renderer knows how to turn the abstract pieces of a query
(identifiers, placeholders, keywords, and a handful of dialect-specific
clauses) into the concrete SQL text expected by a given database
engine.

Renderers are deliberately *not* tied to any driver.  They only produce
strings.  The builder is responsible for collecting parameters; the
renderer never sees them.

Naming conventions used throughout this file:

``render_*`` methods return a ``str``.  Methods that a builder may call
are all defined on :class:`JustRenderABS` so that type checkers and IDEs
can see the full surface of a renderer.  Dialects that do not support a
feature raise :class:`justorm.JustormDialectError` from the
corresponding ``render_*`` method; the builder is expected to call the
method at the last possible moment, so the error surfaces when the
statement is about to run.
"""

from __future__ import annotations

from typing import Optional, Sequence

__all__ = [
    "JustRenderABS",
    "PGRenderer",
    "MySQLRenderer",
    "SQLiteRenderer",
    "MSSQLRenderer",
    "OracleRenderer",
]


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class JustRenderABS:
    """Abstract base class for dialect renderers."""

    #: Human-readable dialect name, used in error messages.
    dialect_name: str = "unknown"

    #: Whether the dialect uses ``DEFAULT`` in a ``VALUES`` list.
    supports_values_default: bool = True

    #: Whether the dialect uses *named* placeholders (Oracle) rather
    #: than anonymous ``%s`` / ``?`` markers.  When this is True, the
    #: builder generates random ``:p<hex>`` names for each placeholder
    #: and passes parameters as a dict.
    uses_named_placeholders: bool = False

    # ------------------------------------------------------------------
    # Identifiers
    # ------------------------------------------------------------------

    def render_identifier(self, name: str) -> str:
        raise NotImplementedError

    def render_identifier_multi(self, *names: str) -> str:
        if not names:
            raise ValueError(
                "render_identifier_multi requires at least one name"
            )
        return ".".join(self.render_identifier(n) for n in names)

    # ------------------------------------------------------------------
    # Placeholders
    # ------------------------------------------------------------------

    def render_placeholder(self) -> str:
        raise NotImplementedError

    def render_placeholder_list(self, count: int) -> str:
        if count < 0:
            raise ValueError("count must be non-negative")
        ph = self.render_placeholder()
        return ", ".join([ph] * count)

    # ------------------------------------------------------------------
    # Literals and keywords
    # ------------------------------------------------------------------

    def render_keyword(self, keyword: str) -> str:
        return keyword

    def escape_percent(self, text: str) -> str:
        return text

    # ------------------------------------------------------------------
    # Dialect-specific clauses
    # ------------------------------------------------------------------

    def render_returning(self, columns: Sequence[str]) -> str:
        raise NotImplementedError

    def render_on_conflict(
        self,
        target: Optional[str],
        do_clause: str,
    ) -> str:
        raise NotImplementedError

    def render_on_conflict_target(
        self,
        columns: Optional[Sequence[str]],
        constraint: Optional[str],
        index_where: Optional[str],
    ) -> str:
        raise NotImplementedError

    def render_on_duplicate(self, update_clause: str) -> str:
        raise NotImplementedError

    def render_limit_offset(
        self,
        limit: Optional[int],
        offset: Optional[int],
    ) -> str:
        parts: list = []
        if limit is not None:
            parts.append(f"LIMIT {int(limit)}")
        if offset is not None:
            parts.append(f"OFFSET {int(offset)}")
        return " ".join(parts)

    def render_for_update(
        self,
        *,
        share: bool = False,
        skip_locked: bool = False,
        nowait: bool = False,
    ) -> str:
        raise NotImplementedError

    def render_distinct_on(self, columns: Sequence[str]) -> str:
        raise NotImplementedError

    def render_ilike(self, left: str, right: str) -> str:
        raise NotImplementedError

    def quote_join(self, parts: Sequence[str]) -> str:
        return ", ".join(parts)


# ---------------------------------------------------------------------------
# PostgreSQL (psycopg / psycopg2)
# ---------------------------------------------------------------------------


class PGRenderer(JustRenderABS):
    """Renderer for PostgreSQL."""

    dialect_name = "postgresql"
    supports_values_default = True

    def render_identifier(self, name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    def render_placeholder(self) -> str:
        return "%s"

    def escape_percent(self, text: str) -> str:
        return text.replace("%", "%%")

    def render_returning(self, columns: Sequence[str]) -> str:
        if not columns:
            return ""
        return "RETURNING " + self.quote_join(columns)

    def render_on_conflict_target(
        self,
        columns: Optional[Sequence[str]],
        constraint: Optional[str],
        index_where: Optional[str],
    ) -> str:
        if constraint is not None:
            return f"ON CONSTRAINT {self.render_identifier(constraint)}"
        if columns is not None:
            quoted = ", ".join(
                self.render_identifier(c) for c in columns
            )
            target = f"({quoted})"
            if index_where:
                target += " WHERE " + index_where
            return target
        return ""

    def render_on_conflict(
        self,
        target: Optional[str],
        do_clause: str,
    ) -> str:
        if target:
            return f"ON CONFLICT {target} {do_clause}"
        return f"ON CONFLICT {do_clause}"

    def render_on_duplicate(self, update_clause: str) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "ON DUPLICATE KEY UPDATE is not supported by PostgreSQL; "
            "use .on_conflict(...) instead"
        )

    def render_for_update(
        self,
        *,
        share: bool = False,
        skip_locked: bool = False,
        nowait: bool = False,
    ) -> str:
        clause = "FOR SHARE" if share else "FOR UPDATE"
        if nowait and skip_locked:
            raise ValueError(
                "nowait and skip_locked are mutually exclusive"
            )
        if nowait:
            clause += " NOWAIT"
        elif skip_locked:
            clause += " SKIP LOCKED"
        return clause

    def render_distinct_on(self, columns: Sequence[str]) -> str:
        if not columns:
            raise ValueError(
                "DISTINCT ON requires at least one column"
            )
        quoted = ", ".join(
            self.render_identifier(c) for c in columns
        )
        return f"DISTINCT ON ({quoted})"

    def render_ilike(self, left: str, right: str) -> str:
        return f"{left} ILIKE {right}"


# ---------------------------------------------------------------------------
# MySQL (PyMySQL)
# ---------------------------------------------------------------------------


class MySQLRenderer(JustRenderABS):
    """Renderer for MySQL / MariaDB."""

    dialect_name = "mysql"
    supports_values_default = True

    def render_identifier(self, name: str) -> str:
        return "`" + name.replace("`", "``") + "`"

    def render_placeholder(self) -> str:
        return "%s"

    def escape_percent(self, text: str) -> str:
        return text.replace("%", "%%")

    def render_returning(self, columns: Sequence[str]) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "MySQL does not support RETURNING; "
            "use LAST_INSERT_ID() or a subsequent SELECT instead"
        )

    def render_on_conflict_target(
        self,
        columns: Optional[Sequence[str]],
        constraint: Optional[str],
        index_where: Optional[str],
    ) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "MySQL does not support ON CONFLICT; "
            "use .on_duplicate(...) instead"
        )

    def render_on_conflict(
        self,
        target: Optional[str],
        do_clause: str,
    ) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "MySQL does not support ON CONFLICT; "
            "use .on_duplicate(...) instead"
        )

    def render_on_duplicate(self, update_clause: str) -> str:
        if not update_clause:
            raise ValueError(
                "ON DUPLICATE KEY UPDATE requires at least one assignment"
            )
        return f"ON DUPLICATE KEY UPDATE {update_clause}"

    def render_limit_offset(
        self,
        limit: Optional[int],
        offset: Optional[int],
    ) -> str:
        parts: list = []
        if limit is not None:
            parts.append(f"LIMIT {int(limit)}")
        if offset is not None:
            if limit is None:
                raise ValueError(
                    "MySQL requires LIMIT when OFFSET is used"
                )
            parts.append(f"OFFSET {int(offset)}")
        return " ".join(parts)

    def render_for_update(
        self,
        *,
        share: bool = False,
        skip_locked: bool = False,
        nowait: bool = False,
    ) -> str:
        clause = "FOR SHARE" if share else "FOR UPDATE"
        if nowait:
            clause += " NOWAIT"
        if skip_locked:
            clause += " SKIP LOCKED"
        return clause

    def render_distinct_on(self, columns: Sequence[str]) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError("MySQL does not support DISTINCT ON")

    def render_ilike(self, left: str, right: str) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "MySQL does not support ILIKE; use LIKE with a "
            "case-insensitive collation instead"
        )


# ---------------------------------------------------------------------------
# SQLite (sqlite3)
# ---------------------------------------------------------------------------


class SQLiteRenderer(JustRenderABS):
    """Renderer for SQLite."""

    dialect_name = "sqlite"
    supports_values_default = False

    def render_identifier(self, name: str) -> str:
        # SQLite accepts ``"name"``, ``` `name` ```, and ``[name]``.  The
        # double-quoted form falls back to a string literal when the
        # identifier does not exist, which masks "no such column"
        # errors.  Backticks do not have that fallback.
        return "`" + name.replace("`", "``") + "`"

    def render_placeholder(self) -> str:
        return "?"

    def render_returning(self, columns: Sequence[str]) -> str:
        if not columns:
            return ""
        return "RETURNING " + self.quote_join(columns)

    def render_on_conflict_target(
        self,
        columns: Optional[Sequence[str]],
        constraint: Optional[str],
        index_where: Optional[str],
    ) -> str:
        from justorm import JustormDialectError

        if constraint is not None:
            raise JustormDialectError(
                "SQLite does not support ON CONFLICT ON CONSTRAINT"
            )
        if index_where is not None:
            raise JustormDialectError(
                "SQLite does not support index predicates in "
                "ON CONFLICT"
            )
        if columns is None:
            return ""
        quoted = ", ".join(
            self.render_identifier(c) for c in columns
        )
        return f"({quoted})"

    def render_on_conflict(
        self,
        target: Optional[str],
        do_clause: str,
    ) -> str:
        if target:
            return f"ON CONFLICT {target} {do_clause}"
        return f"ON CONFLICT {do_clause}"

    def render_on_duplicate(self, update_clause: str) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "SQLite does not support ON DUPLICATE KEY UPDATE; "
            "use .on_conflict(...) instead"
        )

    def render_limit_offset(
        self,
        limit: Optional[int],
        offset: Optional[int],
    ) -> str:
        parts: list = []
        if limit is not None:
            parts.append(f"LIMIT {int(limit)}")
        if offset is not None:
            if limit is None:
                parts.append("LIMIT -1")
            parts.append(f"OFFSET {int(offset)}")
        return " ".join(parts)

    def render_for_update(
        self,
        *,
        share: bool = False,
        skip_locked: bool = False,
        nowait: bool = False,
    ) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "SQLite does not support FOR UPDATE / FOR SHARE"
        )

    def render_distinct_on(self, columns: Sequence[str]) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError("SQLite does not support DISTINCT ON")

    def render_ilike(self, left: str, right: str) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "SQLite does not support ILIKE; use LIKE with "
            "COLLATE NOCASE instead"
        )


# ---------------------------------------------------------------------------
# SQL Server (pymssql)
# ---------------------------------------------------------------------------


class MSSQLRenderer(JustRenderABS):
    """Renderer for SQL Server, used with the PyMSSQL driver.

    The driver-specific details justorm exposes:

    * identifiers are quoted with square brackets, SQL Server's native
      quoting style,
    * ``%s`` is used for placeholders (PyMSSQL's own convention),
    * ``RETURNING`` is not available; the equivalent is the ``OUTPUT``
      clause, which has a different shape and is best written as raw
      SQL,
    * upserts use ``MERGE``, which justorm does not model,
    * ``LIMIT`` / ``OFFSET`` map to ``OFFSET ... ROWS FETCH NEXT ...
      ROWS ONLY``, which requires an ``ORDER BY`` clause,
    * ``FOR UPDATE`` is not a thing on SQL Server; row locking is done
      through table hints such as ``WITH (UPDLOCK)``,
    * ``DISTINCT ON`` and ``ILIKE`` are not available.
    """

    dialect_name = "pymssql"
    supports_values_default = True

    def render_identifier(self, name: str) -> str:
        return "[" + name.replace("]", "]]") + "]"

    def render_placeholder(self) -> str:
        return "%s"

    def escape_percent(self, text: str) -> str:
        return text.replace("%", "%%")

    def render_returning(self, columns: Sequence[str]) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "pymssql does not support RETURNING; the SQL Server "
            "equivalent is an OUTPUT clause, which must be written as "
            "raw SQL via cur.query(...)"
        )

    def render_on_conflict_target(
        self,
        columns: Optional[Sequence[str]],
        constraint: Optional[str],
        index_where: Optional[str],
    ) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "pymssql does not support ON CONFLICT; use MERGE via "
            "cur.query(...) instead"
        )

    def render_on_conflict(
        self,
        target: Optional[str],
        do_clause: str,
    ) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "pymssql does not support ON CONFLICT; use MERGE via "
            "cur.query(...) instead"
        )

    def render_on_duplicate(self, update_clause: str) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "pymssql does not support ON DUPLICATE KEY UPDATE; use "
            "MERGE via cur.query(...) instead"
        )

    def render_limit_offset(
        self,
        limit: Optional[int],
        offset: Optional[int],
    ) -> str:
        if limit is None and offset is None:
            return ""
        parts: list = []
        # SQL Server requires an ORDER BY for OFFSET/FETCH.  We always
        # emit OFFSET (with 0 if the caller did not provide one) so the
        # statement is well-formed.
        parts.append(f"OFFSET {int(offset) if offset is not None else 0} ROWS")
        if limit is not None:
            parts.append(f"FETCH NEXT {int(limit)} ROWS ONLY")
        return " ".join(parts)

    def render_for_update(
        self,
        *,
        share: bool = False,
        skip_locked: bool = False,
        nowait: bool = False,
    ) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "pymssql does not support FOR UPDATE; use a table hint "
            "such as WITH (UPDLOCK) via raw SQL"
        )

    def render_distinct_on(self, columns: Sequence[str]) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError("pymssql does not support DISTINCT ON")

    def render_ilike(self, left: str, right: str) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "pymssql does not support ILIKE; use LIKE with a "
            "case-insensitive collation instead"
        )


# ---------------------------------------------------------------------------
# Oracle (python-oracledb)
# ---------------------------------------------------------------------------


class OracleRenderer(JustRenderABS):
    """Renderer for Oracle, used with the python-oracledb driver.

    The driver-specific details justorm exposes:

    * identifiers are quoted with double quotes (Oracle uppercases
      unquoted identifiers, so justorm always quotes),
    * placeholders are **named** (``:p<hex>``); ``uses_named_placeholders``
      is True, which tells the builder to generate random names and
      pass parameters as a dict,
    * ``RETURNING`` requires an OUT bind variable and is not modelled,
    * upserts use ``MERGE``, which justorm does not model,
    * ``LIMIT`` / ``OFFSET`` map to ``OFFSET ... ROWS FETCH NEXT ...
      ROWS ONLY`` (12c+),
    * ``FOR UPDATE`` is supported, with the same ``NOWAIT`` /
      ``SKIP LOCKED`` modifiers as PostgreSQL,
    * ``DISTINCT ON`` and ``ILIKE`` are not available,
    * ``DEFAULT`` is not accepted inside a ``VALUES`` list.
    """

    dialect_name = "oracledb"
    supports_values_default = False
    uses_named_placeholders = True

    def render_identifier(self, name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    def render_placeholder(self) -> str:
        # Not used by the builder when ``uses_named_placeholders`` is
        # True; provided for callers that ask for one directly.
        return ":p"

    def render_returning(self, columns: Sequence[str]) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "oracledb does not support RETURNING through justorm's "
            "builder; use an OUT bind variable via cur.execute(...)"
        )

    def render_on_conflict_target(
        self,
        columns: Optional[Sequence[str]],
        constraint: Optional[str],
        index_where: Optional[str],
    ) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "oracledb does not support ON CONFLICT; use MERGE via "
            "cur.query(...) instead"
        )

    def render_on_conflict(
        self,
        target: Optional[str],
        do_clause: str,
    ) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "oracledb does not support ON CONFLICT; use MERGE via "
            "cur.query(...) instead"
        )

    def render_on_duplicate(self, update_clause: str) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "oracledb does not support ON DUPLICATE KEY UPDATE; use "
            "MERGE via cur.query(...) instead"
        )

    def render_limit_offset(
        self,
        limit: Optional[int],
        offset: Optional[int],
    ) -> str:
        parts: list = []
        if offset is not None:
            parts.append(f"OFFSET {int(offset)} ROWS")
        if limit is not None:
            parts.append(f"FETCH NEXT {int(limit)} ROWS ONLY")
        return " ".join(parts)

    def render_for_update(
        self,
        *,
        share: bool = False,
        skip_locked: bool = False,
        nowait: bool = False,
    ) -> str:
        # Oracle does not have FOR SHARE; treat ``share`` as a plain
        # FOR UPDATE, matching the caller's intent to lock rows.
        clause = "FOR UPDATE"
        if nowait:
            clause += " NOWAIT"
        elif skip_locked:
            clause += " SKIP LOCKED"
        return clause

    def render_distinct_on(self, columns: Sequence[str]) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError("oracledb does not support DISTINCT ON")

    def render_ilike(self, left: str, right: str) -> str:  # pragma: no cover
        from justorm import JustormDialectError

        raise JustormDialectError(
            "oracledb does not support ILIKE; use LIKE with NLS_UPPER()"
        )
