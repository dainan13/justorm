# JOIN

justorm's join support is deliberately small.  It covers the joins
people actually write — inner, left, right, full, cross — and it
requires you to say what you mean, rather than guessing from a `where`
clause.

A join is built by starting from a primary table and chaining `.join`
(and its aliases) onto it:

```python
cur.users.join(cur.orders, on=cur.users["id"] == cur.orders["user_id"]).select()
```

```sql
SELECT * FROM "users"
JOIN "orders" ON "users"."id" = "orders"."user_id"
```

This page describes the pieces, the rules, and the things justorm
deliberately does not do.

## The shape of a join

Every join has three parts:

1. **A right-hand side** — a table (or an aliased table, or an aliased
   subquery).  This is the first positional argument to `.join(...)`.
2. **A condition** — either `on=<condition>` or `using=<columns>`.
   Exactly one of the two, except for cross joins.
3. **A type** — inner (default), left, right, full, or cross.

```python
cur.users.join(
    cur.orders,                              # right-hand side
    on=cur.users["id"] == cur.orders["user_id"],  # condition
    how="left",                              # type
)
```

The same join may be written with the convenience method for the type:

```python
cur.users.left_join(cur.orders, on=cur.users["id"] == cur.orders["user_id"])
```

Mixing `how=` with a typed method (`left_join(..., how="right")`) is an
error.

## Conditions: `on=` versus `using=`

