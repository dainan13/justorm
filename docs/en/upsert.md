# UPSERT

An *upsert* is "insert this row, but if it already exists, do
something else instead".  Every database justorm talks to has an
upsert, but they spell it differently, and justorm exposes each
spelling rather than hiding the differences.

* PostgreSQL: `INSERT ... ON CONFLICT ... DO NOTHING | DO UPDATE ...`
* SQLite: `INSERT ... ON CONFLICT ... DO NOTHING | DO UPDATE ...`
  (similar to PostgreSQL, but with a smaller grammar)
* MySQL: `INSERT ... ON DUPLICATE KEY UPDATE ...`
* SQL Server / Oracle: **not supported**; both use `MERGE`

This page covers the first two.  For a side-by-side table see
[Dialects](dialects.md#upsert).

## PostgreSQL and SQLite: `on_conflict`

The builder surface is:

```python
cur.users.on_conflict(
    on = <optional conflict target>,
    do = <required action>,
).append(...)
```

`on` is optional; `do` is required.  A call to `on_conflict` without
`do` raises `JustormTypeError` when the builder is constructed — there
is no reasonable default, and justorm refuses to guess.

### `do=cur.sql.nothing()`

The simplest form: do nothing on conflict.

```python
cur.users.on_conflict(do=cur.sql.nothing()).append(id=1, name="Alice")
```

```sql
INSERT INTO "users" ("id", "name")
VALUES (%s, %s)
ON CONFLICT DO NOTHING
```

`cur.sql.nothing()` is a terminal builder.  It cannot be followed by
`.where(...)`; `DO NOTHING` has no condition.

### `on=cur.sql.columns(...)`

Target a specific set of columns.  This is the form most people want:
it fires only when the named columns collide with an existing unique
index.

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.nothing(),
).append(id=1, name="Alice")
```

```sql
INSERT INTO "users" ("id", "name")
VALUES (%s, %s)
ON CONFLICT ("id") DO NOTHING
```

Multiple columns are allowed, and are emitted in the order you give:

```python
cur.users.on_conflict(
    on=cur.sql.columns("tenant_id", "email"),
    do=cur.sql.nothing(),
).append(tenant_id=1, email="a@example.com", name="Alice")
```

```sql
ON CONFLICT ("tenant_id", "email") DO NOTHING
```

### `do=cur.sql.update(...)`

`DO UPDATE SET ...`.  The keyword arguments are the assignments; the
values may be plain Python values (bound as parameters) or
expressions.

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(id=1, name="Alice")
```

```sql
ON CONFLICT ("id") DO UPDATE SET "name" = EXCLUDED.name
```

`EXCLUDED.<col>` refers to the row that *would have been inserted*.
It is written as an `Expr` because justorm does not special-case it:

```python
cur["EXCLUDED.name"]         # PostgreSQL / SQLite
```

The name `EXCLUDED` is a PostgreSQL / SQLite keyword; justorm passes
it through verbatim.  It is up to you to spell it in the case your
database expects.  PostgreSQL folds unquoted identifiers to lower
case, so `EXCLUDED.name` is the usual spelling.

Plain values are also fine:

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(seen=0, updated_at=cur["now()"]),
).append(id=1, name="Alice")
```

```sql
ON CONFLICT ("id") DO UPDATE SET "seen" = %s, "updated_at" = now()
```

### `do=cur.sql.where(...).update(...)`

Add a `WHERE` clause to the update, so that the conflict only updates
rows that satisfy the condition:

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.where(cur["users.updated_at < now()"]).update(
        name=cur["EXCLUDED.name"],
    ),
).append(id=1, name="Alice")
```

```sql
ON CONFLICT ("id") DO UPDATE SET "name" = EXCLUDED.name
WHERE users.updated_at < now()
```

Notice the ordering: the `where` is chained **before** `.update(...)`,
not after.  `cur.sql.where(...)` alone is an incomplete builder; it
must be terminated by `.update(...)`.  The reverse — `.update(...)`
followed by `.where(...)` — is not supported, because the terminal
action is always the last thing you write.

### `on=cur.sql.constraint(...)` — PostgreSQL only

Target a named constraint instead of a column set:

```python
cur.users.on_conflict(
    on=cur.sql.constraint("users_pkey"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(id=1, name="Alice")
```

```sql
ON CONFLICT ON CONSTRAINT users_pkey DO UPDATE SET "name" = EXCLUDED.name
```

