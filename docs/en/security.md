# Security

justorm is a builder, not a sandbox.  It escapes the things it is
asked to escape, and it leaves the rest to you.  This page describes
exactly where that line is, so you can reason about it.

The short version:

* **Values you pass to the builder are always bound as parameters.**
  You cannot accidentally inject SQL through a value.
* **Column names and table names are quoted as identifiers.**  You
  cannot accidentally inject SQL through a name, as long as you pass
  it where a name is expected.
* **`cur["..."]` is emitted verbatim.**  Do not put untrusted input
  there.  There is no escaping inside a verbatim fragment.
* **`where_raw(sql, params)` treats `sql` as verbatim and `params` as
  values.**  The split is exactly what you wrote.

That is the whole model.  The rest of this page explains why, and
where the sharp edges are.

## What is escaped

### Values

Every value that justorm puts into a statement — whether it comes
from a keyword argument, a dict, a tuple, a list, or an expression's
right-hand side — is bound as a **parameter**.  It is not inlined
into the SQL text.

```python
cur.users.where(name=user_input).select()
# -> WHERE "name" = %s     (params: [user_input])
```

```python
cur.users.append(name=user_input)
# -> INSERT INTO "users" ("name") VALUES (%s)   (params: [user_input])
```

```python
cur.users.where(cur.users["age"] > user_input).select()
# -> WHERE "users"."age" > %s   (params: [user_input])
```

Because the value travels alongside the SQL rather than inside it,
no amount of quoting, comment markers, or statement terminators in
the value can change the meaning of the statement.  The driver
handles the rest.

### Identifiers

Column names and table names that justorm receives **as names** are
quoted with the dialect's identifier quoting rules.  Quote characters
inside the name are doubled according to those rules.

```python
cur.users.where(**{user_input: 1}).select()
# -> WHERE "name; DROP TABLE users" = %s   (params: [1])
```

The value `"name; DROP TABLE users"` is treated as a single identifier.
If it happens to contain a `;`, that `;` is inside the quoted
identifier and has no meaning.

The places where a name is expected are:

* the keyword arguments of `.where(...)`, `.where_in(...)`, and
  friends,
* the `str` keys of the mapping passed to `.where_in(...)` and
  friends,
* `cur.<table>` and `cur.table("...")`,
* `cur.<table>["col"]`,
* `set` / `list` / `tuple` arguments to `select(...)`,
* `using=(...)` on a join,
* the arguments to `cur.sql.columns(...)` and
  `cur.sql.constraint(...)`.

### The split between identifiers and values

In every method that takes both a name and a value, the split is
syntactic, not semantic.  The name is the key; the value is the
value.

```python
cur.users.where(**{name: value})       # name is an identifier, value is a parameter
cur.users.where_in({name: [values]})   # name is an identifier, values are parameters
cur.users.update(**{name: value})      # name is an identifier, value is a parameter
```

