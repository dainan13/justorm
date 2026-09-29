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

**1. Mix into the cursor, do not replace it.**

Every driver entry point is a subclass of that driver's native cursor
(or, for SQLite, a thin wrapper around it).  The rest of your code —
connection handling, transactions, error handling, `fetchone()` —
keeps working exactly as it did before.  justorm only *adds* methods.

```python
with conn.cursor(justorm.psycopg.Cursor) as cur:
    cur.execute("SELECT 1")            # native psycopg
    cur.users.where(id=1).select()     # justorm
```

**2. Schemaless by design.**

justorm does not know your tables, your columns, or your types.  It
never inspects the schema and never validates column names.  If you
write `cur.users.where(nonexistent=1).select()`, the database is the
one that complains.

**3. Fluent, chainable, immutable.**

Builders are immutable: every chained call returns a new builder, and
nothing is sent to the database until a terminal method is called.

```python
base = cur.users.where(active=True)   # nothing executed yet
adults = base.where(cur.users["age"] >= 18)
rows = adults.select()                # now it runs
```

**4. Dialects stay visible.**

justorm does **not** paper over the differences between PostgreSQL,
MySQL, SQLite, SQL Server, and Oracle.  If you are talking to MySQL,
you write `.on_duplicate(...)`; if you are talking to PostgreSQL, you
write `.on_conflict(...)`.  If a feature does not exist in your
database, justorm raises an error at the last possible moment rather
than silently doing something surprising.

**5. Escape by default, raw on request.**

Structured input — keyword arguments, `set` / `list` / `tuple` of
column names, values passed as parameters — is always escaped and
quoted according to the dialect.  When you need to write something the
builder cannot express, reach for `cur['...']`, which is emitted
verbatim.

```python
cur.users.where(name="a b").select()                 # safe
cur.users.where(cur["lower(name)"] == "a").select()  # verbatim; on you
```

## Installation

```console
$ pip install justorm[psycopg]     # PostgreSQL via psycopg (v3)
$ pip install justorm[psycopg2]    # PostgreSQL via psycopg2
$ pip install justorm[pymysql]     # MySQL / MariaDB via PyMySQL
$ pip install justorm[sqlite]      # SQLite (sqlite3 is stdlib)
$ pip install justorm[pymssql]     # SQL Server via pymssql
$ pip install justorm[oracledb]    # Oracle via python-oracledb
$ pip install justorm[all]         # everything
$ pip install justorm[dev]         # plus the test tooling
```

Each driver module imports only its own driver, so installing justorm
for one database does not pull in the others.  The top-level `import
justorm` imports no driver at all.

## Supported drivers

| Module             | Driver                                                              | Database        |
| ------------------ | ------------------------------------------------------------------- | --------------- |
| `justorm.psycopg`  | [psycopg](https://www.psycopg.org/psycopg3/) (v3)                   | PostgreSQL      |
| `justorm.psycopg2` | [psycopg2](https://www.psycopg.org/)                                | PostgreSQL      |
| `justorm.pymysql`  | [PyMySQL](https://pymysql.readthedocs.io/)                          | MySQL / MariaDB |
| `justorm.sqlite`   | `sqlite3` (standard library)                                        | SQLite 3        |
| `justorm.pymssql`  | [pymssql](https://pymssql.readthedocs.io/)                          | SQL Server      |
| `justorm.oracledb` | [python-oracledb](https://python-oracledb.readthedocs.io/)          | Oracle          |

> **Beta drivers.**  `pymssql` and `oracledb` ship with the full API
> surface and pass the unit tests, but have **not** been
> integration-tested against a live SQL Server or Oracle server.
> Treat them as beta until you have verified them in your environment.

## A short tour

### SELECT

```python
cur.users.select()                                   # [{"id": 1, "name": "Alice"}, ...]
cur.users.select({"name"})                           # [{"name": "Alice"}, ...]
cur.users.select(("id", "name"))                     # [(1, "Alice"), ...]
cur.users.select("name")                             # ["Alice", ...]
cur.users.where(id=1).select("name", key="id")       # {1: "Alice"}
cur.users.where(id=1).get()                          # one row as a dict, or None
cur.users.orderby("name").limit(10).select()
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
- Not a connection pool.  Use the driver's pool, or a third-party one.

## Documentation

Full documentation is available in two languages:

- **中文**: [`docs/zh/index.md`](docs/zh/index.md)
- **English**: [`docs/en/index.md`](docs/en/index.md)

The documentation covers:

- Quickstart
- API reference
- Dialects (per-database feature matrix)
- UPSERT
- JOIN
- Subqueries
- Expressions
- Security
- Migration from raw SQL

## Development

The test suite has two layers:

- **Pure tests** (`tests/test_builder.py`, `tests/test_renderer.py`,
  `tests/test_fetch.py`) run everywhere.  They exercise the builder
  and renderer against a fake cursor and do not need a database.
- **Integration tests** (`tests/test_psycopg.py`,
  `tests/test_psycopg2.py`, `tests/test_pymysql.py`,
  `tests/test_sqlite.py`) run against a real database.  They are
  opt-in per driver and skip automatically when the driver or the
  server is not available.
- **Smoke tests** (`tests/test_pymssql.py`, `tests/test_oracledb.py`)
  verify the driver modules import cleanly and expose the expected
  class hierarchy.  They do not open a connection.

To run everything:

```console
$ pip install -e ".[dev,all]"
$ JUSTORM_PG_DSN="postgresql://user:pw@localhost/test" \
  JUSTORM_MYSQL_DSN="mysql://user:pw@localhost/test" \
  pytest
```

SQLite tests always run.  PostgreSQL and MySQL tests skip unless the
corresponding DSN is set in the environment.

A convenience script, `run_tests.py`, runs the full pipeline (build
the wheel, install it, run the tests) and writes a log file:

```console
$ python run_tests.py
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT.  See [LICENSE](LICENSE).