SQLite has no equivalent: `ON CONFLICT ON CONSTRAINT` requires a
*constraint* name, and SQLite's `ON CONFLICT` only accepts column
lists.  The call is accepted by the builder and rejected by the
renderer at the last possible moment:

```python
cur.users.on_conflict(
    on=cur.sql.constraint("users_pkey"),
    do=cur.sql.nothing(),
).append(id=1, name="Alice")
# JustormDialectError: SQLite does not support ON CONFLICT ON CONSTRAINT
```

### `on=cur.sql.where(...).columns(...)` — PostgreSQL only

The "index predicate" form, used together with partial unique indexes:

```sql
CREATE UNIQUE INDEX users_email_active
    ON users (email) WHERE deleted_at IS NULL;
```

```python
cur.users.on_conflict(
    on=cur.sql.where(cur["deleted_at IS NULL"]).columns("email"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(email="a@example.com", name="Alice")
```

```sql
ON CONFLICT ("email") WHERE deleted_at IS NULL
DO UPDATE SET "name" = EXCLUDED.name
```

The `WHERE` here is an *index predicate*: it matches the predicate of a
partial index, not a row filter.  It is **not** the same as the
`WHERE` that can follow `DO UPDATE SET`.  A statement can have both:

```python
cur.users.on_conflict(
    on=cur.sql.where(cur["deleted_at IS NULL"]).columns("email"),
    do=cur.sql.where(cur["users.updated_at < now()"]).update(
        name=cur["EXCLUDED.name"],
    ),
).append(email="a@example.com", name="Alice")
```

```sql
ON CONFLICT ("email") WHERE deleted_at IS NULL
DO UPDATE SET "name" = EXCLUDED.name
WHERE users.updated_at < now()
```

SQLite does not support partial-index predicates in `ON CONFLICT`, so
this form is rejected at the last possible moment.

### Combining with `insert` and `insert_many`

`on_conflict` works with all three insertion methods:

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).insert([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])
```

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.nothing(),
).insert_many(rows, columns=["id", "name"])
```

For `insert` (single statement, multiple `VALUES` rows) the conflict
clause applies to the whole statement, which is exactly what
PostgreSQL and SQLite expect.  For `insert_many` (one `execute` per
row) the clause applies to each row independently.

### Combining with `returning`

`returning` and `on_conflict` may appear in either order:

```python
cur.users.returning("id").on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(id=1, name="Alice")

cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).returning("id").append(id=1, name="Alice")
```

