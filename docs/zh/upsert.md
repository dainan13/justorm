# UPSERT

**UPSERT** 是"插入这一行，但如果它已经存在，就做别的事"。justorm
说的每个数据库都有 upsert，但拼法不同，justorm 把每种拼法都暴露出
来，而不是藏起来。

- PostgreSQL：`INSERT ... ON CONFLICT ... DO NOTHING | DO UPDATE ...`
- SQLite：`INSERT ... ON CONFLICT ... DO NOTHING | DO UPDATE ...`
  （和 PostgreSQL 类似，但语法更小）
- MySQL：`INSERT ... ON DUPLICATE KEY UPDATE ...`
- SQL Server / Oracle：**不支持**，两者都用 `MERGE`

这一页覆盖前两种。并排表见 [方言](dialects.md#upsert)。

## PostgreSQL 和 SQLite：`on_conflict`

builder surface 是：

```python
cur.users.on_conflict(
    on = <可选冲突目标>,
    do = <必填动作>,
).append(...)
```

`on` 可选；`do` 必填。`on_conflict` 不带 `do` 时在 builder 构造时
抛 `JustormTypeError`——没有合理的默认值，justorm 拒绝猜。

### `do=cur.sql.nothing()`

最简单的形式：冲突时什么都不做。

```python
cur.users.on_conflict(do=cur.sql.nothing()).append(id=1, name="Alice")
```

```sql
INSERT INTO "users" ("id", "name")
VALUES (%s, %s)
ON CONFLICT DO NOTHING
```

`cur.sql.nothing()` 是终端 builder。它后面不能接 `.where(...)`；
`DO NOTHING` 没有条件。

### `on=cur.sql.columns(...)`

针对特定列集。这是大多数人想要的形式：只在命名列和已存在的
unique 索引冲突时触发。

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.nothing(),
).append(id=1, name="Alice")
```

```sql
INSERT INTO "users" ("id", "name")
VALUES (%s, %s)
ON CONFLICT ("id") DO NOTHING
```

多列允许，按你给的顺序发出：

```python
cur.users.on_conflict(
    on=cur.sql.columns("tenant_id", "email"),
    do=cur.sql.nothing(),
).append(tenant_id=1, email="a@example.com", name="Alice")
```

```sql
ON CONFLICT ("tenant_id", "email") DO NOTHING
```

### `do=cur.sql.update(...)`

`DO UPDATE SET ...`。关键字参数是赋值；值可以是普通 Python 值
（绑为参数）或表达式。

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(id=1, name="Alice")
```

```sql
ON CONFLICT ("id") DO UPDATE SET "name" = EXCLUDED.name
```

`EXCLUDED.<col>` 指**本来会被插入**的那一行。写成 `Expr`，因为
justorm 不特殊处理它：

```python
cur["EXCLUDED.name"]         # PostgreSQL / SQLite
```

`EXCLUDED` 是 PostgreSQL / SQLite 的关键字；justorm 原样传。拼
大小写由你负责。PostgreSQL 把不加引号的标识符折叠到小写，所以
`EXCLUDED.name` 是常见拼法。

普通值也行：

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(seen=0, updated_at=cur["now()"]),
).append(id=1, name="Alice")
```

```sql
ON CONFLICT ("id") DO UPDATE SET "seen" = %s, "updated_at" = now()
```

### `do=cur.sql.where(...).update(...)`

给 update 加 `WHERE`，让冲突只在满足条件的行上更新：

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.where(cur["users.updated_at < now()"]).update(
        name=cur["EXCLUDED.name"],
    ),
).append(id=1, name="Alice")
```

```sql
ON CONFLICT ("id") DO UPDATE SET "name" = EXCLUDED.name
WHERE users.updated_at < now()
```

注意顺序：`where` 链在 `.update(...)` **之前**，不是之后。
`cur.sql.where(...)` 单独存在是不完整 builder；必须以
`.update(...)` 结尾。反过来——`.update(...)` 后接 `.where(...)`
——不支持，因为终端动作总是最后写。

### `on=cur.sql.constraint(...)` —— 仅 PostgreSQL

针对命名约束而不是列集：

```python
cur.users.on_conflict(
    on=cur.sql.constraint("users_pkey"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(id=1, name="Alice")
```

```sql
ON CONFLICT ON CONSTRAINT users_pkey DO UPDATE SET "name" = EXCLUDED.name
```

