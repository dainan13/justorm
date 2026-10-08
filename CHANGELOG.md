# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-09-29

Initial release.

### Added

- **Fluent builder that mixes into native DB-API cursors.**  Each
  driver's cursor is a subclass of that driver's own cursor (or, for
  SQLite, a thin wrapper around it), so the native DB-API surface keeps
  working unchanged.

- **Supported drivers:**
  - `justorm.psycopg` — psycopg (v3), PostgreSQL.
  - `justorm.psycopg2` — psycopg2, PostgreSQL.
  - `justorm.pymysql` — PyMySQL, MySQL / MariaDB.
  - `justorm.sqlite` — sqlite3, SQLite (standard library).
  - `justorm.pymssql` — pymssql, SQL Server.
  - `justorm.oracledb` — python-oracledb, Oracle.

- **Query features:**
  - `select` with projection by `set` / `list` / `tuple` / `str` /
    `Expr`, plus `key=` for keyed dict results and `key_conflict=` for
    duplicate-key policy.
  - `get` for single-row retrieval with an optional `default`.
  - `append` (single row), `insert` (many rows, one statement),
    `insert_many` (driver `executemany`).
  - `update` and `delete` with a mandatory `where` (or explicit
    `.all()`).
  - `returning` on PostgreSQL and SQLite.
  - `where`, `where_in`, `where_not_in`, `where_between`,
    `where_is_null`, `where_like`, `where_ilike`, `where_raw`.
  - `orderby`, `orderby_desc`, `limit`, `offset`, `distinct`,
    `distinct_on` (PostgreSQL).
  - Joins: `join`, `inner_join`, `left_join`, `right_join`,
    `full_join`, `cross_join`, plus `using=` and `as_` for aliasing.
  - Subqueries via `select_subquery()` and `.as_()`, usable as a join
    target or as the primary table.
  - Upserts: `on_conflict(...)` on PostgreSQL / SQLite and
    `on_duplicate(...)` on MySQL, with a `cur.sql` namespace for
    targets and actions.
  - Row locking via `select(for_update=..., skip_locked=..., nowait=...)`.
  - Expression DSL: `cur['...']` (verbatim), `cur.<table>['col']`
    (quoted column reference), operator overloading for comparisons and
    arithmetic, and `as_()` for aliases.

- **Cursor features:**
  - `query(sql, params=None)` — one-call "execute and shape the
    result": `list[dict]` for `SELECT`, `int` for DML / DDL.
  - `fetchone` / `fetchmany` / `fetchall` accept `format=dict`,
    `format=namedtuple`, or `format=tuple`.  The default (`None`)
    returns exactly what the driver returned.

- **Dialect exposure instead of abstraction.**  Differences between
  PostgreSQL, MySQL, SQLite, SQL Server, and Oracle are visible in the
  API: `.on_conflict(...)` vs `.on_duplicate(...)`, `RETURNING`
  available on some dialects only, `DISTINCT ON` and `ILIKE` restricted
  to PostgreSQL, and so on.  Unsupported features are rejected at the
  last possible moment (when the terminal method runs) with
  `JustormDialectError`.

- **Documentation** in `docs/zh/` (Chinese) and `docs/en/` (English),
  covering quickstart, API reference, dialects, upsert, join,
  subquery, expressions, security, and migration.

### Testing

- 700 tests covering the builder, renderers, row-conversion helpers,
  and integration against all six supported drivers: PostgreSQL
  (psycopg v3 and psycopg2), MySQL (PyMySQL), SQLite (sqlite3),
  SQL Server (pymssql), and Oracle (python-oracledb).

### Notes

- **Asynchronous drivers are not supported.**  The current release is
  synchronous only.

- **No connection pooling, no session management, no schema
  introspection, no migrations.**  justorm is a builder, not an ORM;
  those concerns belong to the surrounding application or to the
  driver.

[Unreleased]: https://github.com/dainan13/justorm/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/dainan13/justorm/releases/tag/v1.0.0
