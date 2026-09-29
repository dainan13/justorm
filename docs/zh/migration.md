# 迁移

这一页给已经跑在 DB-API cursor 上、想开始用 justorm 而不想重写的
代码。它假设你熟悉裸 SQL，想逐步迁移到 builder，一次一条语句。

迁移路径分三阶段：

1. **换上 cursor。** import 一个 justorm cursor 类，在原来用驱动
   cursor 的地方都用它。其他不变；`cur.execute` 还能用。
2. **一次改一条语句。** 把 `cur.execute("SELECT ...", params)` 换成
   builder 形式。其余不动。
3. **需要时用逃生舱。** 有些语句不值得迁移。`where_raw`、
   `cur["..."]`、`cur.execute` 永远在。

没有第 4 阶段，没有"一次全改"的步骤。justorm 设计成重写可以一条
一条发生，永远如此，或者根本不发生。

## 阶段 1：换上 cursor

改前：

```python
import psycopg

conn = psycopg.connect(...)
cur = conn.cursor()
cur.execute("SELECT id, name FROM users WHERE id = %s", [1])
row = cur.fetchone()
```

改后：

```python
import psycopg
import justorm.psycopg

conn = psycopg.connect(...)
cur = conn.cursor(justorm.psycopg.Cursor)
cur.execute("SELECT id, name FROM users WHERE id = %s", [1])
row = cur.fetchone()
```

唯一改动是 cursor 类。其他——`execute` 调用、`%s` 占位符、
`fetchone`——和以前完全一样工作。"混入游标"设计的全部意义就在
这里：cursor **就是** psycopg cursor，所以这一步不需要改任何现有
代码。

SQLite 上改动稍不同，因为 `sqlite3.Cursor` 不能子类化：

```python
import sqlite3
import justorm.sqlite

conn = sqlite3.connect(...)
cur = justorm.sqlite.Cursor(conn)
cur.execute("SELECT id, name FROM users WHERE id = ?", [1])
row = cur.fetchone()
```

包装对 DB-API surface 是透明的。`execute`、`fetchone`、
`description`、`rowcount` 等行为同以前。

你可以在代码库里换 cursor 而完全不用 builder。如果这就是你需要的
全部，那是很好的终点。

## 阶段 2：一次改一条语句

cursor 就位后，每条语句可以独立迁移。没有全局开关、没有 session、
没有"justorm 模式"；一条语句要么用 builder，要么不用。

### SELECT

改前：

```python
cur.execute(
    "SELECT id, name FROM users WHERE active = %s ORDER BY name LIMIT 10",
    [True],
)
rows = cur.fetchall()
```

改后：

```python
rows = cur.users.where(active=True).orderby("name").limit(10).select()
```

结果和驱动返回的行列表一样。如果你偏好 dict，builder 默认产生
dict；如果偏好 tuple，给 `select` 传 tuple：

```python
rows = cur.users.where(active=True).orderby("name").limit(10).select(("id", "name"))
```

### INSERT

改前：

```python
cur.execute(
    "INSERT INTO users (name, age) VALUES (%s, %s)",
    ["Alice", 30],
)
```

改后：

```python
cur.users.append(name="Alice", age=30)
```

多行时：

改前：

```python
cur.executemany(
    "INSERT INTO users (name, age) VALUES (%s, %s)",
    [("Alice", 30), ("Bob", 25)],
)
```

改后：

```python
cur.users.insert_many([("Alice", 30), ("Bob", 25)], columns=["name", "age"])
```

注意两种插入方法不同：

- `cur.users.insert(rows)` 用**单条** `INSERT ... VALUES (...),
  (...), (...)` 语句。这是快的那个，也是批量加载该用的。
- `cur.users.insert_many(rows, columns=...)` 用驱动的
  `executemany`，每行一次往返。驱动或数据库需要逐行行为时用。

区别镜像裸 SQL 里的那个，所以迁移机械。

### UPDATE / DELETE

改前：

```python
cur.execute("UPDATE users SET name = %s WHERE id = %s", ["Alice", 1])
cur.execute("DELETE FROM users WHERE id = %s", [1])
```

改后：

```python
cur.users.where(id=1).update(name="Alice")
cur.users.where(id=1).delete()
```

builder 拒绝在没有 `where` 的情况下跑 `update` 或 `delete`，因为
忘写 `where` 是经典的毁表方式。如果你真的指"所有行"，明说：

```python
cur.users.all().update(active=True)
cur.users.all().delete()
```

现有裸 SQL 形式没有这个守卫；这是 builder 比裸 API 严格的少数
地方之一。如果严格性对某条特定语句是问题，`cur.execute` 还能用。

### 参数

builder 把参数当 Python 值收，在裸 SQL 会用 `%s` 的同样位置：

