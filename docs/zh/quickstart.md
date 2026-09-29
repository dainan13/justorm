# 快速开始

这一页让你五分钟内从零到跑起一个查询。用 SQLite，因为不需要服务端。但
每个例子在 PostgreSQL、MySQL、SQL Server、Oracle 上都一样——只是
import 和 cursor 类不同。

## 安装

```console
$ pip install justorm[sqlite]
```

`sqlite3` 是 Python 标准库的一部分，所以 `[sqlite]` 这个 extra 实际上
不装任何东西；它只是为了让其他 extra 的命名对称：

```console
$ pip install justorm[psycopg]     # PostgreSQL via psycopg (v3)
$ pip install justorm[psycopg2]    # PostgreSQL via psycopg2
$ pip install justorm[pymysql]     # MySQL / MariaDB via PyMySQL
$ pip install justorm[pymssql]     # SQL Server via pymssql
$ pip install justorm[oracledb]    # Oracle via python-oracledb
```

也可以一次装多个：

```console
$ pip install justorm[psycopg,psycopg2,pymysql]
```

## 创建 cursor

justorm 不打开连接、不管事务。这些你用驱动原样做。唯一区别是你向连接
要的是一个 justorm cursor。

### SQLite

```python
import sqlite3
import justorm.sqlite

conn = sqlite3.connect(":memory:")
cur = justorm.sqlite.Cursor(conn)
```

`sqlite3.Cursor` 是 C 实现的，不能子类化，所以 justorm 是包装它而不是
继承它。这就是为什么 SQLite 入口接收连接作为参数，而其他驱动是
`conn.cursor(...)` 收一个 cursor 类。

### PostgreSQL（psycopg v3）

```python
import psycopg
import justorm.psycopg

conn = psycopg.connect("postgresql://localhost/mydb")
cur = conn.cursor(justorm.psycopg.Cursor)
```

`psycopg` 的 `Connection.cursor()` 把 cursor 类放在 `cursor_factory` 关键字
参数里（第一个位置参数是 **服务端 cursor 的名字**，完全是另一回事）。
也可以在 `connect()` 里一次性指定：

```python
conn = psycopg.connect(
    "postgresql://localhost/mydb",
    cursor_factory=justorm.psycopg.Cursor,
)
cur = conn.cursor()
```

### PostgreSQL（psycopg2）

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

## 建表

justorm 不建表，所以用原生 SQL：

```python
cur.execute("""
    CREATE TABLE users (
        id   INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        age  INTEGER
    )
""")
```

注意 `cur.execute` 还是原生 `sqlite3` 的方法。justorm cursor **就是**
sqlite3 cursor；它只是多了些方法。

## 插入行

`append` 插入单行：

```python
cur.users.append(name="Alice", age=30)
cur.users.append({"name": "Bob", "age": 25})
```

两种形式生成同样的 SQL：

```sql
INSERT INTO "users" ("name", "age") VALUES (%s, %s)
```

`insert` 用一条语句插多行：

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

`insert_many` 走 `executemany`，每行一次往返——当驱动或数据库需要
逐行行为时有用：

```python
cur.users.insert_many(
    [{"name": "Eve", "age": 20}, {"name": "Frank", "age": 45}],
    columns=["name", "age"],
)
```

`insert_many` **总是**需要 `columns`，因为输入可以是惰性迭代器
（生成器、查询结果……），justorm 不想为了发现列名而缓冲它。

## 查询行

`select()` 默认返回 `dict` 列表：

```python
rows = cur.users.select()
# [{"id": 1, "name": "Alice", "age": 30}, ...]
```

加 `where` 条件：

```python
rows = cur.users.where(name="Alice").select()
```

`where` 收关键字参数，用 `AND` 组合：

```python
rows = cur.users.where(name="Alice", age=30).select()
# WHERE "name" = %s AND "age" = %s
```

链式 `where` 也是 `AND`：

