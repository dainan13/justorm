"""justorm - a lightweight, schemaless SQL builder.

``justorm`` mixes a fluent query builder into the native cursor classes of
several database drivers.  It intentionally does **not** try to hide the
differences between dialects: users are expected to know which database they
are talking to, and the API reflects that.

Typical usage::

    import psycopg
    import justorm.psycopg

    conn = psycopg.connect(...)
    with conn.cursor(justorm.psycopg.Cursor) as cur:
        rows = cur.users.where(id=1).select()

The top-level package deliberately imports **no** database driver.  Driver
specific entry points live in submodules and must be imported explicitly::

    import justorm.psycopg      # psycopg (v3)
    import justorm.psycopg2     # psycopg2
    import justorm.pymysql      # PyMySQL
    import justorm.sqlite       # sqlite3 (standard library)

This makes ``import justorm`` cheap and safe even when a particular driver
is not installed.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "JustormError",
]


class JustormError(Exception):
    """Base class for every error raised by justorm itself.

    Errors coming from the underlying DB-API driver (for example
    ``psycopg.Error`` or ``sqlite3.OperationalError``) are **not** wrapped;
    they propagate unchanged so that users can keep using their driver's
    usual exception handling.

    justorm raises this type for problems detected before the SQL reaches
    the database, such as:

    * using a dialect-specific feature on an unsupported dialect
      (e.g. ``.returning(...)`` on MySQL),
    * malformed builder usage (e.g. calling ``.update(...)`` on a builder
      that has neither ``.where(...)`` nor ``.all()``),
    * passing an argument of a type the builder does not understand.

    See the individual subclasses for more specific conditions.
    """


class JustormTypeError(JustormError, TypeError):
    """Raised when an argument has an unsupported type.

    Inherits from both :class:`JustormError` and the built-in
    :class:`TypeError` so that ``except TypeError`` keeps working for
    callers who do not want to depend on justorm's exception hierarchy.
    """


class JustormValueError(JustormError, ValueError):
    """Raised when an argument has a supported type but an invalid value.

    Inherits from both :class:`JustormError` and the built-in
    :class:`ValueError` for the same reason as :class:`JustormTypeError`.
    """


class JustormDialectError(JustormError):
    """Raised when a feature is not supported by the current dialect.

    Examples:

    * ``.returning(...)`` on MySQL,
    * ``.distinct_on(...)`` on MySQL or SQLite,
    * ``.select(for_update=True)`` on SQLite,
    * ``.on_conflict(on=cur.sql.constraint('...'))`` on SQLite.

    These errors are raised at the *last possible moment*, i.e. when the
    terminal method (``.select()``, ``.insert()``, ...) is called, not when
    the offending builder method is invoked.  This mirrors the general
    "report problems as late as possible" policy of justorm.
    """


# Convenience re-exports for the exception hierarchy.  These names are not
# in ``__all__`` on purpose: the canonical place to import them from is the
# top-level ``justorm`` package, and we do not want ``from justorm import *``
# to pull them in silently.
_ = (JustormTypeError, JustormValueError, JustormDialectError)
