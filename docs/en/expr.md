# Expressions

Most of justorm works with Python values and column names.  When you
need to write SQL that the builder does not have a method for — a
function call, a `CASE`, a cast, an unusual comparison — you reach for
an **expression**.  This page is about the two kinds of expression,
what they do, and where the boundaries are.

The two kinds are:

* `Expr`, produced by `cur["..."]` — a verbatim SQL fragment.
* `ColumnExpr`, produced by `cur.<table>["col"]` — a quoted column
  reference.

Their names are similar; their behaviour is very different.  The
distinction matters.

## `Expr` — `cur["..."]`

`cur["..."]` wraps the given string in an `Expr`.  The string is
emitted **verbatim** into the SQL.  It is the escape hatch, and it is
the only place in justorm where you are responsible for the SQL text
yourself.

```python
cur["lower(name)"]           # lower(name)
cur["now()"]                 # now()
cur["count(*) AS n"]         # count(*) AS n
cur["CASE WHEN a > 0 THEN 1 ELSE 0 END"]
```

### What is rejected

At construction time, `cur["..."]` rejects four sequences:

| Sequence | Why                                |
| -------- | ---------------------------------- |
| `;`      | Prevents multiple statements       |
| `--`     | Prevents line comments             |
| `/*`     | Prevents block comments            |
| `*/`     | Same                               |

This is a **safety net for typos**, not a security boundary.  It stops
you from accidentally pasting two statements into one string.  It does
not make user input safe.  See [Security](security.md).

```python
cur["name"]                  # fine
cur["name; DROP TABLE users"] # JustormValueError
cur["name -- comment"]       # JustormValueError
```