```python
rows = cur.users.where(name="Alice").where(age=30).select()
# WHERE ("name" = %s) AND ("age" = %s)
```

## 选择 `select` 返回什么

结果的形状由 `select` 的第一个位置参数决定：

```python
cur.users.select()                 # [{"id": 1, "name": "Alice"}, ...]
cur.users.select({"name"})         # [{"name": "Alice"}, ...]   — set：列子集，dict
cur.users.select(["name"])         # [{"name": "Alice"}, ...]   — list：同上但有序
cur.users.select(("id", "name"))   # [(1, "Alice"), ...]        — tuple：行是元组
cur.users.select("name")           # ["Alice", ...]             — str：单列
```

传 `key=` 时结果是按那列做的 dict：

```python
cur.users.select("name", key="id")     # {1: "Alice", 2: "Bob", ...}
cur.users.select(key="id")             # {1: {"id": 1, "name": "Alice"}, ...}
```

默认情况下重复 key 会报错。可以改：

```python
cur.users.select("name", key="id", key_conflict="overwrite")
cur.users.select("name", key="id", key_conflict=lambda old, new: old + new)
```

## 取一行

`get` 是"取一行"的快捷方式：

```python
cur.users.where(id=1).get()                # {"id": 1, ...} 或 None
cur.users.where(id=1).get("name")          # "Alice" 或 None
cur.users.where(id=1).get(("id", "name"))  # (1, "Alice") 或 None
cur.users.where(id=999).get(default={})    # {}（没找到时）
```

内部相当于 `.limit(1).select(...)[0]`，只是空结果返回 `default`
而不是抛 `IndexError`。

## 更新和删除

`update` 和 `delete` 拒绝在没有 `where` 的情况下运行，因为忘写
`where` 是经典的毁表方式：

```python
cur.users.where(id=1).update(name="Alice Smith")
cur.users.where(id=1).delete()
```

如果你真的要"所有行"，明说：

```python
cur.users.all().update(active=True)
cur.users.all().delete()
```

## 排序和分页

```python
cur.users.orderby("name").limit(10).select()
cur.users.orderby_desc("age").limit(10).offset(20).select()
cur.users.orderby("name").orderby_desc("age").select()
# ORDER BY "name", "age" DESC
```

## 拿到生成的 SQL

终端方法立即执行。要检查发出去的 SQL，可以在 cursor 外包装日志
拦截，或对中间 builder 用 `repr()`：

```python
b = cur.users.where(id=1)
repr(b)   # '<TableBuilder table=users>'
```

## 执行原生 SQL

当 builder 表达不了你的语句时，用 `query`——一次调用既执行也塑形
结果：

```python
rows = cur.query("SELECT id, name FROM users WHERE age > %s", [18])
# [{"id": 1, "name": "Alice"}, ...]

n = cur.query("UPDATE users SET active = %s WHERE id = %s", [True, 1])
# 受影响的行数
```

`query` 对 `SELECT` 返回 `list[dict]`，对写操作返回 `int`。

## 让 `fetch*` 返回特定形状

三个 `fetch*` 方法接受 `format=`：

```python
cur.execute("SELECT id, name FROM users")
cur.fetchall()                   # [(1, "Alice"), ...]        — 默认，元组
cur.fetchall(format=dict)        # [{"id": 1, "name": "Alice"}, ...]
cur.fetchall(format=namedtuple)  # [Row(id=1, name="Alice"), ...]
cur.fetchall(format=tuple)       # 强制转成普通元组
```

`format=None`（默认）返回驱动原本返回的样子。

## 事务

justorm 不参与事务管理。用驱动的设施：

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

## 下一步

- [API 参考](api.md) 看完整 surface。
- [方言](dialects.md) 看 PostgreSQL、MySQL、SQLite、SQL Server、
  Oracle 之间有什么不同。
- [表达式](expr.md) 看逃生舱（`cur['...']`）和运算符 DSL。
- [安全](security.md) 在你把不可信输入放进 builder 之前先读。
