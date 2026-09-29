# Subqueries

A subquery is a `SELECT` used as a value in another statement.  justorm
supports subqueries in one specific place: as the **source of a
`FROM` clause**, i.e. as a table you can join to or start from.

Subqueries in other positions — inside `WHERE`, as the right-hand side
of `IN`, as the argument to `EXISTS` — are **not** part of the builder.
Use [`where_raw`](api.md#where_rawsql-paramsnone) for those; see
[Not supported](#not-supported) below.

## Creating a subquery

A subquery is built by calling `.select_subquery(...)` on a
`TableBuilder` instead of `.select()`:

```python
sub = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"})
```

`.select_subquery(...)` is a terminal method: it ends the builder
chain.  Unlike `.select()`, however, it does **not** execute anything.
It returns a `Subquery` object that holds the generated SQL and can be
embedded in an enclosing query.

The arguments are the same as for `select` — they decide which columns
the subquery exposes:

```python
cur.orders.select_subquery()                    # SELECT *
cur.orders.select_subquery({"user_id"})         # SELECT "user_id"
cur.orders.select_subquery(["user_id", "total"])  # ordered columns
cur.orders.select_subquery(("user_id", "total"))  # ordered, tuples not needed here
```

The return-shape arguments of `select` (`set` vs `list` vs `tuple` vs
`str`) only affect how the subquery's columns are named in metadata.
Since the subquery is not fetched, the only thing that matters is the
list of column expressions and their output names.

## Aliasing a subquery

Every subquery used in a `FROM` clause **must** have an alias.  In
PostgreSQL, SQL Server, and Oracle, an unaliased subquery in `FROM` is
a syntax error; SQLite and MySQL accept it but the reference is
awkward.  justorm requires an alias uniformly:

```python
s = sub.as_("s")
```

`.as_` returns a new object — an alias — that can be used:

* as the right-hand side of a `JOIN`,
* as the primary table of a query,
* as a source of `ColumnExpr`s via `s["col"]`.

Calling `.as_` is idempotent in the sense that a fresh alias is
returned each time; the original `sub` is unchanged.

## Joining a subquery

```python
sub = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"})
s = sub.as_("s")

cur.users.join(s, on=cur.users["id"] == s["user_id"]).select()
```

```sql
SELECT * FROM "users"
JOIN (
    SELECT "user_id" FROM "orders" WHERE "total" > %s
) AS "s" ON "users"."id" = "s"."user_id"
```

`s["user_id"]` is a `ColumnExpr` whose table is the alias `"s"`.  It
renders as `"s"."user_id"` (or `` `s`.`user_id` `` on MySQL, or
`[s].[user_id]` on SQL Server).

The usual join rules apply: see [JOIN](join.md) for `on=` vs `using=`,
join types, and the left-join filter pattern.

## Using a subquery as the primary table

An alias can also be the starting point of a query:

```python
s = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"}).as_("s")
s.join(cur.users, on=s["user_id"] == cur.users["id"]).select()
```

```sql
SELECT * FROM (
    SELECT "user_id" FROM "orders" WHERE "total" > %s
) AS "s"
JOIN "users" ON "s"."user_id" = "users"."id"
```

The alias object supports the same surface as a `TableBuilder`: `.join`,
`.left_join`, `.where`, `.orderby`, `.limit`, `.select`, and so on.
The only difference is the primary table, which is a parenthesised
`SELECT` rather than a table name.

## Selecting from a subquery without joining

If you only want to select from the subquery, the primary-table form
is enough:

```python
s = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"}).as_("s")
s.select()
```

```sql
SELECT * FROM (SELECT "user_id" FROM "orders" WHERE "total" > %s) AS "s"
```

## Nesting

Subqueries nest naturally, because each `.select_subquery()` call
starts a fresh builder:

```python
inner = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"})

mid = cur.users.where(cur.users["active"] == True).select_subquery({"id"})

s_inner = inner.as_("i")
s_mid = mid.as_("m")

cur.regions \
    .join(s_inner, on=...)
    .join(s_mid, on=...)
    .select()
```

The depth is limited only by the database's own limits.

## Column naming inside a subquery

Column references inside the subquery follow the same rules as
elsewhere: `cur.orders["total"]` renders as `"orders"."total"` when
used inside the subquery.  If the subquery's `FROM` is itself aliased,
the reference must use the alias:

```python
o = cur.orders.as_("o")
sub = o.where(o["total"] > 100).select_subquery({"user_id"})
```

Inside `sub`, the column is `"o"."total"`, not `"orders"."total"`.

## The result shape of a subquery

`.select_subquery()` does not fetch rows, so the return-shape
arguments of `select` (`set` vs `tuple` vs `str`, and `key=`) are not
meaningful and are ignored.  Only the choice of columns matters.

Passing `key=` to `select_subquery` is allowed but has no effect; the
call is not rejected because the same argument is meaningful in
`.select()`, and it is convenient to write code that constructs a
subquery and a query with the same helper.

## Limitations

### Subqueries in `WHERE`

Not supported as first-class builder constructs.  Use `where_raw`:

```python
cur.users.where_raw(
    "EXISTS (SELECT 1 FROM orders o WHERE o.user_id = users.id)",
    [],
)
```

```python
cur.users.where_raw(
    "id IN (SELECT user_id FROM orders WHERE total > %s)",
    [100],
)
```

`where_raw` does not translate placeholders, so write the one your
driver expects (`%s` on PostgreSQL, MySQL, and SQL Server; `?` on
SQLite; `:name` on Oracle).  See
[Dialects](dialects.md#placeholders).

### `EXISTS` / `IN` as builder constructs

Not supported.  The pattern is common enough that it is tempting, but
the variations (correlated subquery, `NOT EXISTS`, `ANY`/`ALL`, ...)
are many, and the raw escape hatch is right there.  justorm stays
small on purpose.

### Scalar subqueries in `SELECT`

Not supported as a first-class construct.  Use `cur[...]`:

```python
cur.users.select({
    cur["id"],
    cur["(SELECT count(*) FROM orders o WHERE o.user_id = users.id) AS n"],
})
```

This is verbatim SQL.  You are responsible for the quoting, and for
the placeholder convention if you pass any parameters — which you
cannot, because `cur[...]` takes no parameters.  If you need
parameters, use `where_raw` and a join, or fall back to the driver's
`execute`.

### `LATERAL`

Not supported.  Use `where_raw`.

### Subquery in `UPDATE` / `DELETE`

Not supported.  Use `where_raw`:

```python
cur.users.where_raw(
    "id IN (SELECT user_id FROM orders WHERE total > %s)",
    [100],
).delete()
```

### `WITH` (common table expressions)

Not supported.  Use `where_raw`, or execute the CTE through the
driver directly and pass its results back in.

## Comparison with the alternative

Without justorm's subquery support, the same query would be:

```python
cur.execute("""
    SELECT * FROM users
    JOIN (
        SELECT user_id FROM orders WHERE total > %s
    ) AS s ON users.id = s.user_id
""", [100])
rows = cur.fetchall()
```

With justorm:

```python
sub = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"})
s = sub.as_("s")
rows = cur.users.join(s, on=cur.users["id"] == s["user_id"]).select()
```

The builder version is easier to compose — the subquery can be
constructed separately, reused, or parameterised by the surrounding
code — and the generated SQL is the same.

## See also

* [JOIN](join.md) for how aliases and join conditions work.
* [Expressions](expr.md) for `ColumnExpr` and `Condition`.
* [API reference](api.md#subqueries) for the `select_subquery`
  signature.
* [Dialects](dialects.md) if you are mixing dialects in one codebase.