```python
# 改前
cur.execute("SELECT * FROM users WHERE name = %s AND age > %s", ["Alice", 18])

# 改后
cur.users.where(name="Alice").where(cur.users["age"] > 18).select()
```

比较右侧的值总是绑为参数，从不内联。见 [安全](security.md)。

### 占位符

builder 里不写占位符。回落 `where_raw` 或 `cur.execute` 时，写你
的驱动期望的占位符：

- psycopg、psycopg2、PyMySQL、pymssql 用 `%s`；
- sqlite3 用 `?`；
- Oracle 用 `:name`。

justorm 不翻译占位符。见 [方言](dialects.md#占位符)。

## 阶段 3：逃生舱

有些语句不值得迁移。窗口函数、递归 CTE、`LATERAL`、奇异 join、
`INSERT ... SELECT`、`COPY`、`EXPLAIN ANALYZE`——builder 不建模
这些，可能也不该。

逃生舱永远在，三种形式：

### `where_raw` 用于条件

```python
cur.users.where_raw("id IN (SELECT user_id FROM orders WHERE total > %s)", [100]).select()
```

SQL 原样，参数被绑。别用字符串拼接构造第一个参数；见
[安全](security.md)。

### `cur["..."]` 用于片段

```python
cur.users.select({
    cur.users["id"],
    cur["row_number() OVER (PARTITION BY team ORDER BY score DESC) AS rank"],
}).select()
```

片段原样。`cur["..."]` 和 `cur.users["..."]` 的区别见
[表达式](expr.md)。

### `cur.execute` 用于整条语句

cursor 还是有原生 `execute` 方法，还是返回它一直返回的东西：

```python
cur.execute("EXPLAIN ANALYZE SELECT * FROM users WHERE id = %s", [1])
plan = cur.fetchall()
```

这不需要"退出 justorm 模式"。cursor 首先是驱动 cursor，其次是
builder。

## 常见翻译模式

### 单个条件

```python
# 改前
cur.execute("SELECT * FROM users WHERE id = %s", [1])

# 改后
cur.users.where(id=1).select()
```

### 多条件，AND

```python
# 改前
cur.execute("SELECT * FROM users WHERE active = %s AND age > %s", [True, 18])

# 改后
cur.users.where(active=True).where(cur.users["age"] > 18).select()
```

### OR

```python
# 改前
cur.execute("SELECT * FROM users WHERE age < %s OR age > %s", [5, 65])

# 改后
cur.users.where((cur.users["age"] < 5) | (cur.users["age"] > 65)).select()
```

括号操作数；Python 里 `&` 和 `|` 比比较绑定更紧。见
[表达式](expr.md#加括号)。

### `IN`

```python
# 改前
cur.execute("SELECT * FROM users WHERE id IN (%s, %s, %s)", [1, 2, 3])

# 改后
cur.users.where_in(id=[1, 2, 3]).select()
```

占位符数量从列表长度派生。别在 `where_raw` 里自己拼列表，除非你
也拼占位符列表；builder 给你做了。

### `BETWEEN`

```python
# 改前
cur.execute("SELECT * FROM users WHERE age BETWEEN %s AND %s", [18, 65])

# 改后
cur.users.where_between(age=(18, 65)).select()
```

### `LIKE`

```python
# 改前
cur.execute("SELECT * FROM users WHERE name LIKE %s", ["A%"])

# 改后
cur.users.where_like(name="A%").select()
```

### `IS NULL`

```python
# 改前
cur.execute("SELECT * FROM users WHERE deleted_at IS NULL")

# 改后
cur.users.where(deleted_at=None).select()
# 或
cur.users.where_is_null("deleted_at").select()
```

### `ORDER BY` / `LIMIT`

```python
# 改前
cur.execute("SELECT * FROM users ORDER BY name, age DESC LIMIT 10 OFFSET 20")

# 改后
cur.users.orderby("name").orderby_desc("age").limit(10).offset(20).select()
```

### `RETURNING`

```python
# 改前
cur.execute("INSERT INTO users (name) VALUES (%s) RETURNING id", ["Alice"])
new_id = cur.fetchone()[0]

# 改后
new_id = cur.users.returning("id").append(name="Alice")
```

`RETURNING` 仅 PostgreSQL 和 SQLite。MySQL、SQL Server、Oracle 上
用各自的方式：

**MySQL**：

```python
cur.users.append(name="Alice")
new_id = cur.execute("SELECT LAST_INSERT_ID()").fetchone()[0]
```

**SQL Server**（`OUTPUT` 子句）：

```python
cur.query(
    "INSERT INTO users (name) OUTPUT INSERTED.id VALUES (%s)",
    ["Alice"],
)
```

**Oracle**（`RETURNING INTO` 加 OUT 绑定）：

```python
var = cur.var(oracledb.NUMBER)
cur.execute(
    "INSERT INTO users (name) VALUES (:p1) RETURNING id INTO :p2",
    {"p1": "Alice", "p2": var},
)
new_id = var.getvalue()
```

### `JOIN`

```python
# 改前
cur.execute("""
    SELECT u.id, u.name, o.total
    FROM users u
    JOIN orders o ON u.id = o.user_id
    WHERE o.paid = %s
""", [True])

# 改后
u = cur.users.as_("u")
o = cur.orders.as_("o")
u.join(o, on=u["id"] == o["user_id"]).where(o["paid"] == True).select({
    u["id"], u["name"], o["total"],
})
```

### UPSERT

```python
# 改前（PostgreSQL）
cur.execute("""
    INSERT INTO users (id, name) VALUES (%s, %s)
    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
""", [1, "Alice"])

# 改后（PostgreSQL）
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(id=1, name="Alice")
```

```python
# 改前（MySQL）
cur.execute("""
    INSERT INTO users (id, name) VALUES (%s, %s)
    ON DUPLICATE KEY UPDATE name = VALUES(name)
""", [1, "Alice"])

# 改后（MySQL）
cur.users.on_duplicate(update={"name": cur["VALUES(name)"]}).append(id=1, name="Alice")
```

完整 surface 见 [UPSERT](upsert.md)。

## 不迁移的东西

builder 刻意不覆盖：

- **DDL。** `CREATE TABLE`、`ALTER TABLE`、`DROP`、`CREATE INDEX`
  之类不建模。用 `cur.execute`。
- **`SELECT` 里的窗口函数。** 表达式用 `cur["..."]`，外层查询用
  `select`。
- **递归 CTE。** 用 `cur.execute`。
- **`INSERT ... SELECT`。** 用 `cur.execute`，或用 builder 跑
  `SELECT`、收行、喂给 `insert`。后者慢但能用。
- **`COPY`。** 用驱动的 `copy` API。
- **`EXPLAIN` / `EXPLAIN ANALYZE`。** 用 `cur.execute`。
- **`LATERAL`、`NATURAL`、逗号 join。** 用 `where_raw` 或
  `cur.execute`。
- **`UPDATE ... LIMIT`、`DELETE ... LIMIT`。** 用 `where_raw`
  加子查询，或 `cur.execute`。
- **`FOR UPDATE OF table`。** 用 `where_raw`。
- **事务。** 用驱动的事务 API。justorm 不管事务。
- **连接池。** 用驱动的池，或第三方池。justorm 不管连接。

模式是：justorm 建模你每天写的语句，长尾留给 `cur.execute`。这就
是整个设计。

## 一个完整迁移

考虑这个函数：

```python
def find_active_users(conn, min_age):
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, age FROM users "
        "WHERE active = %s AND age >= %s "
        "ORDER BY name "
        "LIMIT 100",
        [True, min_age],
    )
    return cur.fetchall()
```

三阶段。

### 换上 cursor

```python
import justorm.psycopg

def find_active_users(conn, min_age):
    cur = conn.cursor(justorm.psycopg.Cursor)
    cur.execute(
        "SELECT id, name, age FROM users "
        "WHERE active = %s AND age >= %s "
        "ORDER BY name "
        "LIMIT 100",
        [True, min_age],
    )
    return cur.fetchall()
```

其他不变。如果函数到处都用，这一步就够了。

### 重写语句

```python
import justorm.psycopg

def find_active_users(conn, min_age):
    cur = conn.cursor(justorm.psycopg.Cursor)
    return (
        cur.users
        .where(active=True)
        .where(cur.users["age"] >= min_age)
        .orderby("name")
        .limit(100)
        .select(("id", "name", "age"))
    )
```

返回值还是同样的 tuple 列表。`where` 调用 `AND` 组合，匹配原样。

### 如果语句不值得

假设查询长了个窗口函数：

```sql
SELECT id, name, age,
       row_number() OVER (PARTITION BY team ORDER BY score DESC) AS rank
FROM users
WHERE active = %s AND age >= %s
ORDER BY name
LIMIT 100
```

窗口函数不建模；那部分用逃生舱：

```python
return (
    cur.users
    .where(active=True)
    .where(cur.users["age"] >= min_age)
    .select({
        "id", "name", "age",
        cur["row_number() OVER (PARTITION BY team ORDER BY score DESC) AS rank"],
    })
    .orderby("name")
    .limit(100)
    .select()
)
```

或者，如果整条语句作为裸 SQL 更好读，回落到 `cur.execute`。没有
惩罚；cursor 是驱动 cursor。

## 另见

- [快速开始](quickstart.md) 如果你是新手。
- [API 参考](api.md) 看方法签名。
- [安全](security.md) 看安全/不安全输入之间的边界。
- [方言](dialects.md) 看影响迁移的各数据库差异。
- [UPSERT](upsert.md)、[JOIN](join.md)、[子查询](subquery.md)
  看最可能需要逃生舱的部分。