If the name comes from user input, it is still quoted as an
identifier, so it cannot break out of its quotes.  What it *can* do
is name a column that does not exist, or one the user was not
supposed to see — but that is an authorization question, not a
quoting question.  See [Authorization](#authorization) below.

## What is not escaped

### `cur["..."]`

The contents of `cur["..."]` are emitted **verbatim**.  There is no
quoting, no doubling, and no placeholder substitution inside the
string.  This is by design: it is the escape hatch, and escape hatches
have to let you escape.

```python
cur["lower(name)"]            # emitted as: lower(name)
cur["count(*) AS n"]          # emitted as: count(*) AS n
cur["name = 'x'"]             # emitted as: name = 'x'  — 'x' is inlined
```

The four forbidden sequences (`;`, `--`, `/*`, `*/`) are rejected at
construction time, which stops the most common accidents:

```python
cur["name; DROP TABLE users"] # JustormValueError
```

But this is a typo guard, **not** a security boundary.  There are
many ways to write SQL that the guard does not catch, because SQL is
a rich language and the guard is four strings long.

**Do not put untrusted input inside `cur["..."]`.**  Not even inside
quotes, not even after escaping it yourself.  If you need to combine
a function name with a value, use the operator form, which binds the
value as a parameter:

```python
cur["lower("] + cur["name"] + cur[")"]   # verbatim, no params — do not do this
```

There is no builder form that produces `lower(<quoted identifier>)`
from a Python string without also quoting the string, so the honest
advice is: if you need `lower(name)`, write `cur["lower(name)"]` and
treat the whole thing as trusted code.  That is what it is for.

### `where_raw(sql, params)`

`where_raw` splits its input in two:

* `sql` is verbatim,
* `params` is a sequence of values that are bound as parameters.

```python
cur.users.where_raw("length(name) > %s", [5]).select()
# -> WHERE length(name) > %s   (params: [5])
```

If you interpolate a value into `sql`, you are on your own:

```python
cur.users.where_raw(f"length(name) > {n}", [])   # do not do this
cur.users.where_raw("length(name) > %s", [n])    # this is the safe form
```

`where_raw` does **not** translate placeholders.  Write the
placeholder your driver expects: `%s` for psycopg, psycopg2, PyMySQL,
and pymssql; `?` for sqlite3; `:name` for Oracle.  See
[Dialects](dialects.md#placeholders).

### Raw SQL passed to the driver

`cur.execute(...)` is the driver's own method.  justorm does not
touch it.  Use it the way the driver documents; for psycopg and
friends that means parameterised queries, not f-strings.

## The `%` character

psycopg, psycopg2, PyMySQL, and pymssql use `%s` placeholders.  A
literal `%` in the SQL text must be doubled so the driver does not
mistake it for a placeholder.

justorm doubles `%` in `cur["..."]` content and in `where_raw`
fragments on those dialects.  SQLite uses `?` and Oracle uses named
placeholders `:p<hex>`, so no doubling is needed there, and justorm
does nothing.

```python
cur["name LIKE 'a%'"]        # emitted as name LIKE 'a%%' on PG/MySQL/SQL Server
                             # emitted as name LIKE 'a%'  on SQLite/Oracle
```

You write the SQL you mean.  Do not write `%%` yourself, and do not
write a `%s` inside `cur["..."]` expecting a parameter to be bound:
no parameter will be bound, because `cur["..."]` takes none.

## Authorization

Quoting identifiers correctly is not the same as authorizing access.
If a column name comes from a request parameter, a user can ask for
a column they were not supposed to see:

```python
col = request.args["col"]              # untrusted
cur.users.select({col})                # runs SELECT "col" FROM "users"
```

justorm will happily quote `"secret_token"` and hand you the values.
Whether that is a problem is your application's decision, not the
builder's.

The general rule: **quote what you must quote, authorize what you
must authorize, and never conflate the two.**

## SQL injection in practice

The ways SQL injection happens in a query builder are:

1. **Inlining a value into SQL text.**  justorm binds values as
   parameters, so this cannot happen through the builder's value
   positions.
2. **Inlining an identifier into SQL text without quoting it.**
   justorm quotes identifiers wherever a name is expected.  The
   escape hatch (`cur["..."]`) does not, but that is the point of an
   escape hatch.
3. **Trusting a `where_raw` fragment built by string concatenation.**
   `where_raw` does not help you if you put the value in the first
   argument instead of the second.  Use parameters.
4. **Concatenating user input into a `cur["..."]` string.**  Don't.
5. **Trusting the driver to do something it does not do.**  For
   example, expecting SQLite to reject a `%s` placeholder; it will
   not, because `%s` is not a placeholder there, it is a literal.
   Write the placeholder your driver expects.

If you avoid (1) through (5), you have avoided SQL injection.

## The four forbidden sequences

`cur["..."]` rejects these substrings:

| Substring | Reason              |
| --------- | ------------------- |
| `;`       | statement separator |
| `--`      | line comment        |
| `/*`      | block comment start |
| `*/`      | block comment end   |

This is a **convenience**, not a guarantee.  It catches the most
common "I pasted two statements into one string" mistakes.  It does
not catch:

* a `;` written as `chr(59)`, or via any other construction,
* SQL that is dangerous without a `;` (for example, a subquery that
  reads a table it should not),
* comments written as `#` (MySQL) — those are not rejected,
* anything else justorm did not think of.

Do not rely on the guard.  Treat `cur["..."]` as you would treat a
call to `cur.execute("...")`: as trusted code.

## `where_raw` is not a sandbox either

`where_raw` does not parse or validate the SQL it receives.  It
splits it into "SQL" and "params" and hands both to the driver.

```python
cur.users.where_raw("1=1 OR 1=1", []).select()   # returns every row
```

That is a legitimate use of `where_raw`.  It is also the kind of
thing a malicious input could do if you build the string yourself.

## Logging

justorm does not log anything.  If you want to see what SQL is
generated, use the driver's own logging, or log `cur.execute` calls
yourself.  A common pattern is a thin wrapper:

```python
class LoggingCursor(justorm.psycopg.Cursor):
    def _execute(self, sql, params):
        logger.debug("SQL: %s  PARAMS: %r", sql, params)
        super()._execute(sql, params)
```

`_execute` and `_execute_and_fetch` are the two places where the
builder hands SQL to the driver.  Both are stable parts of the
internal interface; overriding them is the supported way to
instrument the library.

If you log SQL, remember that bound parameters may contain sensitive
data (passwords, tokens, personal information).  The placeholder
style means the values are not in the SQL string — which is good for
safety — but they will show up in the `params` list if you log it.

## Parameters and types

justorm passes values through to the driver unchanged.  The driver
decides how to adapt them.  This means:

* A value the driver does not know how to adapt will raise an error
  from the driver, not from justorm.
* A value that is adapted differently on different dialects (for
  example a `datetime` with a timezone, or a `Decimal`) will behave
  the way the driver and the database decide, not the way justorm
  decides.

justorm does not attempt to normalise types across dialects.  See
[Dialects](dialects.md#type-adaptation) for the usual mappings.

## Oracle's named placeholders

python-oracledb uses named placeholders.  justorm's Oracle path
assigns a random name `:p<hex>` to every placeholder and passes
parameters to the driver as a dict.  On the security front:

* the names come from `os.urandom(4).hex()`, which is
  cryptographically random, not a predictable counter,
* values are still in a dict, still bound as parameters.  The rules
  for `cur["..."]` are unchanged: verbatim fragments are still
  verbatim.

Random names do not change the security model.  They change *where
placeholder names come from*.

## Summary

| You write                           | Escaped? | Safe for untrusted input? |
| ----------------------------------- | -------- | ------------------------- |
| `cur.users.where(name=value)`       | yes      | yes                       |
| `cur.users.where(**{name: value})`  | yes      | yes                       |
| `cur.users["name"]`                 | yes      | yes (name is not a value) |
| `cur.users.select({name})`          | yes      | yes (name is not a value) |
| `cur["..."]`                        | **no**   | **no**                    |
| `where_raw("... %s ...", [value])`  | yes      | yes                       |
| `where_raw(f"... {value} ...", [])` | **no**   | **no**                    |
| `cur.execute("...")`                | **no**   | **no** (unless the driver does) |

If a piece of data is untrusted, it must appear only in a position
marked "yes" in the third column.  Everything else is your
responsibility.

## See also

* [Expressions](expr.md) for the difference between `cur["..."]` and
  `cur.<table>["col"]`.
* [API reference](api.md) for method signatures.
* [Dialects](dialects.md#placeholders) for the `%s` vs `?` vs
  `:name` rule.
* [Migration](migration.md) for moving raw SQL into the builder
  without losing safety.
