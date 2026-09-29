# justorm

一个轻量的、无 schema 的 SQL 构建器，混入原生的数据库游标。

```python
import psycopg
import justorm.psycopg

conn = psycopg.connect("postgresql://localhost/mydb")
with conn.cursor(justorm.psycopg.Cursor) as cur:
    rows = cur.users.where(id=1).select()
    cur.users.where(id=1).update(name="Alice")
    cur.users.append(name="Bob")
```

justorm **不是**那种"把数据库藏起来"的 ORM。它没有 model、没有 session、没有 identity map、没有 migration。它做的只是给你一套流畅的、Pythonic 的方式来**写** SQL，运行在真实的 DB-API 游标上——游标还是那个游标，数据库还是那个数据库。

## 设计原则

justorm 建立在五条原则上。

### 1. 混入游标，而不是替换它

每个驱动的入口都是那个驱动原生游标的子类（SQLite 例外，是包装）。你的其他代码——连接管理、事务、异常处理、`fetchone()`——全都保持原样。justorm 只是**加**方法。

```python
with conn.cursor(justorm.psycopg.Cursor) as cur:
    cur.execute("SELECT 1")            # 原生 psycopg
    cur.users.where(id=1).select()     # justorm
```

### 2. 无 schema

justorm 不知道你的表、列、类型。它从不检查 schema，从不校验列名。`cur.users.where(nonexistent=1).select()` 报错的是数据库，不是 justorm。

这让库保持小、可预测，也不强迫你用大多数 ORM 强加的 "model" 层。

### 3. 链式、不可变

Builder 是不可变的：每次链式调用返回一个新 builder，直到终端方法调用才真正发 SQL。

```python
base = cur.users.where(active=True)   # 还没执行
adults = base.where(cur.users["age"] >= 18)
rows = adults.select()                # 现在才跑
```

### 4. 方言保持可见

justorm **不**试图抹平 PostgreSQL、MySQL、SQLite、SQL Server、Oracle 之间的差异。你连的是 MySQL，就写 `.on_duplicate(...)`；连的是 PostgreSQL，就写 `.on_conflict(...)`。如果你的数据库没有某个特性，justorm 会**在最后时刻**报错，而不是静默地做别的事。

这是刻意的选择。你知道自己在用哪个数据库，justorm 信任你知道。

### 5. 默认转义，需要时裸写

结构化输入——kwargs、`set` / `list` / `tuple` 形式的列名、作为参数传入的值——总是按方言转义、加引号。当你要写 builder 表达不了的东西时，用 `cur['...']`，它原样输出。

```python
cur.users.where(name="a b").select()                  # "name" = %s, ["a b"]
cur.users.where(cur['lower(name)'] == 'a').select()   # lower(name) = %s
```

第一种是安全的。第二种你自己负责。

## 支持的驱动

| 模块                | 驱动                                                      | 数据库          |
| ------------------- | --------------------------------------------------------- | --------------- |
| `justorm.psycopg`   | [psycopg](https://www.psycopg.org/psycopg3/) (v3)         | PostgreSQL      |
| `justorm.psycopg2`  | [psycopg2](https://www.psycopg.org/)                      | PostgreSQL      |
| `justorm.pymysql`   | [PyMySQL](https://pymysql.readthedocs.io/)                | MySQL / MariaDB |
| `justorm.sqlite`    | `sqlite3`（标准库）                                        | SQLite 3        |
| `justorm.pymssql`   | [pymssql](https://pymssql.readthedocs.io/)                | SQL Server      |
| `justorm.oracledb`  | [python-oracledb](https://python-oracledb.readthedocs.io/) | Oracle          |

每个模块按需加载，装 justorm 只为一个驱动不会拉进其他驱动：

```python
import justorm.psycopg    # 只 import psycopg
import justorm.pymysql    # 只 import pymysql
```

顶层的 `import justorm` 不 import 任何驱动。

## 快速预览

### SELECT

```python
cur.users.select()                                   # [{"id": 1, "name": "Alice"}, ...]
cur.users.select({"name"})                           # [{"name": "Alice"}, ...]
cur.users.select(("id", "name"))                     # [(1, "Alice"), ...]
cur.users.select("name")                             # ["Alice", ...]
cur.users.where(id=1).select("name", key="id")       # {1: "Alice"}
cur.users.orderby("name").limit(10).select()
cur.users.where(id=1).get()                          # 单行 dict，无结果返回 None
```

### INSERT

```python
cur.users.append(name="Alice")                        # 单行
cur.users.append({"name": "Alice", "age": 30})        # 同上
cur.users.insert([{"name": "A"}, {"name": "B"}])      # 一条 SQL 多行 VALUES
cur.users.insert_many(rows, columns=["name"])         # executemany
cur.users.returning("id").append(name="Alice")        # -> 1
```

### UPDATE / DELETE

```python
cur.users.where(id=1).update(name="Alice")
cur.users.where(id=1).delete()
cur.users.all().delete()                              # 显式全表
```

### JOIN

```python
u = cur.users.as_("u")
o = cur.orders.as_("o")
u.join(o, on=u["id"] == o["user_id"]).select()
```

### 子查询

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

### 原生 SQL

```python
# 一行执行 + 塑形：
rows = cur.query("SELECT a, b FROM t WHERE c = %s", [1])   # list[dict]
n    = cur.query("UPDATE t SET a = %s WHERE b = %s", [1, 2])  # int

# fetch* 也支持输出格式：
cur.execute("SELECT a, b FROM t")
cur.fetchall(format=dict)
cur.fetchone(format=namedtuple)
```

## justorm 不是什么

- 不是 session 管理器。连接、游标、事务归你。
- 不是 schema 工具。没有 model、migration、字段类型。
- 不是方言抽象层。方言差异是暴露的，不是隐藏的。
- 不是异步的。当前版本只同步。

## 下一步

- [快速开始](quickstart.md) —— 五分钟入门。
- [API 参考](api.md) —— 每个 builder 方法，带例子。
- [方言](dialects.md) —— 什么支持、什么不支持。
- [表达式](expr.md) —— `cur['...']`、`cur.t['col']`、运算符。
- [UPSERT](upsert.md) —— `on_conflict` 和 `on_duplicate`。
- [JOIN](join.md) 和 [子查询](subquery.md)。
- [安全](security.md) —— 什么被转义、什么不被转义、为什么。
- [迁移](migration.md) —— 从裸 SQL 迁移。