`on=` takes a [`Condition`](expr.md#conditions) — anything that
comparison operators on expressions produce:

```python
cur.users.join(cur.orders, on=cur.users["id"] == cur.orders["user_id"])
cur.users.join(cur.orders, on=(cur.users["id"] == cur.orders["user_id"])
                                & (cur.orders["paid"] == True))
```

`using=` takes a sequence of column names that both sides share:

```python
cur.users.join(cur.orders, using=("user_id",))
```

```sql
JOIN "orders" USING ("user_id")
```

The two are mutually exclusive.  Passing both, or neither, on a
non-cross join, is an error:

```python
cur.users.join(cur.orders)                                   # error
cur.users.join(cur.orders, on=..., using=("user_id",))       # error
```

`using` is convenient when the columns really do have the same name on
both sides.  If they do not, use `on`:

```python
cur.users.join(cur.orders, on=cur.users["id"] == cur.orders["buyer_id"])
```

## Join types

The `how` argument accepts five values:

| `how`     | SQL            |
| --------- | -------------- |
| `"inner"` | `JOIN`         |
| `"left"`  | `LEFT JOIN`    |
| `"right"` | `RIGHT JOIN`   |
| `"full"`  | `FULL JOIN`    |
| `"cross"` | `CROSS JOIN`   |

`"inner"` is the default.

The convenience methods are:

```python
cur.users.inner_join(cur.orders, on=...)
cur.users.left_join(cur.orders, on=...)
cur.users.right_join(cur.orders, on=...)
cur.users.full_join(cur.orders, on=...)
cur.users.cross_join(cur.orders)
```

SQLite does not have `RIGHT JOIN` or `FULL JOIN` before version 3.39.
justorm passes the join through unchanged, so the error comes from
SQLite itself at execution time.

SQL Server supports `LEFT JOIN`, `RIGHT JOIN`, `FULL JOIN`,
`CROSS JOIN`, and `INNER JOIN`.  All are available.

Oracle supports all of them.

## Cross joins

A cross join has no condition:

```python
cur.users.cross_join(cur.regions).select()
```

```sql
SELECT * FROM "users" CROSS JOIN "regions"
```

Passing `on=` or `using=` to a cross join is an error.

## Multiple joins

Joins are chained.  Each `.join(...)` appends to the previous one:

```python
cur.users \
    .join(cur.orders, on=cur.users["id"] == cur.orders["user_id"]) \
    .join(cur.order_items, on=cur.orders["id"] == cur.order_items["order_id"]) \
    .select()
```

```sql
SELECT * FROM "users"
JOIN "orders" ON "users"."id" = "orders"."user_id"
JOIN "order_items" ON "orders"."id" = "order_items"."order_id"
```

Joins are left-associative and no parentheses are emitted.  If you
need to change the grouping — rare in practice — use `where_raw` or a
subquery.

## Aliases

The primary table can be aliased with `.as_`:

```python
u = cur.users.as_("u")
o = cur.orders.as_("o")
u.join(o, on=u["id"] == o["user_id"]).select()
```

```sql
SELECT * FROM "users" AS "u"
JOIN "orders" AS "o" ON "u"."id" = "o"."user_id"
```

`u` and `o` are builders, not strings.  `u["id"]` produces a
`ColumnExpr` that renders as `"u"."id"`.  Without the alias, the same
expression would render as `"users"."id"`.

Aliases are mostly useful when:

* The same table appears twice in one query.
* You want shorter column references.
* You are joining a subquery (see below).

### Aliasing the right-hand side without aliasing the primary table

You can alias either side independently:

```python
cur.users.join(cur.orders.as_("o"), on=cur.users["id"] == cur.orders["id"])
```

Here `cur.users` keeps its name, and `cur.orders.as_("o")` is used only
for the join target.  The condition must reference the aliased
expression:

```python
o = cur.orders.as_("o")
cur.users.join(o, on=cur.users["id"] == o["user_id"])
```

Otherwise, `cur.users["id"] == cur.orders["id"]` would produce a
reference to the *unaliased* `orders`, which is not in scope.

### Alias reuse

Aliases are just names.  Reusing one is your problem:

```python
a = cur.users.as_("t")
b = cur.orders.as_("t")     # wrong; you have two "t"s
```

justorm does not detect this.  The database will complain.

## Subqueries as join targets

A subquery is produced by `.select_subquery(...)`:

```python
sub = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"})
```

A subquery **must** be aliased before it can be joined:

```python
s = sub.as_("s")
cur.users.join(s, on=cur.users["id"] == s["user_id"]).select()
```

```sql
SELECT * FROM "users"
JOIN (SELECT "user_id" FROM "orders" WHERE "total" > %s) AS "s"
     ON "users"."id" = "s"."user_id"
```

See [Subqueries](subquery.md) for more.

## Subqueries as the primary table

A subquery can also be the starting point:

```python
s = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"}).as_("s")
s.join(cur.users, on=s["user_id"] == cur.users["id"]).select()
```

```sql
SELECT * FROM (SELECT "user_id" FROM "orders" WHERE "total" > %s) AS "s"
JOIN "users" ON "s"."user_id" = "users"."id"
```

## `WHERE` after a join

`.where(...)` works the same after a join as before, but you now have
to worry about ambiguity.  A column name that appears in more than one
of the joined tables must be qualified:

```python
# Ambiguous if both "users" and "orders" have an "id" column
cur.users.join(cur.orders, on=...).where(id=1)

# Unambiguous
cur.users.join(cur.orders, on=...).where(cur.users["id"] == 1)
```

justorm does **not** try to detect this.  The error comes from the
database.  This is consistent with the "schemaless, trust the server"
philosophy.

Keyword arguments to `.where(...)` are always quoted as bare
identifiers, so they cannot carry a table prefix:

```python
cur.users.join(...).where(id=1)       # "id" = %s   — ambiguous
cur.users.join(...).where(cur.users["id"] == 1)   # "users"."id" = %s
```

## `select` after a join

Column references in `select` work the same way.  The `set` / `list` /
`tuple` forms accept either plain strings (bare column names) or
`ColumnExpr` objects (qualified references):

```python
cur.users.join(cur.orders, on=...).select({cur.users["name"], cur.orders["total"]})
cur.users.join(cur.orders, on=...).select({"name", "total"})    # ambiguous if both exist
```

## `ORDER BY` after a join

Same rules:

```python
cur.users.join(cur.orders, on=...).orderby(cur.users["name"]).select()
cur.users.join(cur.orders, on=...).orderby("name").select()
```

## `JOIN` with `for_update`

On PostgreSQL, `SELECT ... FOR UPDATE` normally locks every table in
the `FROM` clause.  To lock only one of them, the `FOR UPDATE OF
table` form is used.  justorm does **not** support `OF`; if you need
it, use `where_raw`:

```python
cur.users.join(cur.orders, on=...).where_raw("1=1").select(for_update=True)
# use where_raw to append "FOR UPDATE OF users" if needed
```

This is a deliberate omission.  `FOR UPDATE OF` is rare, and justorm
prefers to leave the escape hatch open rather than build a partial
abstraction.

## What is not supported

justorm does not provide:

* **LATERAL joins.**  Use `where_raw` if you need one.
* **NATURAL joins.**  Use `using=...` or `on=...`; the meaning of
  `NATURAL` depends on the schema, which justorm does not know.
* **`FULL OUTER JOIN` spelled differently.**  `how="full"` emits
  `FULL JOIN`, which PostgreSQL, SQLite, SQL Server, and Oracle
  understand as `FULL OUTER JOIN`.  MySQL does not have either; the
  error comes from MySQL.
* **Comma joins** (`FROM a, b`).  Use `cross_join` or an explicit
  `on`; the comma form has been considered harmful for two decades.
* **Join hints** (`/*+ ... */`).  Use `where_raw` or `cur[...]`.
* **Parenthesised join groups** that change the associativity.  The
  emitted SQL is always left-associative and unparenthesised.

The pattern here is: justorm covers what you would write by hand most
of the time, and leaves the escape hatches open for the rest.

## Common patterns

### Count rows in a related table

```python
o = cur.orders.as_("o")
cur.users.left_join(o, on=cur.users["id"] == o["user_id"]) \
    .select({cur.users["id"], cur["count(o.id) AS n"]})
```

`group_by` is not part of justorm; use `where_raw` for that, or
`select` the aggregate with a plain `Expr`:

```python
cur.users.left_join(o, on=...).select({cur.users["id"], cur["count(o.id) AS n"]})
```

### Filter on the right-hand side

Filters that belong to the right-hand side go into the `on` condition,
not into `.where(...)`, if you want left-join semantics to be
preserved:

```python
# Keeps users with no matching order (LEFT JOIN semantics)
cur.users.left_join(cur.orders, on=(cur.users["id"] == cur.orders["user_id"])
                                    & (cur.orders["paid"] == True))

# Drops users with no matching order
cur.users.left_join(cur.orders, on=cur.users["id"] == cur.orders["user_id"]) \
    .where(cur.orders["paid"] == True)
```

This is standard SQL semantics; justorm does not change it.

### Self join

```python
m = cur.users.as_("m")
e = cur.users.as_("e")
m.join(e, on=m["manager_id"] == e["id"]).select({m["name"], e["name"]})
```

## See also

* [API reference](api.md#tablebuilder--join) for method signatures.
* [Subqueries](subquery.md) for `select_subquery` and `.as_`.
* [Expressions](expr.md) for `ColumnExpr` and `Condition`.
* [Dialects](dialects.md) for per-database notes on `FOR UPDATE`,
  `RIGHT JOIN`, and friends.
