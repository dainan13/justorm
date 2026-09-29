# Quickstart

This page gets you from zero to a working query in about five minutes.
It uses SQLite because it needs no server, but every example works the
same way on PostgreSQL, MySQL, SQL Server, and Oracle — only the
import and the cursor class change.

## Installation

```console
$ pip install justorm[sqlite]
```

`sqlite3` is part of the Python standard library, so the `[sqlite]`
extra installs nothing; it exists only for symmetry with the other
extras:

```console
$ pip install justorm[psycopg]     # PostgreSQL via psycopg (v3)
$ pip install justorm[psycopg2]    # PostgreSQL via psycopg2
$ pip install justorm[pymysql]     # MySQL / MariaDB via PyMySQL
$ pip install justorm[pymssql]     # SQL Server via pymssql
$ pip install justorm[oracledb]    # Oracle via python-oracledb
```

You can also install several at once:

```console
$ pip install justorm[psycopg,psycopg2,pymysql]
```

## Creating a cursor

justorm does not open connections or manage transactions.  You do that
with the driver, exactly as you always have.  The only difference is
that you ask the connection for a justorm cursor.

### SQLite

```python
import sqlite3
import justorm.sqlite

conn = sqlite3.connect(":memory:")
cur = justorm.sqlite.Cursor(conn)
```

`sqlite3.Cursor` is implemented in C and cannot be subclassed, so
justorm wraps it instead of inheriting from it.  This is why the
SQLite entry point takes the connection as its argument, while the
other drivers take the cursor class as an argument to
`conn.cursor(...)`.

### PostgreSQL (psycopg v3)

```python
import psycopg
import justorm.psycopg

conn = psycopg.connect("postgresql://localhost/mydb")
cur = conn.cursor(justorm.psycopg.Cursor)
```

psycopg's `Connection.cursor()` takes the cursor class in the
`cursor_factory` keyword argument (the first positional argument is
the *name* of a server-side cursor, which is a different concept).
You can also set it once at connection time:

```python
conn = psycopg.connect(
    "postgresql://localhost/mydb",
    cursor_factory=justorm.psycopg.Cursor,
)
cur = conn.cursor()
```

### PostgreSQL (psycopg2)

```python
import psycopg2
import justorm.psycopg2

conn = psycopg2.connect("postgresql://localhost/mydb")
cur = conn.cursor(cursor_factory=justorm.psycopg2.Cursor)
```

### MySQL

```python
import pymysql
import justorm.pymysql

conn = pymysql.connect(host="localhost", user="me", database="mydb")
cur = conn.cursor(justorm.pymysql.Cursor)
```

### SQL Server

```python
import pymssql
import justorm.pymssql

conn = pymssql.connect(server="localhost", user="me", database="mydb")
cur = conn.cursor(justorm.pymssql.Cursor)
```

### Oracle

```python
import oracledb
import justorm.oracledb

conn = oracledb.connect(user="me", password="pw", dsn="localhost/mydb")
cur = conn.cursor(justorm.oracledb.Cursor)
```

## Setting up a table

justorm does not create tables, so use plain SQL for that:

```python
cur.execute("""
    CREATE TABLE users (
        id   INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        age  INTEGER
    )
""")
```

Notice that `cur.execute` is still the native driver method.  The
justorm cursor *is* a sqlite3 cursor; it just happens to have more
methods.

## Inserting rows

`append` inserts a single row:

```python
cur.users.append(name="Alice", age=30)
cur.users.append({"name": "Bob", "age": 25})
```

Both forms build the same SQL:

```sql
INSERT INTO "users" ("name", "age") VALUES (%s, %s)
```

`insert` inserts many rows in a single statement:

```python
cur.users.insert([
    {"name": "Carol", "age": 40},
    {"name": "Dave",  "age": 35},
])
```

```sql
INSERT INTO "users" ("name", "age")
VALUES (%s, %s), (%s, %s), (%s, %s)
```

`insert_many` uses `executemany` instead — one round trip per row,
useful when the driver or the database has per-row behaviour:

```python
cur.users.insert_many(
    [{"name": "Eve", "age": 20}, {"name": "Frank", "age": 45}],
    columns=["name", "age"],
)
```

`insert_many` always requires `columns`, because it may be fed a
lazy iterator (a generator, a query result, ...) and justorm does not
want to buffer it in order to discover the column names.

## Selecting rows

The default `select()` returns a list of dictionaries:

```python
rows = cur.users.select()
# [{"id": 1, "name": "Alice", "age": 30}, ...]
```

Add a `where` clause:

```python
rows = cur.users.where(name="Alice").select()
```

