# Migration

This page is for code that already runs against a DB-API cursor and
wants to start using justorm without a rewrite.  It assumes you are
comfortable with raw SQL and want to move to the builder gradually,
one statement at a time.

The migration path has three stages:

1. **Adopt the cursor.**  Import a justorm cursor class and use it
   everywhere you already use the driver's cursor.  Nothing else
   changes; `cur.execute` still works.
2. **Rewrite statements one at a time.**  Replace
   `cur.execute("SELECT ...", params)` with the builder form.  Leave
   the rest alone.
3. **Reach for the escape hatch when you need it.**  Some statements
   are not worth migrating.  `where_raw`, `cur["..."]`, and
   `cur.execute` are always available.

There is no stage 4, and no "convert all your code" step.  justorm is
designed so that the rewrite can happen statement by statement,
forever, or not at all.

## Stage 1: adopt the cursor

Before:

```python
import psycopg

conn = psycopg.connect(...)
cur = conn.cursor()
cur.execute("SELECT id, name FROM users WHERE id = %s", [1])
row = cur.fetchone()
```

After:

```python
import psycopg
import justorm.psycopg

conn = psycopg.connect(...)
cur = conn.cursor(justorm.psycopg.Cursor)
cur.execute("SELECT id, name FROM users WHERE id = %s", [1])
row = cur.fetchone()
```

The only change is the cursor class.  Everything else — the `execute`
call, the `%s` placeholder, the `fetchone` — works exactly as before.
This is the whole point of the "mix into the cursor" design: the
cursor *is* a psycopg cursor, so nothing about the existing code has
to change in this step.

For SQLite, the change is slightly different because `sqlite3.Cursor`
cannot be subclassed:

```python
import sqlite3
import justorm.sqlite

conn = sqlite3.connect(...)
cur = justorm.sqlite.Cursor(conn)
cur.execute("SELECT id, name FROM users WHERE id = ?", [1])
row = cur.fetchone()
```

The wrapping is transparent for the DB-API surface.  `execute`,
`fetchone`, `description`, `rowcount`, and the rest all behave as
they did.

You can adopt the cursor in a codebase without using the builder at
all.  That is a fine place to stop if that is all you need.

## Stage 2: rewrite statements one at a time

Once the cursor is in place, each statement can be migrated
independently.  There is no global flag, no session, no "justorm
mode"; a statement either uses the builder or it does not.

### SELECT

Before:

```python
cur.execute(
    "SELECT id, name FROM users WHERE active = %s ORDER BY name LIMIT 10",
    [True],
)
rows = cur.fetchall()
```

After:

```python
rows = cur.users.where(active=True).orderby("name").limit(10).select()
```

The result is the same list of rows the driver returned.  If you
prefer dicts, the builder produces them by default; if you prefer
tuples, pass a tuple to `select`:

```python
rows = cur.users.where(active=True).orderby("name").limit(10).select(("id", "name"))
```

### INSERT

Before:

```python
cur.execute(
    "INSERT INTO users (name, age) VALUES (%s, %s)",
    ["Alice", 30],
)
```

After:

```python
cur.users.append(name="Alice", age=30)
```

For many rows:

Before:

```python
cur.executemany(
    "INSERT INTO users (name, age) VALUES (%s, %s)",
    [("Alice", 30), ("Bob", 25)],
)
```

After:

```python
cur.users.insert_many([("Alice", 30), ("Bob", 25)], columns=["name", "age"])
```

Note the two insertion methods are different:

* `cur.users.insert(rows)` uses a **single** `INSERT ... VALUES
  (...), (...), (...)` statement.  It is the fast one, and it is the
  one to use for bulk loads.
* `cur.users.insert_many(rows, columns=...)` uses the driver's
  `executemany`, one round trip per row.  Use it when the driver or
  the database needs per-row behaviour.

The distinction mirrors the one in the raw SQL, so the migration is
mechanical.

### UPDATE / DELETE

Before:

```python
cur.execute("UPDATE users SET name = %s WHERE id = %s", ["Alice", 1])
cur.execute("DELETE FROM users WHERE id = %s", [1])
```

After:

```python
cur.users.where(id=1).update(name="Alice")
cur.users.where(id=1).delete()
```

The builder refuses to run an `update` or `delete` with no `where`
clause, because a forgotten `where` is a classic way to destroy a
table.  If you really mean "all rows", say so:

```python
cur.users.all().update(active=True)
cur.users.all().delete()
```

The existing raw-SQL form had no such guard; this is one of the few
places where the builder is stricter than the raw API.  If the
strictness is a problem for a particular statement, `cur.execute`
still works.

### Parameters

The builder takes parameters as Python values, in the same places the
raw SQL would have used `%s`:

```python
# before
cur.execute("SELECT * FROM users WHERE name = %s AND age > %s", ["Alice", 18])

# after
cur.users.where(name="Alice").where(cur.users["age"] > 18).select()
```

