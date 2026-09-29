# justorm

A lightweight, schemaless SQL builder that mixes into native database
cursors.

```python
import psycopg
import justorm.psycopg

conn = psycopg.connect("postgresql://localhost/mydb")
with conn.cursor(justorm.psycopg.Cursor) as cur:
    rows = cur.users.where(id=1).select()
    cur.users.where(id=1).update(name="Alice")
    cur.users.append(name="Bob")
```

justorm is **not** an ORM in the "hide the database" sense.  There are
no models, no sessions, no identity maps, no migrations.  What it does
is give you a fluent, Pythonic way to *write* SQL against a real
DB-API cursor, while leaving the cursor — and the database it talks
to — fully in charge.

## Design principles

justorm is built around five principles.

### 1. Mix into the cursor, do not replace it

Every driver entry point is a subclass of that driver's native cursor
(SQLite is the exception: it is a wrapper).  The rest of your code —
connection handling, transactions, error handling, `fetchone()` —
keeps working exactly as it did before.  justorm only *adds* methods.

```python
with conn.cursor(justorm.psycopg.Cursor) as cur:
    cur.execute("SELECT 1")            # native psycopg
    cur.users.where(id=1).select()     # justorm
```

### 2. Schemaless by design

justorm does not know your tables, your columns, or your types.  It
never inspects the schema and never validates column names.  If you
write `cur.users.where(nonexistent=1).select()`, the database is the
one that complains.

This keeps the library small, predictable, and free of the "model"
layer that most ORMs force on you.

### 3. Fluent, chainable, immutable

Builders are immutable: every chained call returns a new builder, and
nothing is sent to the database until a terminal method is called.

```python
base = cur.users.where(active=True)   # nothing executed yet
adults = base.where(cur.users["age"] >= 18)
rows = adults.select()                # now it runs
```

### 4. Dialects stay visible

justorm does **not** paper over the differences between PostgreSQL,
MySQL, SQLite, SQL Server, and Oracle.  If you are talking to MySQL,
you write `.on_duplicate(...)`; if you are talking to PostgreSQL, you
write `.on_conflict(...)`.  If a feature does not exist in your
database, justorm raises an error *at the last possible moment*
rather than silently doing something surprising.

This is a deliberate choice.  You know which database you are using.
justorm trusts you to know.

### 5. Escape by default, raw on request

Structured input — keyword arguments, `set` / `list` / `tuple` of
column names, values passed as parameters — is always escaped and
quoted according to the dialect.  When you need to write something the
builder cannot express, you reach for `cur['...']`, which is emitted
verbatim.

```python
cur.users.where(name="a b").select()                  # "name" = %s, ["a b"]
cur.users.where(cur['lower(name)'] == 'a').select()   # lower(name) = %s
```

The first form is safe.  The second form is on you.

## Supported drivers

| Module              | Driver                                                     | Database        |
| ------------------- | ---------------------------------------------------------- | --------------- |
| `justorm.psycopg`   | [psycopg](https://www.psycopg.org/psycopg3/) (v3)          | PostgreSQL      |
| `justorm.psycopg2`  | [psycopg2](https://www.psycopg.org/)                       | PostgreSQL      |
| `justorm.pymysql`   | [PyMySQL](https://pymysql.readthedocs.io/)                 | MySQL / MariaDB |
| `justorm.sqlite`    | `sqlite3` (standard library)                               | SQLite 3        |
| `justorm.pymssql`   | [pymssql](https://pymssql.readthedocs.io/)                 | SQL Server      |
| `justorm.oracledb`  | [python-oracledb](https://python-oracledb.readthedocs.io/) | Oracle          |

Each module is imported on demand, so installing justorm for one
driver does not pull in the others:

```python
import justorm.psycopg    # only imports psycopg
import justorm.pymysql    # only imports pymysql
```

The top-level `import justorm` imports no driver at all.

## A short tour

### SELECT

```python
cur.users.select()                                   # [{"id": 1, "name": "Alice"}, ...]
cur.users.select({"name"})                           # [{"name": "Alice"}, ...]
cur.users.select(("id", "name"))                     # [(1, "Alice"), ...]
cur.users.select("name")                             # ["Alice", ...]
cur.users.where(id=1).select("name", key="id")       # {1: "Alice"}
cur.users.orderby("name").limit(10).select()
cur.users.where(id=1).get()                          # one row as a dict, or None
```

### INSERT

```python
cur.users.append(name="Alice")                        # one row
cur.users.append({"name": "Alice", "age": 30})        # same
cur.users.insert([{"name": "A"}, {"name": "B"}])      # single statement, many rows
cur.users.insert_many(rows, columns=["name"])         # executemany
cur.users.returning("id").append(name="Alice")        # -> 1
```

### UPDATE / DELETE

```python
cur.users.where(id=1).update(name="Alice")
cur.users.where(id=1).delete()
cur.users.all().delete()                              # explicit, required
```

### JOIN

```python
u = cur.users.as_("u")
o = cur.orders.as_("o")
u.join(o, on=u["id"] == o["user_id"]).select()
```

### Subquery

```python
sub = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"})
s = sub.as_("s")
cur.users.join(s, on=cur.users["id"] == s["user_id"]).select()
```

### UPSERT

```python
# PostgreSQL / SQLite
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(id=1, name="Alice")

# MySQL
cur.users.on_duplicate(update={"name": cur["VALUES(name)"]}).append(
    id=1, name="Alice",
)
```

### Raw SQL

```python
# One call to execute and shape the result:
rows = cur.query("SELECT a, b FROM t WHERE c = %s", [1])   # list[dict]
n    = cur.query("UPDATE t SET a = %s WHERE b = %s", [1, 2])  # int

# fetch* also accepts an output format:
cur.execute("SELECT a, b FROM t")
cur.fetchall(format=dict)
cur.fetchone(format=namedtuple)
```

## What justorm is not

- Not a session manager.  You own the connection, the cursor, and the
  transaction.
- Not a schema tool.  There are no models, no migrations, no field
  types.
- Not a dialect abstraction.  Dialect differences are exposed, not
  hidden.
- Not asynchronous.  The current release is synchronous only.

## Where to go next

- [Quickstart](quickstart.md) — a five-minute introduction.
- [API reference](api.md) — every builder method, with examples.
- [Dialects](dialects.md) — what works where, and what does not.
- [Expressions](expr.md) — `cur['...']`, `cur.t['col']`, operators.
- [UPSERT](upsert.md) — `on_conflict` and `on_duplicate`.
- [JOIN](join.md) and [Subqueries](subquery.md).
- [Security](security.md) — what is escaped, what is not, and why.
- [Migration](migration.md) — moving from raw SQL.
