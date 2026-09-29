# Dialects

justorm does **not** try to hide the differences between PostgreSQL,
MySQL, SQLite, SQL Server, and Oracle.  If you are talking to MySQL,
you write `.on_duplicate(...)`.  If you are talking to PostgreSQL, you
write `.on_conflict(...)`.  If you ask for a feature your database
does not have, justorm raises an error *at the last possible moment* —
when the terminal method runs, not when the offending builder method
is called.

This page is the reference for those differences.  It is meant to be
read alongside [API reference](api.md), which describes the common
surface.

## The dialects

| Module              | Driver                                                     | Database        |
| ------------------- | ---------------------------------------------------------- | --------------- |
| `justorm.psycopg`   | [psycopg](https://www.psycopg.org/psycopg3/) (v3)          | PostgreSQL      |
| `justorm.psycopg2`  | [psycopg2](https://www.psycopg.org/)                       | PostgreSQL      |
| `justorm.pymysql`   | [PyMySQL](https://pymysql.readthedocs.io/)                 | MySQL / MariaDB |
| `justorm.sqlite`    | `sqlite3` (standard library)                               | SQLite 3        |
| `justorm.pymssql`   | [pymssql](https://pymssql.readthedocs.io/)                 | SQL Server      |
| `justorm.oracledb`  | [python-oracledb](https://python-oracledb.readthedocs.io/) | Oracle          |

`psycopg` and `psycopg2` share a single renderer, because the SQL
grammar they emit is identical.  The differences between them are in
the driver layer, not in the SQL, and justorm hides none of those:
each is a separate module with its own `Cursor` class.

## Summary table

| Feature                         | PostgreSQL | MySQL        | SQLite         | SQL Server   | Oracle        |
| ------------------------------- | ---------- | ------------ | -------------- | ------------ | ------------- |
| Identifier quoting              | `"col"`    | `` `col` ``  | `` `col` ``    | `[col]`      | `"col"`       |
| Placeholder                     | `%s`       | `%s`         | `?`            | `%s`         | `:p<hex>`     |
| `RETURNING`                     | yes        | **no**       | 3.35+          | **no**       | **no**        |
| UPSERT                          | `ON CONFLICT` | `ON DUPLICATE KEY` | `ON CONFLICT` (partial) | **no** (use `MERGE`) | **no** (use `MERGE`) |
| `ON CONFLICT ... ON CONSTRAINT` | yes        | n/a          | **no**         | n/a          | n/a           |
| `ON CONFLICT ( ... ) WHERE ...` | yes        | n/a          | **no**         | n/a          | n/a           |
| `DISTINCT ON`                   | yes        | **no**       | **no**         | **no**       | **no**        |
| `ILIKE`                         | yes        | **no**       | **no**         | **no**       | **no**        |
| `FOR UPDATE` / `FOR SHARE`      | yes        | 8.0+         | **no**         | **no**       | yes           |
| `LIMIT` without `OFFSET`        | yes        | yes          | yes            | yes          | yes           |
| `OFFSET` without `LIMIT`        | yes        | **no**       | yes (3.30+)    | yes          | yes           |
| `DEFAULT` in `VALUES`           | yes        | yes          | **no**         | yes          | **no**        |
| Insert output                   | `RETURNING` | —           | `RETURNING`    | `OUTPUT`     | `RETURNING INTO` |

"yes" / "no" mean whether justorm generates that SQL.  Some features
the database has but justorm does not model (MySQL's `UPDATE ...
LIMIT`, SQL Server's and Oracle's `MERGE`) are rejected at the API
level; use `cur.query(...)` for raw SQL.

## Identifier quoting

| Dialect    | Example                                  |
| ---------- | ---------------------------------------- |
| PostgreSQL | `"users"`, `"public"."users"`            |
| MySQL      | `` `users` ``, `` `mydb`.`users` ``      |
| SQLite     | `` `users` ``                            |
| SQL Server | `[users]`, `[dbo].[users]`               |
| Oracle     | `"users"`, `"schema"."users"`            |

You do not usually write the quotes yourself.  `cur.users`,
`cur.table("users")`, `cur.users["name"]`, and the keyword arguments
to `.where(...)` all go through the dialect's identifier renderer.

`cur["..."]` is the exception: its contents are emitted verbatim, so
you are responsible for quoting anything inside it.

### SQLite uses backticks

SQLite's double-quoted form falls back to a **string literal** when the
identifier does not exist — `WHERE "no_such_col" = 1` is parsed as
`WHERE 'no_such_col' = 1`, quietly hiding the "no such column" error.
Backticks do not have that fallback.  So justorm's SQLite renderer
uses backticks.

## Placeholders

| Dialect    | Placeholder |
| ---------- | ----------- |
| PostgreSQL | `%s`        |
| MySQL      | `%s`        |
| SQLite     | `?`         |
| SQL Server | `%s`        |
| Oracle     | `:p<hex>`   |

You do not write placeholders yourself, but the difference matters if
you use `.where_raw(...)` or `cur["..."]`:

```python
cur.users.where_raw("length(name) > %s", [5])       # PostgreSQL / MySQL / SQL Server
cur.users.where_raw("length(name) > ?", [5])        # SQLite
cur.users.where_raw("length(name) > :p1", [5])      # Oracle (but prefer the builder)
```

justorm does not translate placeholders inside a raw fragment.  Write
the placeholder your driver expects.

### Oracle's named placeholders

python-oracledb uses named placeholders (`:name`).  justorm's Oracle
path assigns a random name `:p<hex>` to every `_PH` at render time
and passes parameters to the driver as a **dict**.  What the user
sees is:

```python
cur.users.where(name="Alice").select()
# Internally:
#   SQL:    SELECT * FROM "users" WHERE "name" = :p3a4f1b2c
#   params: {"p3a4f1b2c": "Alice"}
```

Random names mean:

- no global counter is needed when placeholders are generated,
- the SQL string and the params dict are independent of each other,
  so they can be reused across connections and retries,
- `params` is dialect-specific; on the other dialects it is still a
  list.

### Percent escaping

Drivers that use `%s` placeholders (psycopg, psycopg2, PyMySQL,
pymssql) require literal percent signs in SQL text to be doubled:

```python
cur["name LIKE 'a%%'"]     # PostgreSQL / MySQL / SQL Server: matches "a..."
cur["name LIKE 'a%'"]      # SQLite / Oracle: same meaning
```

justorm applies this escaping to `Expr` content and to `.where_raw`
fragments on the dialects that need it.  SQLite and Oracle are left
alone (they do not use `%s`).

## RETURNING

| Dialect    | Support                     |
| ---------- | --------------------------- |
| PostgreSQL | yes                         |
| MySQL      | **no**                      |
| SQLite     | 3.35+                       |
| SQL Server | **no**                      |
| Oracle     | **no**                      |

```python
cur.users.returning("id").append(name="Alice")   # -> 1
```

On MySQL, SQL Server, and Oracle, the terminal method raises
`JustormDialectError`.

**MySQL users** should use `LAST_INSERT_ID()`:

```python
cur.users.append(name="Alice")
new_id = cur.execute("SELECT LAST_INSERT_ID()").fetchone()[0]
```

**SQL Server users** should use the `OUTPUT` clause, via
`cur.query(...)`:

```python
cur.query(
    "INSERT INTO users (name) OUTPUT INSERTED.id VALUES (%s)",
    ["Alice"],
)
```

**Oracle users** should use `RETURNING col INTO :var` with an OUT
bind variable, via `cur.execute(...)`.

SQLite versions older than 3.35 do not support `RETURNING`; justorm
does not try to detect the version, so the error comes from SQLite
itself at execution time.

## UPSERT

This is the largest dialect difference, and justorm exposes it
directly.

### PostgreSQL / SQLite — `on_conflict`

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(id=1, name="Alice")
```

| Form                                    | PostgreSQL | SQLite |
| --------------------------------------- | ---------- | ------ |
| `on=cur.sql.columns(...)`               | yes        | yes    |
| `on=cur.sql.constraint(...)`            | yes        | **no** |
| `on=cur.sql.where(...).columns(...)`    | yes        | **no** |
| `on=` omitted (untargeted)              | yes        | yes    |
| `do=cur.sql.nothing()`                  | yes        | yes    |
| `do=cur.sql.update(...)`                | yes        | yes    |
| `do=cur.sql.where(...).update(...)`     | yes        | yes    |

Attempting the rejected forms on SQLite raises
`JustormDialectError` when the terminal method runs.

`ON CONFLICT ON CONSTRAINT` requires the conflict target to be a
named constraint (created with `CONSTRAINT ... UNIQUE` or
`CONSTRAINT ... PRIMARY KEY`).  SQLite has no named constraints in
the sense PostgreSQL does, hence the limitation.

### MySQL — `on_duplicate`

```python
cur.users.on_duplicate(update={"name": cur["VALUES(name)"]}).append(
    id=1, name="Alice",
)
```

MySQL's `ON DUPLICATE KEY UPDATE` has no conflict target — it fires on
*any* duplicate key.  It also has no `DO NOTHING` form; the closest
equivalent is to update a column to itself.  MySQL 8.0.20+ prefers a
row alias over `VALUES(col)`; write it yourself if you need it:

```python
cur.users.on_duplicate(update={"name": cur["new.name"]}).append(
    id=1, name="Alice",
)
```

### SQL Server / Oracle — neither is supported

Both use `MERGE`, whose syntax is completely different from
`ON CONFLICT`:

```sql
MERGE INTO users AS t
USING (VALUES (1, 'Alice')) AS s (id, name)
ON t.id = s.id
WHEN MATCHED THEN UPDATE SET name = s.name
WHEN NOT MATCHED THEN INSERT (id, name) VALUES (s.id, s.name);
```

justorm does not model `MERGE`.  Write raw SQL via `cur.query(...)`.

### Cross-dialect mistakes

Using `on_conflict` on MySQL, or `on_duplicate` on PostgreSQL /
SQLite, is rejected at the last possible moment:

```python
cur.users.on_conflict(do=cur.sql.nothing()).append(id=1)   # OK on PG / SQLite
# ... same call on MySQL: JustormDialectError when append() runs
```

## DISTINCT ON

PostgreSQL only.  Rejected at the last possible moment on MySQL,
SQLite, SQL Server, and Oracle.

```python
cur.users.distinct_on("name").orderby("name").orderby_desc("id").select()
```

Note that `DISTINCT ON` requires the leading `ORDER BY` expressions to
match the `DISTINCT ON` expressions; this is a PostgreSQL rule and
justorm does not enforce it.  The database will complain.

## ILIKE

PostgreSQL only.  Rejected at the last possible moment on MySQL,
SQLite, SQL Server, and Oracle.

```python
cur.users.where_ilike(name="a%").select()
```

On MySQL, the usual workaround is a case-insensitive collation:

```python
cur.users.where_raw("name LIKE %s COLLATE utf8mb4_0900_ai_ci", ["a%"])
```

On SQLite, `LIKE` is already case-insensitive for ASCII by default, so
plain `LIKE` often suffices.

On SQL Server, use a case-insensitive collation, or:

```python
cur.users.where_raw("LOWER(name) LIKE LOWER(%s)", ["a%"])
```

On Oracle:

```python
cur.users.where_raw("NLS_UPPER(name) LIKE NLS_UPPER(:p1)", ["a%"])
```

## FOR UPDATE / FOR SHARE

| Dialect    | Support                       |
| ---------- | ----------------------------- |
| PostgreSQL | `FOR UPDATE`, `FOR SHARE`     |
| MySQL      | `FOR UPDATE`, `FOR SHARE` (8.0+) |
| SQLite     | **no**                        |
| SQL Server | **no** (use `WITH (UPDLOCK)`) |
| Oracle     | `FOR UPDATE` (no `FOR SHARE`) |

```python
cur.users.where(id=1).select(for_update=True)
cur.users.where(id=1).select(for_update=True, skip_locked=True)
cur.users.where(id=1).select(for_update="share")
```

`nowait=True` and `skip_locked=True` are mutually exclusive and raise
`JustormValueError` before the statement is built.

SQLite and SQL Server reject `FOR UPDATE` at the last possible moment.

On Oracle, `share=True` maps to `FOR UPDATE` — Oracle does not have
`FOR SHARE`, and the locking intent is the same.

## LIMIT / OFFSET

| Dialect    | Notes                                              |
| ---------- | -------------------------------------------------- |
| PostgreSQL | `LIMIT n OFFSET m` in any order                    |
| MySQL      | `OFFSET` requires `LIMIT`; error raised by the builder |
| SQLite     | `OFFSET` without `LIMIT` works since 3.30          |
| SQL Server | `OFFSET n ROWS FETCH NEXT m ROWS ONLY` (needs `ORDER BY`) |
| Oracle     | `OFFSET n ROWS FETCH NEXT m ROWS ONLY` (12c+)      |

```python
cur.users.limit(10).offset(20).select()
```

MySQL's `LIMIT offset, count` shorthand is not generated; use `LIMIT`
and `OFFSET` as above, or `.where_raw(...)` if you really need the
comma form.

SQL Server requires an `ORDER BY` for this to be legal; add one.

## UPDATE / DELETE restrictions

`UPDATE ... LIMIT` and `DELETE ... LIMIT` exist in MySQL, SQLite, and
SQL Server but not in PostgreSQL.  justorm does not generate them on
any dialect, so:

```python
cur.users.where(id=1).limit(1).delete()     # raises
cur.users.where(id=1).orderby("id").update(name="x")   # raises
```

The error is raised when the terminal method runs.  Use
`where_raw(...)` or a subquery if you need one of these forms.

## Type adaptation

Value types are adapted by the driver, not by justorm.  The usual
mappings are:

| Python type | PostgreSQL | MySQL        | SQLite    | SQL Server  | Oracle     |
| ----------- | ---------- | ------------ | --------- | ----------- | ---------- |
| `bool`      | `boolean`  | `tinyint(1)` | `integer` | `bit`       | `number(1)` |
| `int`       | `bigint`   | `bigint`     | `integer` | `bigint`    | `number`   |
| `float`     | `double precision` | `double` | `real` | `float` | `binary_double` |
| `str`       | `text`     | `text`       | `text`    | `nvarchar`  | `varchar2` |
| `bytes`     | `bytea`    | `blob`       | `blob`    | `varbinary` | `raw`      |
| `datetime`  | `timestamp`| `datetime`   | (text)    | `datetime2` | `timestamp` |
| `Decimal`   | `numeric`  | `decimal`    | (text)    | `decimal`   | `number`   |
| `dict`      | `jsonb`    | `json`       | (text)    | `nvarchar`  | `varchar2` |
| `list` / `tuple` | `array` | (json)    | (text)    | (json)      | (json)     |

Because values are always passed as parameters, justorm does not need
to know any of this.  What it does mean is that a value that is fine
on one dialect may fail on another.  For example:

```python
cur.users.where(tags=["a", "b"]).select()
# PostgreSQL: WHERE "tags" = ARRAY['a','b']
# MySQL:      an error, arrays are not a value type
# Oracle:     an error, same reason
```

## Detecting the dialect

The dialect is determined by which cursor class you instantiate.  There
is no runtime detection and no `dialect=` argument: you import the
module for your driver and use its `Cursor`.

If you need to branch in your own code, use the renderer attribute:

```python
if cur.dialect_name == "postgresql":
    ...
```

`dialect_name` is set by each renderer (`"postgresql"`, `"mysql"`,
`"sqlite"`, `"pymssql"`, `"oracledb"`).  It is intended for logging
and diagnostics; application logic should generally not need it, since
the dialect is known at the import site.

## Version notes

* SQLite `RETURNING`: 3.35.0 (2021-03-12).
* SQLite `ON CONFLICT`: 3.24.0 (2018-06-04).
* SQLite `OFFSET` without `LIMIT`: 3.30.0 (2019-10-04).
* MySQL `FOR SHARE`: 8.0.1.
* MySQL row alias in `ON DUPLICATE KEY UPDATE`: 8.0.19+.
* SQL Server `OFFSET ... FETCH`: 2012.
* Oracle `OFFSET ... FETCH`: 12c.

justorm does not query server versions.  If you use a feature the
server does not have, the error will come from the server, not from
justorm.  This is consistent with the "schemaless, raise at the last
possible moment" philosophy.