Both produce the same statement.  The result follows the usual
`returning` rules (see [API reference](api.md#tablebuilder--insert)).

## MySQL: `on_duplicate`

MySQL's upsert has a different shape.  There is no conflict target —
the clause fires on *any* duplicate key — and there is no
`DO NOTHING`.  The builder reflects this:

```python
cur.users.on_duplicate(update={"name": cur["VALUES(name)"]}).append(
    id=1, name="Alice",
)
```

```sql
INSERT INTO `users` (`id`, `name`)
VALUES (%s, %s)
ON DUPLICATE KEY UPDATE `name` = VALUES(name)
```

### Assignments

The `update` argument is a mapping of column name to value.  Values may
be plain Python values (bound as parameters) or expressions:

```python
cur.users.on_duplicate(update={"seen": 0, "name": cur["VALUES(name)"]}).append(...)
```

```sql
ON DUPLICATE KEY UPDATE `seen` = %s, `name` = VALUES(name)
```

The `VALUES(col)` function refers to the value that would have been
inserted for `col`.  It is written as an `Expr` because justorm does
not special-case it.

MySQL 8.0.19 and later deprecate `VALUES(col)` in favour of a row
alias:

```python
cur.users.on_duplicate(update={"name": cur["new.name"]}).append(...)
```

justorm does not add the alias for you; if you want the new form,
write it yourself.  Both spellings are just strings inside an `Expr`
from justorm's point of view.

### No `DO NOTHING`

MySQL has no `DO NOTHING`.  If you want "insert or ignore", use
`INSERT IGNORE` — which justorm does not model — or update a column to
itself:

```python
cur.users.on_duplicate(update={"id": cur["id"]}).append(id=1, name="Alice")
```

### Combining with `insert` / `insert_many`

`on_duplicate` works with `append`, `insert`, and `insert_many`, just
like `on_conflict`:

```python
cur.users.on_duplicate(update={"seen": 0}).insert(
    [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
)
```

### Combining with `returning`

MySQL does not support `RETURNING`, so combining `on_duplicate` with
`.returning(...)` raises `JustormDialectError` when the terminal method
runs.  The `on_duplicate` clause itself is fine; it is the
`RETURNING` that MySQL rejects.

## SQL Server / Oracle: neither is supported

Both use `MERGE`:

```sql
MERGE INTO users AS t
USING (VALUES (1, 'Alice')) AS s (id, name)
ON t.id = s.id
WHEN MATCHED THEN UPDATE SET name = s.name
WHEN NOT MATCHED THEN INSERT (id, name) VALUES (s.id, s.name);
```

justorm does not model `MERGE`.  Write raw SQL via `cur.query(...)`:

```python
cur.query(
    """
    MERGE INTO users AS t
    USING (VALUES (%s, %s)) AS s (id, name)
    ON t.id = s.id
    WHEN MATCHED THEN UPDATE SET name = s.name
    WHEN NOT MATCHED THEN INSERT (id, name) VALUES (s.id, s.name)
    """,
    [1, "Alice"],
)
```

```python
# Oracle
cur.query(
    """
    MERGE INTO users t
    USING (SELECT :p1 AS id, :p2 AS name FROM dual) s
    ON (t.id = s.id)
    WHEN MATCHED THEN UPDATE SET t.name = s.name
    WHEN NOT MATCHED THEN INSERT (t.id, t.name) VALUES (s.id, s.name)
    """,
    {"p1": 1, "p2": "Alice"},
)
```

## Cross-dialect mistakes

Using a PostgreSQL / SQLite upsert on MySQL, or vice versa, is
rejected at the last possible moment:

```python
cur.users.on_conflict(do=cur.sql.nothing()).append(id=1)
# PostgreSQL / SQLite: fine
# MySQL: JustormDialectError when append() runs
```

```python
cur.users.on_duplicate(update={"name": "x"}).append(id=1)
# MySQL: fine
# PostgreSQL / SQLite: JustormDialectError when append() runs
```

The rationale is that the *shape* of the call depends on the dialect,
so it makes no sense to fail early: a user writing dialect-portable
code will guard the call themselves.

## Notes on `cur.sql`

`cur.sql` is a small namespace that exists only for `on_conflict`.
It has four/five entry points:

| Call                            | Produces                                    |
| ------------------------------- | ------------------------------------------- |
| `cur.sql.nothing()`             | the `DO NOTHING` action                     |
| `cur.sql.update(**kwargs)`      | the `DO UPDATE SET ...` action              |
| `cur.sql.columns(*names)`       | an `ON CONFLICT ( ... )` target             |
| `cur.sql.constraint(name)`      | an `ON CONFLICT ON CONSTRAINT name` target  |
| `cur.sql.where(...)`            | an incomplete clause; must be terminated    |

`cur.sql.where(...)` may be followed by either `.columns(...)`
(index-predicate form) or `.update(...)` (update condition).  The two
cannot be mixed on the same `cur.sql.where(...)`:

```python
cur.sql.where(cur["deleted_at IS NULL"]).columns("email")     # target
cur.sql.where(cur["users.updated_at < now()"]).update(...)    # update condition
```

`cur.sql.nothing()` and `cur.sql.columns(...)` and
`cur.sql.constraint(...)` are terminal.  They cannot be followed by
`.where(...)`.

## Summary

| You want...                                  | PostgreSQL / SQLite                                  | MySQL                                            |
| -------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------ |
| insert, ignore on conflict                   | `on_conflict(do=cur.sql.nothing())`                  | `on_duplicate(update={...})` (update a column to itself) |
| insert, update on a specific key             | `on_conflict(on=cur.sql.columns("id"), do=cur.sql.update(...))` | `on_duplicate(update={...})` (any duplicate key) |
| insert, update on a named constraint         | `on_conflict(on=cur.sql.constraint("name"), do=...)` | n/a                                              |
| insert, update only if a condition holds     | `do=cur.sql.where(...).update(...)`                  | not supported; use a trigger or a follow-up      |
| insert, update on a partial-index conflict   | `on=cur.sql.where(...).columns(...)`                 | n/a                                              |
| retrieve inserted / updated rows             | `.returning(...)`                                    | not supported by MySQL                           |

## See also

* [Dialects](dialects.md#upsert) for the side-by-side comparison.
* [API reference](api.md#tablebuilder--upsert) for the method
  signatures.
* [Security](security.md) for the rules about `cur[...]` content.