`where` accepts keyword arguments, which are combined with `AND`:

```python
rows = cur.users.where(name="Alice", age=30).select()
# WHERE "name" = %s AND "age" = %s
```

Chained `where` calls are also combined with `AND`:

```python
rows = cur.users.where(name="Alice").where(age=30).select()
# WHERE ("name" = %s) AND ("age" = %s)
```

## Choosing what `select` returns

The shape of the result is controlled by the first positional argument
to `select`:

```python
cur.users.select()                 # [{"id": 1, "name": "Alice"}, ...]
cur.users.select({"name"})         # [{"name": "Alice"}, ...]       — set: subset of columns, dicts
cur.users.select(["name"])         # [{"name": "Alice"}, ...]       — list: same, but ordered
cur.users.select(("id", "name"))   # [(1, "Alice"), ...]            — tuple: rows as tuples
cur.users.select("name")           # ["Alice", ...]                 — str: a single column
```

When you pass `key=`, the result becomes a dictionary keyed by that
column:

```python
cur.users.select("name", key="id")     # {1: "Alice", 2: "Bob", ...}
cur.users.select(key="id")             # {1: {"id": 1, "name": "Alice"}, ...}
```

By default, duplicate keys raise an error.  You can choose a different
behaviour:

```python
cur.users.select("name", key="id", key_conflict="overwrite")
cur.users.select("name", key="id", key_conflict=lambda old, new: old + new)
```

## Fetching a single row

`get` is the "give me one row" shortcut:

```python
cur.users.where(id=1).get()                # {"id": 1, ...} or None
cur.users.where(id=1).get("name")          # "Alice" or None
cur.users.where(id=1).get(("id", "name"))  # (1, "Alice") or None
cur.users.where(id=999).get(default={})    # {} when nothing matches
```

Internally it is `.limit(1).select(...)[0]`, except that an empty
result returns `default` instead of raising `IndexError`.

## Updating and deleting

`update` and `delete` refuse to run without a `where` clause, because
a forgotten `where` is the classic way to destroy a table:

```python
cur.users.where(id=1).update(name="Alice Smith")
cur.users.where(id=1).delete()
```

If you really mean "all rows", say so explicitly:

```python
cur.users.all().update(active=True)
cur.users.all().delete()
```

## Ordering and pagination

```python
cur.users.orderby("name").limit(10).select()
cur.users.orderby_desc("age").limit(10).offset(20).select()
cur.users.orderby("name").orderby_desc("age").select()
# ORDER BY "name", "age" DESC
```

## Getting the generated SQL back

Terminal methods execute immediately.  To inspect what is being sent,
wrap the cursor in a logger, or call `repr()` on an intermediate
builder:

```python
b = cur.users.where(id=1)
repr(b)   # '<TableBuilder table=users>'
```

## Running raw SQL

When the builder cannot express your statement, use `query` — one call
to execute and shape the result:

```python
rows = cur.query("SELECT id, name FROM users WHERE age > %s", [18])
# [{"id": 1, "name": "Alice"}, ...]

n = cur.query("UPDATE users SET active = %s WHERE id = %s", [True, 1])
# number of affected rows
```

`query` returns `list[dict]` for `SELECT` and `int` for writes.

## Fetching in a specific shape

The three `fetch*` methods accept a `format=` keyword:

```python
cur.execute("SELECT id, name FROM users")
cur.fetchall()                   # [(1, "Alice"), ...]        — default, tuples
cur.fetchall(format=dict)        # [{"id": 1, "name": "Alice"}, ...]
cur.fetchall(format=namedtuple)  # [Row(id=1, name="Alice"), ...]
cur.fetchall(format=tuple)       # force plain tuples
```

`format=None` (the default) returns exactly what the driver returned.

## Transactions

justorm does not participate in transaction management.  Use the
driver's facilities:

=== "SQLite / DB-API"

    ```python
    conn = sqlite3.connect(":memory:")
    cur = justorm.sqlite.Cursor(conn)
    try:
        cur.users.append(name="Alice")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    ```

=== "psycopg v3"

    ```python
    with conn.transaction():
        cur.users.append(name="Alice")
        cur.orders.append(user_id=cur.users.returning("id").append(name="Bob"))
    ```

## Where to go next

- [API reference](api.md) for the full surface.
- [Dialects](dialects.md) to see what changes between PostgreSQL,
  MySQL, SQLite, SQL Server, and Oracle.
- [Expressions](expr.md) for the escape hatch (`cur['...']`) and the
  operator DSL.
- [Security](security.md) before you put untrusted input anywhere near
  the builder.