SQLite 没有对应物：`ON CONFLICT ON CONSTRAINT` 需要一个**约束**
名，而 SQLite 的 `ON CONFLICT` 只收列列表。调用被 builder 接受，
被 renderer 在最后时刻拒绝：

```python
cur.users.on_conflict(
    on=cur.sql.constraint("users_pkey"),
    do=cur.sql.nothing(),
).append(id=1, name="Alice")
# JustormDialectError: SQLite does not support ON CONFLICT ON CONSTRAINT
```

### `on=cur.sql.where(...).columns(...)` —— 仅 PostgreSQL

"索引谓词"形式，配合 partial unique 索引：

```sql
CREATE UNIQUE INDEX users_email_active
    ON users (email) WHERE deleted_at IS NULL;
```

```python
cur.users.on_conflict(
    on=cur.sql.where(cur["deleted_at IS NULL"]).columns("email"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(email="a@example.com", name="Alice")
```

```sql
ON CONFLICT ("email") WHERE deleted_at IS NULL
DO UPDATE SET "name" = EXCLUDED.name
```

这里的 `WHERE` 是**索引谓词**：匹配 partial 索引的谓词，不是行
过滤。它和 `DO UPDATE SET` 后面的 `WHERE` **不**是一回事。一条
语句可以两个都有：

```python
cur.users.on_conflict(
    on=cur.sql.where(cur["deleted_at IS NULL"]).columns("email"),
    do=cur.sql.where(cur["users.updated_at < now()"]).update(
        name=cur["EXCLUDED.name"],
    ),
).append(email="a@example.com", name="Alice")
```

```sql
ON CONFLICT ("email") WHERE deleted_at IS NULL
DO UPDATE SET "name" = EXCLUDED.name
WHERE users.updated_at < now()
```

SQLite 不支持 `ON CONFLICT` 里的 partial 索引谓词，所以这个形式
在最后时刻被拒绝。

### 和 `insert` / `insert_many` 组合

`on_conflict` 对三种插入方法都工作：

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).insert([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])
```

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.nothing(),
).insert_many(rows, columns=["id", "name"])
```

对 `insert`（单语句多 `VALUES` 行），冲突子句作用于整条语句，这
正是 PostgreSQL 和 SQLite 期望的。对 `insert_many`（每行一次
`execute`），子句独立作用于每行。

### 和 `returning` 组合

`returning` 和 `on_conflict` 可以任意顺序：

```python
cur.users.returning("id").on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(id=1, name="Alice")

cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).returning("id").append(id=1, name="Alice")
```