If you need a semicolon or a comment in your SQL, use
[`where_raw`](api.md#where_rawsql-paramsnone) with the `execute`
method of the driver, or split the work into two statements.

### Operators on `Expr`

`Expr` supports arithmetic and comparison operators.  The
right-hand side is always bound as a parameter — never inlined — when
it is a Python value:

```python
cur["age"] + 1               # (age + %s), params [1]
cur["age"] - 1               # (age - %s), params [1]
cur["price"] * 2             # (price * %s), params [2]
cur["price"] / 100           # (price / %s), params [100]
cur["age"] % 10              # (age % %s), params [10]

cur["age"] > 18              # Condition: (age > %s), params [18]
cur["age"] >= 18             # Condition: (age >= %s)
cur["age"] < 65              # Condition: (age < %s)
cur["age"] <= 65             # Condition: (age <= %s)
cur["name"] == "Alice"       # Condition: (name = %s), params ["Alice"]
cur["name"] != "Bob"         # Condition: (name <> %s)
```

If the right-hand side is another `Expr`, the comparison is emitted
without a bound parameter:

```python
cur["a"] == cur["b"]         # Condition: (a = b), no params
cur["a"] > cur["b"]          # Condition: (a > b)
```

This is the difference between *parameterised* and *verbatim*:

```python
cur["age + 1"]               # verbatim: age + 1
cur["age"] + 1               # parameterised: (age + %s), params [1]
```

Both are useful.  Only the second protects the value from being
inlined.

### `None` and comparisons

A comparison whose right-hand side is `None` becomes `IS NULL` or
`IS NOT NULL`:

```python
cur["deleted_at"] == None    # Condition: (deleted_at IS NULL)
cur["deleted_at"] != None    # Condition: (deleted_at IS NOT NULL)
```

Note that this is the behaviour *only* in a comparison.  In an
assignment (`update`, `insert`, `on_conflict`'s `do=cur.sql.update`),
`None` means `= NULL`:

```python
cur.users.where(id=1).update(deleted_at=None)
# SET "deleted_at" = %s, params [None]
```

### Nested expressions

Arithmetic nests as you would expect:

```python
cur["a"] + cur["b"] * 2      # (a + (b * %s)), params [2]
```

The parentheses are added by justorm, not by you, and are always
correct.  The expression tree is what you wrote; the SQL is what you
get.

### Using `Expr` in `select`

`Expr` items may appear in the column list of `select`:

```python
cur.users.select({cur["id"], cur["lower(name) AS lname"]})
# SELECT "id", lower(name) AS lname FROM "users"
```

A single `Expr` as the only argument produces scalars, not dicts:

```python
cur.users.select(cur["count(*)"])    # [3]
```

## `ColumnExpr` — `cur.<table>["col"]`

`cur.users["name"]` creates a `ColumnExpr`.  It is similar to `Expr`,
but it knows the table and the column name, so it can quote both
according to the dialect:

```python
cur.users["name"]            # "users"."name"
cur.users["name"] == "Alice" # Condition: ("users"."name" = %s), params ["Alice"]
cur.users["name"] + " x"     # ColumnExpr: ("users"."name" + %s)
```

The quoting is dialect-specific:

* PostgreSQL, SQLite, Oracle: `"users"."name"`
* MySQL: `` `users`.`name` ``
* SQL Server: `[users].[name]`

You do not write the quotes.  If the column name itself contains a
quote character, it is doubled according to the dialect's rules.

### `cur.<table>["*"]` is rejected

The wildcard is not a column name, and justorm does not pretend
otherwise:

```python
cur.users["*"]               # JustormValueError
cur["users.*"]               # verbatim: users.*
```

If you want `users.*` in a `select`, use the `Expr` form.

### Aliases: `ColumnExpr.as_(alias)`

The `as_` method returns an `Expr` that carries the alias, so the
result-set column is named correctly:

```python
cur.users["name"].as_("n")    # "users"."name" AS "n"
```

The aliased expression is a plain `Expr` (it does not need the table
knowledge any more), but it remembers the alias for the `select`
machinery:

```python
cur.users.select({cur.users["name"].as_("n")})
# SELECT "users"."name" AS "n" FROM "users"
# [{"n": "Alice"}, ...]
```

This is how you resolve name clashes in multi-table queries:

```python
cur.users.join(cur.orders, on=...).select({
    cur.users["id"].as_("user_id"),
    cur.orders["id"].as_("order_id"),
})
```

## Conditions

A `Condition` is what comparison operators produce.  It is the
thing you pass to `.where(...)`, `.where_raw` accepts the SQL text
directly, and joins accept through `on=`.

Conditions combine with three operators:

```python
a = cur.users["age"] > 18
b = cur.users["active"] == True

a & b         # AND: ((age > %s) AND (active = %s))
a | b         # OR:  ((age > %s) OR (active = %s))
~a            # NOT: (NOT (age > %s))
```

### Parenthesise

Python's operator precedence puts `&` and `|` **above** comparisons.
Without parentheses, this:

```python
cur["a"] > 1 & cur["b"] > 2
```

parses as:

```python
cur["a"] > (1 & cur["b"]) > 2
```

which is not what you mean.  Always parenthesise comparison operands
when combining them:

```python
(cur["a"] > 1) & (cur["b"] > 2)
```

justorm cannot fix this in Python; it is a language-level rule.
Getting it wrong will usually produce a `TypeError` from the `&`
operator, but not always.

### Conditions have no SQL of their own

A `Condition` is not a string.  It is an abstract node.  Its SQL is
generated when the enclosing statement is rendered, which is why
conditions can be reused across dialects:

```python
cond = cur.users["age"] > 18
# ... later, on a MySQL cursor ...
cur.users.where(cond).select()
```

The `Condition` holds the structure, not the dialect-specific text.
`Condition.params` exposes the list of bound parameters for
debugging:

```python
(cur.users["age"] > 18).params       # [18]
(cur.users["name"] == "Alice").params # ["Alice"]
```

### `where` with keyword arguments

Inside `.where(...)`, keyword arguments are shorthand for equality
conditions on bare column names:

```python
cur.users.where(age=30)              # "age" = %s, params [30]
cur.users.where(age=None)            # "age" IS NULL
```

The key is always a plain column name, quoted by the dialect.  To
qualify a column, use the `ColumnExpr` form:

```python
cur.users.where(cur.users["age"] == 30)
```

Mixing positional `Condition`s and keyword arguments in one call is an
error.

### `where` with a dict

`.where_in`, `.where_not_in`, `.where_between`, `.where_like`, and
`.where_ilike` accept either keyword arguments or a mapping.  The
mapping may use `str` keys (quoted as identifiers) or `Expr` keys
(emitted verbatim):

```python
cur.users.where_in(id=[1, 2, 3])                  # "id" IN (%s, %s, %s)
cur.users.where_in({"id": [1, 2, 3]})             # same
cur.users.where_in({cur["lower(name)"]: ["a"]})   # lower(name) IN (%s)
cur.users.where_in({cur.users["id"]: [1, 2, 3]})  # "users"."id" IN (%s, %s, %s)
```

Mixing a mapping and keyword arguments in one call is an error.

## When to use which

| You want...                              | Use                          |
| ---------------------------------------- | ---------------------------- |
| a plain column                           | `cur.table["col"]`           |
| a column with an alias                   | `cur.table["col"].as_("x")`  |
| a function call                          | `cur["lower(name)"]`         |
| a SQL keyword (`DEFAULT`, `NULL`)        | `cur["DEFAULT"]`             |
| a comparison                            | `cur.x == 1`, `cur.t["a"] > cur.t["b"]` |
| a logical combination                    | `a & b`, `a | b`, `~a`       |
| an `IN` list                             | `where_in(...)`              |
| a `BETWEEN`                              | `where_between(...)`         |
| a `LIKE`                                 | `where_like(...)`            |
| anything else                            | `where_raw(...)`             |

The last row is important.  justorm has a small expression vocabulary
on purpose; the escape hatch is always `where_raw` (for conditions)
and `cur[...]` (for other fragments).

## The `%` question

On PostgreSQL, MySQL, and SQL Server, the driver uses `%s`
placeholders, which means a literal `%` in SQL text must be doubled.
justorm handles this for `Expr` content and for `where_raw`
fragments:

```python
cur["name LIKE 'a%'"]        # PostgreSQL/MySQL/SQL Server: emitted as name LIKE 'a%%'
                             # SQLite/Oracle: emitted as name LIKE 'a%'
```

You write the SQL you mean; the dialect renderer doubles the percent
signs where the driver requires it.  The one exception is a `%s` you
write yourself inside `cur[...]`:

```python
cur["name LIKE %s"]          # looks like a placeholder, but there is
                             # no parameter to bind — do not do this
```

If you need a placeholder, use a method that accepts parameters
(`where_raw`, `where_in`, ...).  See [Security](security.md).

## A worked example

Suppose you want:

```sql
SELECT
    id,
    lower(name) AS lname,
    CASE WHEN age >= 18 THEN 'adult' ELSE 'minor' END AS status
FROM users
WHERE deleted_at IS NULL
  AND (age >= %s OR verified = %s)
ORDER BY lower(name)
```

With justorm:

```python
cur.users.select({
    cur.users["id"],
    cur["lower(name) AS lname"],
    cur["CASE WHEN age >= 18 THEN 'adult' ELSE 'minor' END AS status"],
}).where(
    cur.users["deleted_at"] == None,
).where(
    (cur.users["age"] >= 18) | (cur.users["verified"] == True),
).orderby(cur["lower(name)"]).select()
```

The parameters come out as `[18, True]`.  The `18` and the `True` are
bound; the `'adult'` and `'minor'` are inside a verbatim `Expr` and
are inlined — you wrote them, so you own them.  See
[Security](security.md) for the rules.

## See also

* [API reference](api.md#expressions) for the method signatures.
* [Security](security.md) for the boundaries between safe and unsafe
  input.
* [Dialects](dialects.md#placeholders) for the placeholder and `%`
  rules.
* [Migration](migration.md) for moving raw SQL into the builder.
