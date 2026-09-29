# API reference

This page documents the public surface of justorm.  It is organised by
the object you interact with, rather than alphabetically, because that
is how you will read it.

Throughout this page:

* `cur` is a justorm cursor (a subclass of a DB-API cursor, or a
  wrapper around one — see [Quickstart](quickstart.md)).
* `%s` is the placeholder for PostgreSQL, MySQL, and SQL Server;
  SQLite uses `?`; Oracle uses named placeholders `:p<hex>` (generated
  by the builder).  The examples use `%s` for readability; the exact
  placeholder is dialect-specific and handled for you.
* All identifiers in generated SQL are quoted according to the dialect
  (`"col"` on PostgreSQL, SQLite, and Oracle; `` `col` `` on MySQL;
  `[col]` on SQL Server).  The examples below show PostgreSQL quoting.

## Table of contents

- [Cursor entry points](#cursor-entry-points)
- [Expressions](#expressions)
- [Conditions](#conditions)
- [TableBuilder — SELECT](#tablebuilder--select)
- [TableBuilder — fetching one row](#tablebuilder--fetching-one-row)
- [TableBuilder — INSERT](#tablebuilder--insert)
- [TableBuilder — UPDATE / DELETE](#tablebuilder--update--delete)
- [TableBuilder — JOIN](#tablebuilder--join)
- [TableBuilder — UPSERT](#tablebuilder--upsert)
- [TableBuilder — ordering and pagination](#tablebuilder--ordering-and-pagination)
- [Subqueries](#subqueries)
- [Raw SQL](#raw-sql)
- [Fetch formats](#fetch-formats)
- [Return values](#return-values)
- [Errors](#errors)

---

## Cursor entry points

### `cur.table(name)` / `cur.table(schema, name)` / `cur.table("schema.name")`

Return a [`TableBuilder`](#tablebuilder--select) for the named table.

```python
cur.table("users")              # FROM "users"
cur.table("public", "users")    # FROM "public"."users"
cur.table("public.users")       # same as above
```

At most two parts are allowed.  Three-part names are rejected.

### `cur.<name>`

Attribute access on the cursor is equivalent to `cur.table(name)`,
*except* when the name is already an attribute of the underlying cursor
(for example `execute`, `fetchone`, `description`, `rowcount`).  Those
names keep their native meaning.

```python
cur.users          # TableBuilder for "users"
cur.execute        # the native cursor method
cur.table("order") # use this for names that clash with cursor attributes
```

### `cur["..."]`

Return an [`Expr`](#expressions) wrapping the given SQL fragment.

```python
cur["lower(name)"]         # Expr("lower(name)")
cur["count(*) AS n"]       # Expr("count(*) AS n")
```

The fragment is emitted **verbatim**.  Only four sequences are
rejected at construction time: `;`, `--`, `/*`, `*/`.  See
[Security](security.md).

### `cur.sql`

A namespace for the pieces used by `.on_conflict(...)`.  See
[UPSERT](#tablebuilder--upsert).

---

## Expressions

There are two kinds of expression, and the distinction matters.

### `Expr` — `cur["..."]`

An opaque SQL fragment.  It is emitted unchanged.  You are responsible
for any quoting inside it.

```python
cur["lower(name)"]
cur["now()"]
cur["count(*) AS n"]
```

`Expr` supports the arithmetic and comparison operators.  The value on
the right-hand side is always bound as a parameter, never inlined:

```python
cur["age"] + 1                # (age + %s), [1]
cur["age"] > 18               # Condition: (age > %s), [18]
cur["a"] == cur["b"]          # Condition: (a = b)
```

This is the difference between *safe* and *verbatim*:

```python
cur["age + 1"]                # verbatim: age + 1
cur["age"] + 1                # parameterised: age + %s, [1]
```

Both are useful.  Only the second protects the value from being
inlined.

### `ColumnExpr` — `cur.<table>["col"]`

A column reference.  Unlike `Expr`, the table name and the column name
are both quoted according to the dialect:

```python
cur.users["name"]             # "users"."name"
cur.users["name"] == "Alice"  # Condition: "users"."name" = %s, ["Alice"]
```

`cur.<table>["*"]` is rejected; use `cur["users.*"]` instead.

### `ColumnExpr.as_(alias)`

Rename the column in the result set:

```python
cur.users["name"].as_("n")    # "users"."name" AS "n"
```

The returned object remembers the alias, so the `select` machinery can
name the result column correctly.

---

## Conditions

Conditions are what you pass to `where`, `on`, and a few other places.
They are produced by comparing expressions, and they can be combined.

### Operators on `Expr` / `ColumnExpr`

| Python   | SQL   |
| -------- | ----- |
| `==`     | `=`   |
| `!=`     | `<>`  |
| `<`      | `<`   |
| `<=`     | `<=`  |
| `>`      | `>`   |
| `>=`     | `>=`  |
| `+ - * / %` | arithmetic |

Comparisons where the right-hand side is `None` become `IS NULL` /
`IS NOT NULL`:

```python
cur.users["age"] == None      # "users"."age" IS NULL
cur.users["age"] != None      # "users"."age" IS NOT NULL
```

### Combining conditions

```python
(cur.users["age"] > 18) & (cur.users["active"] == True)   # AND
(cur.users["age"] > 18) | (cur.users["age"] < 5)          # OR
~(cur.users["active"] == True)                            # NOT
```

Because `&` and `|` bind more tightly than comparisons in Python,
**always parenthesise** the operands:

```python
# Wrong: parses as cur["a"] > (1 & cur["b"]) > 2
cur["a"] > 1 & cur["b"] > 2

# Right:
(cur["a"] > 1) & (cur["b"] > 2)
```

### `Condition.params`

The list of parameters the condition will bind, in order.  Mostly
useful when debugging.

---

## TableBuilder — SELECT

A `TableBuilder` is returned by `cur.<table>` and by chained calls like
`.where(...)`, `.join(...)`, and so on.  Every method returns a **new**
builder; nothing is executed until a terminal method is called.

### `select(*args, key=None, key_conflict="error", for_update=False, share=False, skip_locked=False, nowait=False)`

Terminal.  Executes a `SELECT` and returns the rows.

The first positional argument controls the *shape* of the result:

| Argument             | Result                                      |
| -------------------- | ------------------------------------------- |
| *(none)*             | `list[dict]`, all columns                   |
| `set` of names       | `list[dict]`, selected columns              |
| `list` of names      | `list[dict]`, selected columns, ordered     |
| `tuple` of names     | `list[tuple]`                               |
| `str`                | `list[scalar]`, single column               |
| `Expr`               | `list[scalar]`, single expression           |
| `set`/`list` of Expr | `list[dict]`                                |
| `tuple` of Expr      | `list[tuple]`                               |

```python
cur.users.select()                            # [{"id":1,"name":"Alice"}, ...]
cur.users.select({"name"})                    # [{"name":"Alice"}, ...]
cur.users.select(["name", "age"])             # ordered columns
cur.users.select(("id", "name"))              # [(1, "Alice"), ...]
cur.users.select("name")                      # ["Alice", ...]
cur.users.select(cur["count(*)"])             # [3]
cur.users.select({cur.users["name"]})         # [{"name": "Alice"}, ...]
```

When `key=` is given, the result is a dictionary keyed by that column:

```python
cur.users.select("name", key="id")            # {1: "Alice", 2: "Bob"}
cur.users.select(key="id")                    # {1: {"id":1,...}, ...}
```

Duplicate keys are resolved according to `key_conflict`:

* `"error"` (default): raise.
* `"overwrite"`: last value wins.
* a callable `f(old, new)`: merge.

```python
cur.users.select("name", key="id", key_conflict="overwrite")
cur.users.select("name", key="id", key_conflict=lambda a, b: a + "/" + b)
```

`key` values that are `None` are used as dictionary keys as-is, and are
subject to the same `key_conflict` policy.

`select("*")` is rejected; call `select()` with no argument instead.

### `.where(*conditions, **kwargs)`

Append `AND`-combined conditions.

With keyword arguments, the key is a column name and the value is the
right-hand side:

```python
cur.users.where(age=30)                # "age" = %s, [30]
cur.users.where(age=None)              # "age" IS NULL
cur.users.where(age=(1, 2))            # "age" = %s, [(1,2)]   — array / tuple
cur.users.where(name=cur["upper('a')"])  # "name" = upper('a')
```

With positional arguments, each must be a [`Condition`](#conditions):

```python
cur.users.where(cur.users["age"] > 18)
cur.users.where((cur.users["age"] > 18) & (cur.users["active"] == True))
```

Chained calls are combined with `AND`:

```python
cur.users.where(age=30).where(name="Alice")
# ("age" = %s) AND ("name" = %s)
```

Passing both positional conditions and keyword arguments in the same
call is an error.

### `.where_in(mapping=None, **kwargs)`

`IN` conditions.  Either pass a mapping, or use keyword arguments:

```python
cur.users.where_in(id=[1, 2, 3])
cur.users.where_in({"id": [1, 2, 3]})
cur.users.where_in({cur["lower(name)"]: ["alice", "bob"]})
```

An empty iterable produces a condition that is always false:

```python
cur.users.where_in(id=[])              # WHERE FALSE
```

Empty mappings are a no-op (they add nothing to the query).

### `.where_not_in(mapping=None, **kwargs)`

Same as `where_in`, negated.  An empty iterable produces `WHERE TRUE`.

### `.where_between(mapping=None, **kwargs)`

`BETWEEN` conditions.  The values must be a two-element tuple or list:

```python
cur.users.where_between(age=(18, 65))
cur.users.where_between({cur["age"]: (18, 65)})
```

### `.where_is_null(*columns)`

`IS NULL` for one or more columns:

```python
cur.users.where_is_null("deleted_at")
cur.users.where_is_null("deleted_at", "archived_at")
```

### `.where_like(mapping=None, **kwargs)` / `.where_ilike(...)`

`LIKE` (and `ILIKE`, PostgreSQL only) conditions:

```python
cur.users.where_like(name="A%")
cur.users.where_ilike(name="a%")       # PostgreSQL only
```

`ILIKE` is rejected at the last possible moment on MySQL, SQLite,
SQL Server, and Oracle.

### `.where_raw(sql, params=None)`

Append a raw SQL fragment with optional parameters.  This is the escape
hatch for conditions the builder cannot express:

```python
cur.users.where_raw("length(name) > %s", [5])
cur.users.where_raw("EXISTS (SELECT 1 FROM orders WHERE ...)", [])
```

The fragment is emitted verbatim.  Values you pass in `params` are bound
as parameters.

### `.all()`

Marks the builder as "intentionally affecting every row".  Required
before `update` and `delete` will run without a `where` clause.  Has no
effect on `select`.

---

## TableBuilder — fetching one row

### `.get(*args, default=None, **kwargs)`

Return the first row of the query, or `default` (which defaults to
`None`).  The first positional argument follows the same rules as
`select`.

```python
cur.users.where(id=1).get()                # {"id": 1, ...} or None
cur.users.where(id=1).get("name")          # "Alice" or None
cur.users.where(id=1).get(("id", "name"))  # (1, "Alice") or None
cur.users.where(id=999).get(default={})    # {}
```

`key=` is **not** supported (a single row is not something to index by
column value); passing it raises `JustormTypeError`.  Any other
keyword argument is forwarded to `select`, so `for_update=True` and
friends still work.

`get` overrides any previously set `limit`: "give me one row" is the
whole point.

---

## TableBuilder — INSERT

### `.append(row=None, *, columns=None, **kwargs)`

Terminal.  Inserts a **single** row.

```python
cur.users.append(name="Alice", age=30)
cur.users.append({"name": "Alice", "age": 30})
cur.users.append({"name": "Alice"}, age=30)       # merged; kwargs win
cur.users.append(("Alice", 30), columns=["name", "age"])
```

An empty list is a no-op:

```python
cur.users.append([])                              # nothing happens
```

### `.insert(rows, *, columns=None)`

Terminal.  Inserts **many** rows in a single `INSERT ... VALUES (...),
(...), ...` statement.

```python
cur.users.insert([{"name": "A"}, {"name": "B"}])
cur.users.insert([{"name": "A"}, {"name": "B"}], columns=["name"])
cur.users.insert([("A",), ("B",)], columns=["name"])
```

When `columns` is omitted and every row is a dict, justorm scans all
rows for the union of keys (order unspecified).  Missing keys in a
given row produce the `DEFAULT` keyword for that position:

```python
cur.users.insert([{"a": 1, "b": 2}, {"a": 3}])
# INSERT INTO "users" ("a","b") VALUES (%s,%s), (%s,DEFAULT)
```

Extra keys beyond the union are ignored.

An empty list is a no-op.

### `.insert_many(rows, *, columns)`

Terminal.  Uses the driver's `executemany`, one statement per row.

`columns` is **required**, because `rows` may be a lazy iterator:

```python
cur.users.insert_many(
    ((i, f"name{i}") for i in range(100_000)),
    columns=["id", "name"],
)
cur.users.insert_many([{"id": 1, "name": "A"}], columns=["id", "name"])
```

### `.returning(*columns)`

Adds a `RETURNING` clause.  Supported on PostgreSQL (psycopg /
psycopg2) and SQLite 3.35+; **rejected on MySQL, SQL Server, and
Oracle** at the last possible moment.

```python
cur.users.returning("id").append(name="Alice")            # -> 1
cur.users.returning("id", "name").append(name="Alice")    # -> (1, "Alice")
cur.users.returning("id").insert([{"name": "A"}])         # -> [1]
```

The shape of the return value follows the same rules as `select`:

* one column name  → scalar (for `append`) or list of scalars
* many columns     → tuple (for `append`) or list of tuples
* no `returning`   → `None`

`returning` may be called before or after the insert method; it always
applies to the pending statement.

---

## TableBuilder — UPDATE / DELETE

### `.update(row=None, **kwargs)`

Terminal.  Updates rows.

```python
cur.users.where(id=1).update(name="Alice")
cur.users.where(id=1).update({"name": "Alice"})
cur.users.where(id=1).update({"name": "Alice"}, age=30)   # merged
```

`None` values mean `= NULL` (not `IS NULL`), because this is an
assignment:

```python
cur.users.where(id=1).update(deleted_at=None)
# SET "deleted_at" = %s, [None]
```

Calling `update` on a builder with no `where` clause and no `.all()`
raises an error.

### `.delete()`

Terminal.  Deletes rows.

```python
cur.users.where(id=1).delete()
cur.users.all().delete()      # explicit
```

Same guard as `update`: no `where` and no `.all()` is an error.

### Ordering / pagination on UPDATE / DELETE

`LIMIT` and `ORDER BY` are not supported by the builder for `update`
and `delete`.  If you use them, justorm raises an error when the
terminal method runs:

```python
cur.users.where(id=1).orderby("id").update(name="x")     # raises
cur.users.where(id=1).limit(1).delete()                  # raises
```

---

## TableBuilder — JOIN

### `.join(right, *, on=None, using=None, how="inner")`

Append a join.  Exactly one of `on` or `using` must be given (except
for `cross_join`, which takes neither).

```python
o = cur.orders.as_("o")
cur.users.join(o, on=cur.users["id"] == o["user_id"]).select()
cur.users.join(o, using=("id",)).select()
cur.users.join(o, on=..., how="left").select()
```

`how` accepts `"inner"`, `"left"`, `"right"`, `"full"`, `"cross"`.

### `.inner_join` / `.left_join` / `.right_join` / `.full_join` / `.cross_join`

Convenience aliases.  They do not accept a `how=` argument (mixing the
two is an error).

```python
cur.users.left_join(o, on=cur.users["id"] == o["user_id"]).select()
cur.users.cross_join(cur.regions).select()
```

### `.as_(alias)`

Return a builder that refers to the table under a different name:

```python
u = cur.users.as_("u")
o = cur.orders.as_("o")
u.join(o, on=u["id"] == o["user_id"]).select()
# FROM "users" AS "u" JOIN "orders" AS "o" ON "u"."id" = "o"."user_id"
```

---

## TableBuilder — UPSERT

UPSERT is dialect-specific and justorm exposes it as such.

### PostgreSQL / SQLite: `.on_conflict(on=None, do=...)`

```python
# DO NOTHING, no target
cur.users.on_conflict(do=cur.sql.nothing()).append(id=1, name="A")

# DO NOTHING, targeted at a column set
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.nothing(),
).append(id=1, name="A")

# DO UPDATE SET, with EXCLUDED reference
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(id=1, name="A")

# DO UPDATE SET ... WHERE ...
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.where(cur["users.updated_at < now()"]).update(
        name=cur["EXCLUDED.name"]
    ),
).append(id=1, name="A")
```

`cur.sql` provides three/four terminal builders:

* `cur.sql.nothing()` — the `DO NOTHING` action.
* `cur.sql.update(**kwargs)` — the `DO UPDATE SET ...` action.  Chain
  `.where(...)` *before* `.update(...)` to add a condition.
* `cur.sql.columns(*names)` — an `ON CONFLICT ( ... )` target.
* `cur.sql.constraint(name)` — an `ON CONFLICT ON CONSTRAINT name`
  target (PostgreSQL only).
* `cur.sql.where(...).columns(...)` — an `ON CONFLICT ( ... ) WHERE
  ...` target (index predicate, PostgreSQL only).

The `do=` argument is required.  A bare `on_conflict()` with no `do`
raises an error.

`ON CONFLICT ON CONSTRAINT` and the index-predicate form are rejected
by SQLite at the last possible moment.

### MySQL: `.on_duplicate(update)`

```python
cur.users.on_duplicate(update={"name": cur["VALUES(name)"]}).append(
    id=1, name="A",
)
cur.users.on_duplicate(update={"age": 0}).append(id=1, name="A")
```

MySQL 8.0.20+ prefers a row alias; justorm does not add one
automatically, so write it yourself if you need it:

```python
cur.users.on_duplicate(update={"name": cur["new.name"]}).append(
    id=1, name="A",
)
```

`on_conflict` on MySQL and `on_duplicate` on PostgreSQL / SQLite are
both rejected at the last possible moment.

SQL Server and Oracle have neither `on_conflict` nor `on_duplicate` —
they use `MERGE`, which justorm does not model.  Write raw `MERGE`
via `cur.query(...)`.

---

## TableBuilder — ordering and pagination

### `.orderby(*exprs)` / `.orderby_desc(*exprs)`

Append `ORDER BY` terms.

```python
cur.users.orderby("name").select()
cur.users.orderby_desc("age", "name").select()
cur.users.orderby("name").orderby_desc("age").select()
# ORDER BY "name", "age" DESC
```

Terms may be column names (`str`) or expressions (`Expr`,
`ColumnExpr`):

```python
cur.users.orderby(cur["length(name) DESC"]).select()
cur.users.orderby(cur.users["name"]).select()
```

Order terms are appended, not replaced.

### `.limit(n)` / `.offset(n)`

```python
cur.users.limit(10).select()
cur.users.limit(10).offset(20).select()
```

`limit` and `offset` *replace* any previous value.  Both are emitted
with literal integers, not placeholders.

On MySQL, `offset` without `limit` is an error (matching MySQL's own
grammar).  The error is raised when the terminal method runs.

On SQL Server and Oracle they map to `OFFSET n ROWS FETCH NEXT m ROWS
ONLY`.  SQL Server requires an `ORDER BY` for this to be legal — add
one yourself.

### `.distinct()` / `.distinct_on(*columns)`

```python
cur.users.distinct().select()
cur.users.distinct_on("name").select()      # PostgreSQL only
```

`distinct_on` is rejected by MySQL, SQLite, SQL Server, and Oracle at
the last possible moment.

### `.select(for_update=False, share=False, skip_locked=False, nowait=False)`

Lock rows.  Supported on PostgreSQL, MySQL, and Oracle; rejected by
SQLite and SQL Server.

```python
cur.users.where(id=1).select(for_update=True)
cur.users.where(id=1).select(for_update=True, skip_locked=True)
cur.users.where(id=1).select(for_update="share")
```

`for_update=True` and `for_update="share"` are equivalent to
`share=False` and `share=True` respectively.  `nowait` and
`skip_locked` are mutually exclusive.

Oracle does not have `FOR SHARE`; the renderer maps `share=True` to
`FOR UPDATE` so the caller's locking intent still holds.

---

## Subqueries

### `.select_subquery(*args)`

Terminal (but non-executing).  Returns a `Subquery` object that can be
used as a join target.

```python
sub = cur.orders.where(total__gt=100).select_subquery({"user_id"})
```

The arguments follow the same rules as `select`, except that the
result is not fetched; the generated SQL is embedded in the enclosing
query.

### `Subquery.as_(alias)`

Subqueries must be aliased before they can be joined:

```python
s = sub.as_("s")
cur.users.join(s, on=cur.users["id"] == s["user_id"]).select()
# JOIN (SELECT "user_id" FROM "orders" WHERE "total" > %s) AS "s"
#      ON "users"."id" = "s"."user_id"
```

`sub.as_("s")["col"]` produces a `ColumnExpr` referring to the
subquery's column.

### Subqueries as the primary table

A subquery alias can also be the primary table:

```python
s = cur.orders.where(total__gt=100).select_subquery({"user_id"}).as_("s")
s.join(cur.users, on=s["user_id"] == cur.users["id"]).select()
```

### Not supported

* Subqueries inside `where` (use `where_raw`).
* `EXISTS` / `IN` subqueries as first-class builder constructs (use
  `where_raw`).

---

## Raw SQL

### `cur.query(sql, params=None)`

Execute raw SQL and shape the result in one call:

```python
cur.query("SELECT * FROM users WHERE id = %s", [1])
# [{"id": 1, "name": "Alice"}, ...]

cur.query("UPDATE users SET active = %s WHERE id = %s", [True, 1])
# 1  (number of affected rows)
```

* If the statement returns a result set (`description` is not None),
  `query` returns `list[dict]`.
* Otherwise it returns an `int`:
  * `UPDATE` / `DELETE` → `rowcount`.
  * Anything else (`INSERT`, `CREATE`, ...) → the driver's *real*
    `lastrowid` when it has one, otherwise `rowcount`.

`params` is passed through to the driver's `execute` unchanged.  Most
drivers expect a list or tuple; python-oracledb accepts a dict for
named placeholders.  justorm does not normalise the type.

### `format=` on `cur.fetch*`

The three `fetch*` methods accept a `format=` keyword:

```python
cur.execute("SELECT id, name FROM users")
cur.fetchone()                   # (1, "Alice")
cur.fetchone(format=dict)        # {"id": 1, "name": "Alice"}
cur.fetchone(format=namedtuple)  # Row(id=1, name="Alice")
cur.fetchmany(50, format=dict)
cur.fetchall(format=namedtuple)
```

Accepted `format` values:

* `None` (the default): return exactly what the driver returned.
* `tuple`: force plain tuples.
* `dict`: build a dict keyed by column name.
* `namedtuple`: build a `namedtuple` whose fields are the column
  names (duplicates renamed to `_0`, `_1`, ... by `rename=True`).

`fetchone` always returns `None` when there are no rows, whatever the
`format` is.

---

## Return values

| Terminal method              | No `returning` | With `returning`      |
| ---------------------------- | -------------- | --------------------- |
| `select()`                   | rows           | —                     |
| `get()`                      | single row / default | —               |
| `select_subquery()`          | `Subquery`     | —                     |
| `append(...)`                | `None`         | scalar / tuple / dict |
| `insert(...)`                | `None`         | `list`                |
| `insert_many(...)`           | `None`         | `list`                |
| `update(...)`                | `None`         | `list`                |
| `delete()`                   | `None`         | `list`                |

For `append`, the value is a single scalar / tuple / dict because at
most one row is inserted.  For the other insert and DML methods, the
value is always a list, because the statement may affect many rows.

The `returning` shape rules are identical to `select`:

```python
cur.users.returning("id").append(...)                 # scalar
cur.users.returning(("id", "name")).append(...)       # tuple
cur.users.returning({"id", "name"}).append(...)       # dict
cur.users.returning("id").insert([...])               # list of scalars
```

`returning` on MySQL, SQL Server, and Oracle is rejected at the last
possible moment.

---

## Errors

All justorm-specific exceptions derive from
`justorm.JustormError`.  The three concrete subclasses are:

| Exception                | Meaning                                                   |
| ------------------------ | --------------------------------------------------------- |
| `JustormTypeError`       | An argument had an unsupported type.                      |
| `JustormValueError`      | An argument had a supported type but an invalid value.    |
| `JustormDialectError`    | The current dialect does not support the requested feature. |

`JustormTypeError` also inherits from `TypeError`, and
`JustormValueError` also inherits from `ValueError`, so code that
catches the built-in exceptions keeps working.

Errors coming from the driver (for example `psycopg.Error`,
`pymysql.err.MySQLError`, `sqlite3.OperationalError`) are **not**
wrapped; they propagate unchanged.

### When errors are raised

justorm follows a "raise at the last possible moment" policy:

* `.returning(...)` on MySQL does not raise.  The statement is built;
  when the terminal method is called, the error is raised.
* `.distinct_on(...)` on MySQL / SQLite / SQL Server / Oracle does not
  raise.  Same rule.
* `.limit(1).delete()` on any dialect does not raise until `delete()`
  runs.

The exceptions are:

* Malformed arguments (wrong type, empty string where a name is
  required, `cur.t["*"]`, ...) raise immediately, because there is no
  reasonable builder state to continue with.
* `cur["..."]` with a forbidden token (`;`, `--`, `/*`, `*/`) raises
  immediately.

---

## What is not in this reference

justorm deliberately does **not** provide:

* Models, sessions, identity maps, relationships, migrations.
* Asynchronous cursors.
* Query caching.
* Connection pooling.
* Schema introspection.
* UPSERT for pymssql / oracledb (use `cur.query(...)` + `MERGE`).

These are the responsibility of the surrounding application or of the
driver.