两者生成同一语句。结果遵循通常的 `returning` 规则（见
[API 参考](api.md#tablebuilder--insert)）。

## MySQL：`on_duplicate`

MySQL 的 upsert 形状不同。没有冲突目标——子句在**任何**重复键
上触发——也没有 `DO NOTHING`。builder 反映这一点：

```python
cur.users.on_duplicate(update={"name": cur["VALUES(name)"]}).append(
    id=1, name="Alice",
)
```

```sql
INSERT INTO `users` (`id`, `name`)
VALUES (%s, %s)
ON DUPLICATE KEY UPDATE `name` = VALUES(name)
```

### 赋值

`update` 参数是列名到值的 mapping。值可以是普通 Python 值（绑为
参数）或表达式：

```python
cur.users.on_duplicate(update={"seen": 0, "name": cur["VALUES(name)"]}).append(...)
```

```sql
ON DUPLICATE KEY UPDATE `seen` = %s, `name` = VALUES(name)
```

`VALUES(col)` 函数指本来会为 `col` 插入的值。写成 `Expr`，因为
justorm 不特殊处理它。

MySQL 8.0.19 及以后弃用 `VALUES(col)`，推荐行别名：

```python
cur.users.on_duplicate(update={"name": cur["new.name"]}).append(...)
```

justorm 不自动加别名；想要新形式就自己写。两种拼法在 justorm
看来都是 `Expr` 里的字符串。

### 没有 `DO NOTHING`

MySQL 没有 `DO NOTHING`。想要"插入或忽略"就用 `INSERT IGNORE`
——justorm 不建模——或把某列更新成它自己：

```python
cur.users.on_duplicate(update={"id": cur["id"]}).append(id=1, name="Alice")
```

### 和 `insert` / `insert_many` 组合

`on_duplicate` 和 `on_conflict` 一样对 `append`、`insert`、
`insert_many` 工作：

```python
cur.users.on_duplicate(update={"seen": 0}).insert(
    [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
)
```

### 和 `returning` 组合

MySQL 不支持 `RETURNING`，所以 `on_duplicate` 配
`.returning(...)` 在终端方法运行时抛 `JustormDialectError`。
`on_duplicate` 子句本身没问题；MySQL 拒绝的是 `RETURNING`。

## SQL Server / Oracle：都不支持

两者都用 `MERGE`：

```sql
MERGE INTO users AS t
USING (VALUES (1, 'Alice')) AS s (id, name)
ON t.id = s.id
WHEN MATCHED THEN UPDATE SET name = s.name
WHEN NOT MATCHED THEN INSERT (id, name) VALUES (s.id, s.name);
```

justorm 不建模 `MERGE`。用 `cur.query(...)` 写原生 SQL：

```python
cur.query(
    """
    MERGE INTO users AS t
    USING (VALUES (%s, %s)) AS s (id, name)
    ON t.id = s.id
    WHEN MATCHED THEN UPDATE SET name = s.name
    WHEN NOT MATCHED THEN INSERT (id, name) VALUES (s.id, s.name)
    """,
    [1, "Alice"],
)
```

```python
# Oracle
cur.query(
    """
    MERGE INTO users t
    USING (SELECT :p1 AS id, :p2 AS name FROM dual) s
    ON (t.id = s.id)
    WHEN MATCHED THEN UPDATE SET t.name = s.name
    WHEN NOT MATCHED THEN INSERT (t.id, t.name) VALUES (s.id, s.name)
    """,
    {"p1": 1, "p2": "Alice"},
)
```

## 跨方言错误

在 MySQL 上用 PostgreSQL / SQLite 的 upsert，或反过来，都在最后
时刻被拒绝：

```python
cur.users.on_conflict(do=cur.sql.nothing()).append(id=1)
# PostgreSQL / SQLite: 没问题
# MySQL: append() 跑时抛 JustormDialectError
```

```python
cur.users.on_duplicate(update={"name": "x"}).append(id=1)
# MySQL: 没问题
# PostgreSQL / SQLite: append() 跑时抛 JustormDialectError
```

理由：调用的**形状**取决于方言，所以提前失败没意义：写方言可移植
代码的用户会自己 guard。

## `cur.sql` 说明

`cur.sql` 是只给 `on_conflict` 用的小命名空间。它有四/五个入口：

| 调用                            | 生成                                         |
| ------------------------------- | -------------------------------------------- |
| `cur.sql.nothing()`             | `DO NOTHING` 动作                            |
| `cur.sql.update(**kwargs)`      | `DO UPDATE SET ...` 动作                     |
| `cur.sql.columns(*names)`       | `ON CONFLICT ( ... )` 目标                   |
| `cur.sql.constraint(name)`      | `ON CONFLICT ON CONSTRAINT name` 目标        |
| `cur.sql.where(...)`            | 不完整子句；必须以目标或 `.update(...)` 结尾 |

`cur.sql.where(...)` 后面可以跟 `.columns(...)`（索引谓词形式）或
`.update(...)`（更新条件）。两者不能混在同一个
`cur.sql.where(...)` 上：

```python
cur.sql.where(cur["deleted_at IS NULL"]).columns("email")     # 目标
cur.sql.where(cur["users.updated_at < now()"]).update(...)    # 更新条件
```

`cur.sql.nothing()`、`cur.sql.columns(...)`、
`cur.sql.constraint(...)` 是终端。后面不能接 `.where(...)`。

## 汇总

| 你想要……                                     | PostgreSQL / SQLite                                  | MySQL                                            |
| -------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------ |
| 插入，冲突时忽略                             | `on_conflict(do=cur.sql.nothing())`                  | `on_duplicate(update={...})`（把某列更新成它自己） |
| 插入，在特定键上更新                         | `on_conflict(on=cur.sql.columns("id"), do=cur.sql.update(...))` | `on_duplicate(update={...})`（任何重复键） |
| 插入，在命名约束上更新                       | `on_conflict(on=cur.sql.constraint("name"), do=...)` | n/a                                              |
| 插入，只在条件成立时更新                     | `do=cur.sql.where(...).update(...)`                  | 不支持；用触发器或后续语句                       |
| 插入，在 partial 索引冲突时更新              | `on=cur.sql.where(...).columns(...)`                 | n/a                                              |
| 取回插入/更新的行                            | `.returning(...)`                                    | MySQL 不支持                                     |

## 另见

- [方言](dialects.md#upsert) 看并排比较。
- [API 参考](api.md#tablebuilder--upsert) 看方法签名。
- [安全](security.md) 看 `cur[...]` 内容的规则。