Values that appear on the right-hand side of a comparison are always
bound as parameters, never inlined.  See [Security](security.md).

### Placeholders

You do not write placeholders in the builder.  If you drop back to
`where_raw` or `cur.execute`, write the placeholder your driver
expects:

* `%s` for psycopg, psycopg2, PyMySQL, and pymssql;
* `?` for sqlite3;
* `:name` for Oracle.

justorm does not translate placeholders.  See
[Dialects](dialects.md#placeholders).

## Stage 3: the escape hatch

Some statements are not worth migrating.  Window functions, recursive
CTEs, `LATERAL`, exotic joins, `INSERT ... SELECT`, `COPY`, `EXPLAIN
ANALYZE` — the builder does not model these, and probably should not.

The escape hatch is always available, in three forms:

### `where_raw` for conditions

```python
cur.users.where_raw("id IN (SELECT user_id FROM orders WHERE total > %s)", [100]).select()
```

The SQL is verbatim, the parameters are bound.  Do not build the
first argument by string concatenation; see [Security](security.md).

### `cur["..."]` for fragments

```python
cur.users.select({
    cur.users["id"],
    cur["row_number() OVER (PARTITION BY team ORDER BY score DESC) AS rank"],
}).select()
```

The fragment is verbatim.  See [Expressions](expr.md) for the
difference between `cur["..."]` and `cur.users["..."]`.

### `cur.execute` for the whole statement

The cursor still has its native `execute` method, and it still
returns what it always returned:

```python
cur.execute("EXPLAIN ANALYZE SELECT * FROM users WHERE id = %s", [1])
plan = cur.fetchall()
```

There is no need to "get out of justorm mode" for this.  The cursor
is a driver cursor first and a builder second.

## Common translation patterns

### One condition

```python
# before
cur.execute("SELECT * FROM users WHERE id = %s", [1])

# after
cur.users.where(id=1).select()
```

### Multiple conditions, AND

```python
# before
cur.execute("SELECT * FROM users WHERE active = %s AND age > %s", [True, 18])

# after
cur.users.where(active=True).where(cur.users["age"] > 18).select()
```

### OR

```python
# before
cur.execute("SELECT * FROM users WHERE age < %s OR age > %s", [5, 65])

# after
cur.users.where((cur.users["age"] < 5) | (cur.users["age"] > 65)).select()
```

Parenthesise the operands; `&` and `|` bind more tightly than
comparisons in Python.  See [Expressions](expr.md#parenthesise).

### `IN`

```python
# before
cur.execute("SELECT * FROM users WHERE id IN (%s, %s, %s)", [1, 2, 3])

# after
cur.users.where_in(id=[1, 2, 3]).select()
```

The number of placeholders is derived from the list length.  Do not
try to spell the list yourself in `where_raw` unless you also build
the placeholder list; the builder does it for you.

### `BETWEEN`

```python
# before
cur.execute("SELECT * FROM users WHERE age BETWEEN %s AND %s", [18, 65])

# after
cur.users.where_between(age=(18, 65)).select()
```

### `LIKE`

```python
# before
cur.execute("SELECT * FROM users WHERE name LIKE %s", ["A%"])

# after
cur.users.where_like(name="A%").select()
```

### `IS NULL`

```python
# before
cur.execute("SELECT * FROM users WHERE deleted_at IS NULL")

# after
cur.users.where(deleted_at=None).select()
# or
cur.users.where_is_null("deleted_at").select()
```

### `ORDER BY` / `LIMIT`

```python
# before
cur.execute("SELECT * FROM users ORDER BY name, age DESC LIMIT 10 OFFSET 20")

# after
cur.users.orderby("name").orderby_desc("age").limit(10).offset(20).select()
```

### `RETURNING`

```python
# before
cur.execute("INSERT INTO users (name) VALUES (%s) RETURNING id", ["Alice"])
new_id = cur.fetchone()[0]

# after
new_id = cur.users.returning("id").append(name="Alice")
```

`RETURNING` is PostgreSQL and SQLite only.  On MySQL, SQL Server, and
Oracle use the driver's own mechanism:

**MySQL**:

```python
cur.users.append(name="Alice")
new_id = cur.execute("SELECT LAST_INSERT_ID()").fetchone()[0]
```

**SQL Server** (`OUTPUT` clause):

```python
cur.query(
    "INSERT INTO users (name) OUTPUT INSERTED.id VALUES (%s)",
    ["Alice"],
)
```

**Oracle** (`RETURNING INTO` with an OUT bind):

```python
var = cur.var(oracledb.NUMBER)
cur.execute(
    "INSERT INTO users (name) VALUES (:p1) RETURNING id INTO :p2",
    {"p1": "Alice", "p2": var},
)
new_id = var.getvalue()
```

### `JOIN`

```python
# before
cur.execute("""
    SELECT u.id, u.name, o.total
    FROM users u
    JOIN orders o ON u.id = o.user_id
    WHERE o.paid = %s
""", [True])

# after
u = cur.users.as_("u")
o = cur.orders.as_("o")
u.join(o, on=u["id"] == o["user_id"]).where(o["paid"] == True).select({
    u["id"], u["name"], o["total"],
})
```

### UPSERT

```python
# before (PostgreSQL)
cur.execute("""
    INSERT INTO users (id, name) VALUES (%s, %s)
    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
""", [1, "Alice"])

# after (PostgreSQL)
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(id=1, name="Alice")
```

```python
# before (MySQL)
cur.execute("""
    INSERT INTO users (id, name) VALUES (%s, %s)
    ON DUPLICATE KEY UPDATE name = VALUES(name)
""", [1, "Alice"])

# after (MySQL)
cur.users.on_duplicate(update={"name": cur["VALUES(name)"]}).append(id=1, name="Alice")
```

See [UPSERT](upsert.md) for the full surface.

## Things that do not translate

The builder intentionally does not cover:

* **DDL.**  `CREATE TABLE`, `ALTER TABLE`, `DROP`, `CREATE INDEX`,
  and friends are not modelled.  Use `cur.execute`.
* **Window functions in `SELECT`.**  Use `cur["..."]` for the
  expression and `select` for the surrounding query.
* **Recursive CTEs.**  Use `cur.execute`.
* **`INSERT ... SELECT`.**  Use `cur.execute`, or run the `SELECT`
  with the builder, collect the rows, and feed them to `insert`.  The
  latter is slower but works.
* **`COPY`.**  Use the driver's `copy` API.
* **`EXPLAIN` / `EXPLAIN ANALYZE`.**  Use `cur.execute`.
* **`LATERAL`, `NATURAL`, comma joins.**  Use `where_raw` or
  `cur.execute`.
* **`UPDATE ... LIMIT`, `DELETE ... LIMIT`.**  Use `where_raw` with a
  subquery, or `cur.execute`.
* **`FOR UPDATE OF table`.**  Use `where_raw`.
* **Transactions.**  Use the driver's transaction API.  justorm does
  not manage transactions.
* **Connection pooling.**  Use the driver's pool, or a third-party
  pool.  justorm does not manage connections.

The pattern is: justorm models the statements you write every day,
and leaves the long tail to `cur.execute`.  That is the whole design.

## A worked migration

Consider this function:

```python
def find_active_users(conn, min_age):
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, age FROM users "
        "WHERE active = %s AND age >= %s "
        "ORDER BY name "
        "LIMIT 100",
        [True, min_age],
    )
    return cur.fetchall()
```

Three stages.

### Adopt the cursor

```python
import justorm.psycopg

def find_active_users(conn, min_age):
    cur = conn.cursor(justorm.psycopg.Cursor)
    cur.execute(
        "SELECT id, name, age FROM users "
        "WHERE active = %s AND age >= %s "
        "ORDER BY name "
        "LIMIT 100",
        [True, min_age],
    )
    return cur.fetchall()
```

Nothing else changes.  If the function is used everywhere, this is
enough.

### Rewrite the statement

```python
import justorm.psycopg

def find_active_users(conn, min_age):
    cur = conn.cursor(justorm.psycopg.Cursor)
    return (
        cur.users
        .where(active=True)
        .where(cur.users["age"] >= min_age)
        .orderby("name")
        .limit(100)
        .select(("id", "name", "age"))
    )
```

The return value is the same list of tuples.  The `where` calls are
combined with `AND`, matching the original.

### If the statement stops being worth it

Suppose the query grows a window function:

```sql
SELECT id, name, age,
       row_number() OVER (PARTITION BY team ORDER BY score DESC) AS rank
FROM users
WHERE active = %s AND age >= %s
ORDER BY name
LIMIT 100
```

The window function is not modelled; use the escape hatch for that
part:

```python
return (
    cur.users
    .where(active=True)
    .where(cur.users["age"] >= min_age)
    .select({
        "id", "name", "age",
        cur["row_number() OVER (PARTITION BY team ORDER BY score DESC) AS rank"],
    })
    .orderby("name")
    .limit(100)
    .select()
)
```

Or, if the whole statement is easier to read as raw SQL, revert to
`cur.execute`.  There is no penalty; the cursor is a driver cursor.

## See also

* [Quickstart](quickstart.md) if you are starting fresh.
* [API reference](api.md) for method signatures.
* [Security](security.md) for the boundaries between safe and unsafe
  input.
* [Dialects](dialects.md) for per-database differences that affect
  the migration.
* [UPSERT](upsert.md), [JOIN](join.md), [Subqueries](subquery.md) for
  the parts most likely to need the escape hatch.
