# API 参考

这一页记录 justorm 的公开 surface。按你实际打交道的对象组织，而不是
字母序，因为这更接近你读它的方式。

全文约定：

- `cur` 是 justorm cursor（DB-API cursor 的子类，或它的包装——见
  [快速开始](quickstart.md)）。
- `%s` 是 PostgreSQL、MySQL、SQL Server 的占位符；SQLite 用 `?`；
  Oracle 用命名占位符 `:p<hex>`（由 builder 生成）。示例里为可读性
  都用 `%s`，实际占位符由方言决定并自动处理。
- 生成的 SQL 里所有标识符按方言加引号（PostgreSQL、SQLite、Oracle
  用 `"col"`，MySQL 用 `` `col` ``，SQL Server 用 `[col]`）。示例以
  PostgreSQL 引号为准。

## 目录

- [Cursor 入口](#cursor-入口)
- [表达式](#表达式)
- [条件](#条件)
- [TableBuilder — SELECT](#tablebuilder--select)
- [TableBuilder — 取单行](#tablebuilder--取单行)
- [TableBuilder — INSERT](#tablebuilder--insert)
- [TableBuilder — UPDATE / DELETE](#tablebuilder--update--delete)
- [TableBuilder — JOIN](#tablebuilder--join)
- [TableBuilder — UPSERT](#tablebuilder--upsert)
- [TableBuilder — 排序和分页](#tablebuilder--排序和分页)
- [子查询](#子查询)
- [原生 SQL](#原生-sql)
- [fetch 输出格式](#fetch-输出格式)
- [返回值](#返回值)
- [异常](#异常)

---

## Cursor 入口

### `cur.table(name)` / `cur.table(schema, name)` / `cur.table("schema.name")`

返回该表的 [`TableBuilder`](#tablebuilder--select)。

```python
cur.table("users")              # FROM "users"
cur.table("public", "users")    # FROM "public"."users"
cur.table("public.users")       # 同上
```

最多两段。三段名会报错。

### `cur.<name>`

cursor 上的属性访问等价于 `cur.table(name)`，**除了**当名字已经是
底层 cursor 的属性（比如 `execute`、`fetchone`、`description`、
`rowcount`）。那些名字保持原义。

```python
cur.users          # TableBuilder for "users"
cur.execute        # 原生 cursor 方法
cur.table("order") # 名字和 cursor 属性冲突时用这个
```

### `cur["..."]`

返回一个 [`Expr`](#表达式)，包住给定的 SQL 片段。

```python
cur["lower(name)"]         # Expr("lower(name)")
cur["count(*) AS n"]       # Expr("count(*) AS n")
```

片段是**原样**发出的。构造时只拒绝四个序列：`;`、`--`、`/*`、
`*/`。见 [安全](security.md)。

### `cur.sql`

`.on_conflict(...)` 各件零件所在的命名空间。见
[UPSERT](#tablebuilder--upsert)。

---

## 表达式

表达式有两类，区别很重要。

### `Expr` — `cur["..."]`

不透明 SQL 片段。原样发出。里面的引号你自己负责。

```python
cur["lower(name)"]
cur["now()"]
cur["count(*) AS n"]
```

`Expr` 支持算术和比较运算符。右侧总是作为参数绑定，从不内联：

```python
cur["age"] + 1                # (age + %s), [1]
cur["age"] > 18               # Condition: (age > %s), [18]
cur["a"] == cur["b"]          # Condition: (a = b)
```

这就是**安全**和**原样**的区别：

```python
cur["age + 1"]                # 原样：age + 1
cur["age"] + 1                # 参数化：age + %s, [1]
```

两种都有用。只有第二种保护了值不被内联。

### `ColumnExpr` — `cur.<table>["col"]`

列引用。和 `Expr` 不同，表名和列名都按方言加引号：

```python
cur.users["name"]             # "users"."name"
cur.users["name"] == "Alice"  # Condition: "users"."name" = %s, ["Alice"]
```

`cur.<table>["*"]` 被拒绝；用 `cur["users.*"]`。

### `ColumnExpr.as_(alias)`

在结果集里重命名列：

```python
cur.users["name"].as_("n")    # "users"."name" AS "n"
```

返回的对象记住了别名，`select` 机制能给结果列正确命名。

---

## 条件

条件是你传给 `where`、`on` 以及少数其他地方的。由表达式比较产生，
可以组合。

### `Expr` / `ColumnExpr` 上的运算符

| Python   | SQL   |
| -------- | ----- |
| `==`     | `=`   |
| `!=`     | `<>`  |
| `<`      | `<`   |
| `<=`     | `<=`  |
| `>`      | `>`   |
| `>=`     | `>=`  |
| `+ - * / %` | 算术 |

右侧是 `None` 的比较变成 `IS NULL` / `IS NOT NULL`：

```python
cur.users["age"] == None      # "users"."age" IS NULL
cur.users["age"] != None      # "users"."age" IS NOT NULL
```

### 组合条件

```python
(cur.users["age"] > 18) & (cur.users["active"] == True)   # AND
(cur.users["age"] > 18) | (cur.users["age"] < 5)          # OR
~(cur.users["active"] == True)                            # NOT
```

因为 Python 里 `&` 和 `|` 优先级**高于**比较，**永远加括号**：

```python
# 错：解析为 cur["a"] > (1 & cur["b"]) > 2
cur["a"] > 1 & cur["b"] > 2

# 对：
(cur["a"] > 1) & (cur["b"] > 2)
```

### `Condition.params`

条件会绑定的参数，按顺序。主要调试用。

---

## TableBuilder — SELECT

`TableBuilder` 由 `cur.<table>` 和链式调用（`.where(...)`、
`.join(...)` 等）返回。每个方法返回**新** builder；终端方法调用前
不执行。

### `select(*args, key=None, key_conflict="error", for_update=False, share=False, skip_locked=False, nowait=False)`

终端。执行 `SELECT` 并返回行。

第一个位置参数控制结果**形状**：

| 参数                | 结果                                        |
| ------------------- | ------------------------------------------- |
| （无）              | `list[dict]`，所有列                         |
| `set` 列名          | `list[dict]`，选定的列                       |
| `list` 列名         | `list[dict]`，选定的列，有序                 |
| `tuple` 列名        | `list[tuple]`                               |
| `str`               | `list[标量]`，单列                          |
| `Expr`              | `list[标量]`，单表达式                      |
| `set`/`list` 的 Expr | `list[dict]`                                |
| `tuple` 的 Expr      | `list[tuple]`                               |

```python
cur.users.select()                            # [{"id":1,"name":"Alice"}, ...]
cur.users.select({"name"})                    # [{"name":"Alice"}, ...]
cur.users.select(["name", "age"])             # 列有序
cur.users.select(("id", "name"))              # [(1, "Alice"), ...]
cur.users.select("name")                      # ["Alice", ...]
cur.users.select(cur["count(*)"])             # [3]
cur.users.select({cur.users["name"]})         # [{"name": "Alice"}, ...]
```

给 `key=` 时结果是按那列做的字典：

```python
cur.users.select("name", key="id")            # {1: "Alice", 2: "Bob"}
cur.users.select(key="id")                    # {1: {"id":1,...}, ...}
```

重复 key 按 `key_conflict` 处理：

- `"error"`（默认）：抛异常。
- `"overwrite"`：后者胜。
- callable `f(old, new)`：合并。

```python
cur.users.select("name", key="id", key_conflict="overwrite")
cur.users.select("name", key="id", key_conflict=lambda a, b: a + "/" + b)
```

`key` 值为 `None` 时原样作为字典 key，遵循同样的 `key_conflict`
策略。

`select("*")` 被拒绝；不带参数调用 `select()`。

### `.where(*conditions, **kwargs)`

追加 `AND` 组合的条件。

关键字参数：key 是列名，value 是右值：

```python
cur.users.where(age=30)                # "age" = %s, [30]
cur.users.where(age=None)              # "age" IS NULL
cur.users.where(age=(1, 2))            # "age" = %s, [(1,2)]   — 数组 / 元组
cur.users.where(name=cur["upper('a')"])  # "name" = upper('a')
```

位置参数：每个必须是 [`Condition`](#条件)：

```python
cur.users.where(cur.users["age"] > 18)
cur.users.where((cur.users["age"] > 18) & (cur.users["active"] == True))
```

链式调用 `AND` 组合：

```python
cur.users.where(age=30).where(name="Alice")
# ("age" = %s) AND ("name" = %s)
```

同一次调用里既传位置条件又传关键字参数会报错。

### `.where_in(mapping=None, **kwargs)`

`IN` 条件。传 mapping 或用关键字：

```python
cur.users.where_in(id=[1, 2, 3])
cur.users.where_in({"id": [1, 2, 3]})
cur.users.where_in({cur["lower(name)"]: ["alice", "bob"]})
```

空可迭代生成永远为假的条件：

```python
cur.users.where_in(id=[])              # WHERE FALSE
```

空 mapping 是 no-op（不加任何条件）。

### `.where_not_in(mapping=None, **kwargs)`

同 `where_in`，取反。空可迭代生成 `WHERE TRUE`。

### `.where_between(mapping=None, **kwargs)`

`BETWEEN` 条件。值必须是两元素 tuple 或 list：

```python
cur.users.where_between(age=(18, 65))
cur.users.where_between({cur["age"]: (18, 65)})
```

### `.where_is_null(*columns)`

一个或多个列的 `IS NULL`：

```python
cur.users.where_is_null("deleted_at")
cur.users.where_is_null("deleted_at", "archived_at")
```

### `.where_like(mapping=None, **kwargs)` / `.where_ilike(...)`

`LIKE`（和 `ILIKE`，仅 PostgreSQL）条件：

```python
cur.users.where_like(name="A%")
cur.users.where_ilike(name="a%")       # 仅 PostgreSQL
```

`ILIKE` 在 MySQL、SQLite、SQL Server、Oracle 上在最后时刻被拒绝。

### `.where_raw(sql, params=None)`

追加带可选参数的裸 SQL 片段。builder 表达不了的条件用它：

```python
cur.users.where_raw("length(name) > %s", [5])
cur.users.where_raw("EXISTS (SELECT 1 FROM orders WHERE ...)", [])
```

片段原样发出。`params` 里的值作为参数绑定。

### `.all()`

把 builder 标记为"故意影响所有行"。`update` / `delete` 没有 `where`
时，加它才能跑。对 `select` 无影响。

---

## TableBuilder — 取单行

### `.get(*args, default=None, **kwargs)`

返回查询的第一行，或 `default`（默认 `None`）。第一个位置参数遵循
和 `select` 一样的规则。

```python
cur.users.where(id=1).get()                # {"id": 1, ...} 或 None
cur.users.where(id=1).get("name")          # "Alice" 或 None
cur.users.where(id=1).get(("id", "name"))  # (1, "Alice") 或 None
cur.users.where(id=999).get(default={})    # {}
```

`key=` **不**支持（单行没什么可索引的），传了抛
`JustormTypeError`。任何其他关键字转发给 `select`，所以
`for_update=True` 之类还能用。

`get` 覆盖之前设置的 `limit`：只要一行是它的全部意义。

---

## TableBuilder — INSERT

### `.append(row=None, *, columns=None, **kwargs)`

终端。插**单行**。

```python
cur.users.append(name="Alice", age=30)
cur.users.append({"name": "Alice", "age": 30})
cur.users.append({"name": "Alice"}, age=30)       # 合并；kwargs 优先
cur.users.append(("Alice", 30), columns=["name", "age"])
```

空 list 是 no-op：

```python
cur.users.append([])                              # 什么都不做
```

### `.insert(rows, *, columns=None)`

终端。用一条 `INSERT ... VALUES (...), (...), ...` 语句插**多行**。

```python
cur.users.insert([{"name": "A"}, {"name": "B"}])
cur.users.insert([{"name": "A"}, {"name": "B"}], columns=["name"])
cur.users.insert([("A",), ("B",)], columns=["name"])
```

`columns` 省略且每行是 dict 时，justorm 扫描所有行取 key 的并集
（顺序不定）。某行缺 key 时，那个位置生成 `DEFAULT` 关键字：

```python
cur.users.insert([{"a": 1, "b": 2}, {"a": 3}])
# INSERT INTO "users" ("a","b") VALUES (%s,%s), (%s,DEFAULT)
```

并集之外的 key 被忽略。

空 list 是 no-op。

### `.insert_many(rows, *, columns)`

终端。用驱动的 `executemany`，每行一条语句。

`columns` **必填**，因为 `rows` 可能是惰性迭代器：

```python
cur.users.insert_many(
    ((i, f"name{i}") for i in range(100_000)),
    columns=["id", "name"],
)
cur.users.insert_many([{"id": 1, "name": "A"}], columns=["id", "name"])
```

### `.returning(*columns)`

加 `RETURNING` 子句。PostgreSQL（psycopg / psycopg2）和
SQLite 3.35+ 支持；**MySQL、SQL Server、Oracle 在最后时刻拒绝**。

```python
cur.users.returning("id").append(name="Alice")            # -> 1
cur.users.returning("id", "name").append(name="Alice")    # -> (1, "Alice")
cur.users.returning("id").insert([{"name": "A"}])         # -> [1]
```

返回值形状遵循和 `select` 一样的规则：

- 一个列名  → 标量（`append`）或标量列表
- 多个列名  → 元组（`append`）或元组列表
- 没 `returning` → `None`

`returning` 可以在 insert 方法前后调；总是作用于挂起的语句。

---

## TableBuilder — UPDATE / DELETE

### `.update(row=None, **kwargs)`

终端。更新行。

```python
cur.users.where(id=1).update(name="Alice")
cur.users.where(id=1).update({"name": "Alice"})
cur.users.where(id=1).update({"name": "Alice"}, age=30)   # 合并
```

`None` 表示 `= NULL`（不是 `IS NULL`），因为是赋值：

```python
cur.users.where(id=1).update(deleted_at=None)
# SET "deleted_at" = %s, [None]
```

在既没 `where` 也没 `.all()` 的 builder 上调 `update` 会报错。

### `.delete()`

终端。删除行。

```python
cur.users.where(id=1).delete()
cur.users.all().delete()      # 显式
```

同 `update`：没 `where` 也没 `.all()` 报错。

### UPDATE / DELETE 上的排序 / 分页

builder 不支持 `update` 和 `delete` 的 `LIMIT` 和 `ORDER BY`。用了
会在终端方法运行时抛错：

```python
cur.users.where(id=1).orderby("id").update(name="x")     # 抛
cur.users.where(id=1).limit(1).delete()                  # 抛
```

---

## TableBuilder — JOIN

### `.join(right, *, on=None, using=None, how="inner")`

追加一个 join。必须给 `on` 或 `using` 之一（`cross_join` 例外，
两个都不收）。

```python
o = cur.orders.as_("o")
cur.users.join(o, on=cur.users["id"] == o["user_id"]).select()
cur.users.join(o, using=("id",)).select()
cur.users.join(o, on=..., how="left").select()
```

`how` 接受 `"inner"`、`"left"`、`"right"`、`"full"`、`"cross"`。

### `.inner_join` / `.left_join` / `.right_join` / `.full_join` / `.cross_join`

便捷别名。它们不收 `how=`（混用会报错）。

```python
cur.users.left_join(o, on=cur.users["id"] == o["user_id"]).select()
cur.users.cross_join(cur.regions).select()
```

### `.as_(alias)`

返回用别名引用表的 builder：

```python
u = cur.users.as_("u")
o = cur.orders.as_("o")
u.join(o, on=u["id"] == o["user_id"]).select()
# FROM "users" AS "u" JOIN "orders" AS "o" ON "u"."id" = "o"."user_id"
```

---

## TableBuilder — UPSERT

UPSERT 是方言特定的，justorm 也这么暴露它。

### PostgreSQL / SQLite：`.on_conflict(on=None, do=...)`

```python
# DO NOTHING，无目标
cur.users.on_conflict(do=cur.sql.nothing()).append(id=1, name="A")

# DO NOTHING，目标为列集
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.nothing(),
).append(id=1, name="A")

# DO UPDATE SET，引用 EXCLUDED
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

`cur.sql` 提供三/四个终端 builder：

- `cur.sql.nothing()` —— `DO NOTHING` 动作。
- `cur.sql.update(**kwargs)` —— `DO UPDATE SET ...` 动作。在
  `.update(...)` **之前**链 `.where(...)` 加条件。
- `cur.sql.columns(*names)` —— `ON CONFLICT ( ... )` 目标。
- `cur.sql.constraint(name)` —— `ON CONFLICT ON CONSTRAINT name`
  目标（仅 PostgreSQL）。
- `cur.sql.where(...).columns(...)` —— `ON CONFLICT ( ... ) WHERE
  ...` 目标（索引谓词，仅 PostgreSQL）。

`do=` 必填。`on_conflict()` 不带 `do` 报错。

`ON CONFLICT ON CONSTRAINT` 和索引谓词形式在 SQLite 上在最后时刻
被拒绝。

### MySQL：`.on_duplicate(update)`

```python
cur.users.on_duplicate(update={"name": cur["VALUES(name)"]}).append(
    id=1, name="A",
)
cur.users.on_duplicate(update={"age": 0}).append(id=1, name="A")
```

MySQL 8.0.20+ 偏好行别名；justorm 不自动加，需要就自己写：

```python
cur.users.on_duplicate(update={"name": cur["new.name"]}).append(
    id=1, name="A",
)
```

MySQL 上的 `on_conflict` 和 PostgreSQL / SQLite 上的 `on_duplicate`
都在最后时刻被拒绝。

SQL Server 和 Oracle 既没有 `on_conflict` 也没有 `on_duplicate`——
它们需要 `MERGE`，justorm 不建模。用 `cur.query(...)` 写原生
`MERGE`。

---

## TableBuilder — 排序和分页

### `.orderby(*exprs)` / `.orderby_desc(*exprs)`

追加 `ORDER BY` 项。

```python
cur.users.orderby("name").select()
cur.users.orderby_desc("age", "name").select()
cur.users.orderby("name").orderby_desc("age").select()
# ORDER BY "name", "age" DESC
```

项可以是列名（`str`）或表达式（`Expr`、`ColumnExpr`）：

```python
cur.users.orderby(cur["length(name) DESC"]).select()
cur.users.orderby(cur.users["name"]).select()
```

排序项是追加的，不是替换。

### `.limit(n)` / `.offset(n)`

```python
cur.users.limit(10).select()
cur.users.limit(10).offset(20).select()
```

`limit` 和 `offset` **替换**之前的值。都按字面整数发出，不用占位符。

在 MySQL 上，`offset` 不配 `limit` 是错误（符合 MySQL 自己的语法）。
终端方法运行时抛错。

在 SQL Server 和 Oracle 上它们映射到 `OFFSET n ROWS FETCH NEXT
m ROWS ONLY`。SQL Server 要求 `ORDER BY` 才合法——自己加。

### `.distinct()` / `.distinct_on(*columns)`

```python
cur.users.distinct().select()
cur.users.distinct_on("name").select()      # 仅 PostgreSQL
```

`distinct_on` 被 MySQL、SQLite、SQL Server、Oracle 在最后时刻拒绝。

### `.select(for_update=False, share=False, skip_locked=False, nowait=False)`

锁行。PostgreSQL 和 MySQL 支持；Oracle 支持；SQLite 和 SQL Server
拒绝。

```python
cur.users.where(id=1).select(for_update=True)
cur.users.where(id=1).select(for_update=True, skip_locked=True)
cur.users.where(id=1).select(for_update="share")
```

`for_update=True` 和 `for_update="share"` 分别等价于 `share=False`
和 `share=True`。`nowait` 和 `skip_locked` 互斥。

Oracle 没有 `FOR SHARE`；渲染器把 `share=True` 映射成
`FOR UPDATE`，调用者的锁意图不变。

---

## 子查询

### `.select_subquery(*args)`

终端（但不执行）。返回一个 `Subquery` 对象，可用作 join 目标。

```python
sub = cur.orders.where(total__gt=100).select_subquery({"user_id"})
```

参数遵循和 `select` 一样的规则，除了结果不取——生成的 SQL 嵌进
外层查询。

### `Subquery.as_(alias)`

子查询 join 前必须别名：

```python
s = sub.as_("s")
cur.users.join(s, on=cur.users["id"] == s["user_id"]).select()
# JOIN (SELECT "user_id" FROM "orders" WHERE "total" > %s) AS "s"
#      ON "users"."id" = "s"."user_id"
```

`sub.as_("s")["col"]` 生成一个引用子查询列的 `ColumnExpr`。

### 子查询作为主表

子查询别名也可以做主表：

```python
s = cur.orders.where(total__gt=100).select_subquery({"user_id"}).as_("s")
s.join(cur.users, on=s["user_id"] == cur.users["id"]).select()
```

### 不支持

- `where` 里的子查询（用 `where_raw`）。
- `EXISTS` / `IN` 子查询作为一等 builder 构造（用 `where_raw`）。

---

## 原生 SQL

### `cur.query(sql, params=None)`

执行原生 SQL 并塑形结果，一行调用：

```python
cur.query("SELECT * FROM users WHERE id = %s", [1])
# [{"id": 1, "name": "Alice"}, ...]

cur.query("UPDATE users SET active = %s WHERE id = %s", [True, 1])
# 1  （受影响行数）
```

- 语句返回结果集（`description` 非 None）→ `list[dict]`。
- 否则返回 `int`：
  - `UPDATE` / `DELETE` → `rowcount`。
  - 其他（`INSERT`、`CREATE`、……）→ 驱动提供*真正*的 `lastrowid`
    时返回它，否则 `rowcount`。

`params` 原样传给驱动的 `execute`。大多数驱动接受 list / tuple；
python-oracledb 接受 dict 以配合命名占位符。justorm 不规范化类型。

### `cur.fetch*` 上的 `format=`

三个 `fetch*` 方法接受 `format=`：

```python
cur.execute("SELECT id, name FROM users")
cur.fetchone()                   # (1, "Alice")
cur.fetchone(format=dict)        # {"id": 1, "name": "Alice"}
cur.fetchone(format=namedtuple)  # Row(id=1, name="Alice")
cur.fetchmany(50, format=dict)
cur.fetchall(format=namedtuple)
```

接受的 `format` 值：

- `None`（默认）：驱动原样返回。
- `tuple`：强制转普通元组。
- `dict`：按列名建字典。
- `namedtuple`：建 `namedtuple`，字段是列名（重复的用
  `rename=True` 重命名成 `_0`、`_1`、……）。

`fetchone` 无结果时总是返回 `None`，不管 `format` 是什么。

---

## 返回值

| 终端方法                     | 无 `returning` | 有 `returning`         |
| ---------------------------- | -------------- | ---------------------- |
| `select()`                   | 行             | —                      |
| `get()`                      | 单行 / default | —                      |
| `select_subquery()`          | `Subquery`     | —                      |
| `append(...)`                | `None`         | 标量 / 元组 / dict     |
| `insert(...)`                | `None`         | `list`                 |
| `insert_many(...)`           | `None`         | `list`                 |
| `update(...)`                | `None`         | `list`                 |
| `delete()`                   | `None`         | `list`                 |

`append` 的值是单标量 / 元组 / dict，因为最多插一行。其他 insert
和 DML 方法的值总是 list，因为语句可能影响多行。

`returning` 形状规则和 `select` 一致：

```python
cur.users.returning("id").append(...)                 # 标量
cur.users.returning(("id", "name")).append(...)       # 元组
cur.users.returning({"id", "name"}).append(...)       # dict
cur.users.returning("id").insert([...])               # 标量列表
```

`returning` 在 MySQL、SQL Server、Oracle 上最后时刻被拒绝。

---

## 异常

justorm 自己的异常都继承 `justorm.JustormError`。三个具体子类：

| 异常                  | 含义                                            |
| --------------------- | ----------------------------------------------- |
| `JustormTypeError`    | 参数类型不支持。                                |
| `JustormValueError`   | 参数类型支持但值非法。                          |
| `JustormDialectError` | 当前方言不支持请求的特性。                      |

`JustormTypeError` 也继承 `TypeError`，`JustormValueError` 也继承
`ValueError`，所以捕获内置异常的代码继续工作。

驱动来的错误（比如 `psycopg.Error`、`pymysql.err.MySQLError`、
`sqlite3.OperationalError`）**不**被包装；它们原样抛出。

### 错误什么时候抛

justorm 遵循"最后时刻抛"策略：

- MySQL 上的 `.returning(...)` 不立即抛。语句构造出来；终端方法
  调用时才抛。
- MySQL / SQLite / SQL Server / Oracle 上的 `.distinct_on(...)`
  不立即抛。同样规则。
- 任何方言上的 `.limit(1).delete()` 直到 `delete()` 跑才抛。

例外：

- 参数格式错误（类型错、需要名字的地方给空字符串、
  `cur.t["*"]`……）立即抛，因为没有合理的 builder 状态可以继续。
- `cur["..."]` 里有禁用 token（`;`、`--`、`/*`、`*/`）立即抛。

---

## 本参考之外的东西

justorm 刻意**不**提供：

- 模型、session、identity map、关系、migration。
- 异步 cursor。
- 查询缓存。
- 连接池。
- Schema 内省。
- pymssql / oracledb 的 upsert（用 `cur.query(...)` + `MERGE`）。

这些由应用或驱动负责。
