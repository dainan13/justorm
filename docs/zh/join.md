# JOIN

justorm 的 join 支持刻意做小。它覆盖人们真正会写的 join——
inner、left、right、full、cross——并要求你说清你的意思，而不是
从 `where` 子句里猜。

join 从主表开始，链式 `.join`（及其别名）：

```python
cur.users.join(cur.orders, on=cur.users["id"] == cur.orders["user_id"]).select()
```

```sql
SELECT * FROM "users"
JOIN "orders" ON "users"."id" = "orders"."user_id"
```

这一页描述各部件、规则，以及 justorm 刻意不做的事。

## join 的形状

每个 join 有三部分：

1. **右表** —— 表（或别名表，或别名子查询）。`.join(...)` 的第一个
   位置参数。
2. **条件** —— `on=<condition>` 或 `using=<columns>`。二选一，
   cross join 例外。
3. **类型** —— inner（默认）、left、right、full、cross。

```python
cur.users.join(
    cur.orders,                                    # 右表
    on=cur.users["id"] == cur.orders["user_id"],   # 条件
    how="left",                                    # 类型
)
```

同一 join 也可以用对应的便捷方法：

```python
cur.users.left_join(cur.orders, on=cur.users["id"] == cur.orders["user_id"])
```

`how=` 和类型化方法（`left_join(..., how="right")`）混用会报错。

## 条件：`on=` 还是 `using=`

`on=` 收一个 [`Condition`](expr.md#条件)——表达式比较运算符产生的
任何东西：

```python
cur.users.join(cur.orders, on=cur.users["id"] == cur.orders["user_id"])
cur.users.join(cur.orders, on=(cur.users["id"] == cur.orders["user_id"])
                                & (cur.orders["paid"] == True))
```

`using=` 收一个两边共有的列名序列：

```python
cur.users.join(cur.orders, using=("user_id",))
```

```sql
JOIN "orders" USING ("user_id")
```

两者互斥。非 cross join 同时给或都不给会报错：

```python
cur.users.join(cur.orders)                                   # 报错
cur.users.join(cur.orders, on=..., using=("user_id",))       # 报错
```

`using` 在两边的列名确实相同时方便。不同名就用 `on`：

```python
cur.users.join(cur.orders, on=cur.users["id"] == cur.orders["buyer_id"])
```

## join 类型

`how` 参数接受五个值：

| `how`     | SQL            |
| --------- | -------------- |
| `"inner"` | `JOIN`         |
| `"left"`  | `LEFT JOIN`    |
| `"right"` | `RIGHT JOIN`   |
| `"full"`  | `FULL JOIN`    |
| `"cross"` | `CROSS JOIN`   |

`"inner"` 是默认值。

便捷方法：

```python
cur.users.inner_join(cur.orders, on=...)
cur.users.left_join(cur.orders, on=...)
cur.users.right_join(cur.orders, on=...)
cur.users.full_join(cur.orders, on=...)
cur.users.cross_join(cur.orders)
```

SQLite 3.39 之前没有 `RIGHT JOIN` 或 `FULL JOIN`。justorm 原样传，
所以错误来自 SQLite 本身，在运行时。

SQL Server 支持 `LEFT JOIN`、`RIGHT JOIN`、`FULL JOIN`、`CROSS
JOIN`、`INNER JOIN`。都可用。

Oracle 支持所有这些。

## cross join

cross join 没有条件：

```python
cur.users.cross_join(cur.regions).select()
```

```sql
SELECT * FROM "users" CROSS JOIN "regions"
```

给 cross join 传 `on=` 或 `using=` 会报错。

## 多个 join

join 是链式的。每次 `.join(...)` 追加到前一个：

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

join 是左结合的，不加括号。要改分组——实际中很少见——用
`where_raw` 或子查询。

## 别名

主表可以用 `.as_` 起别名：

```python
u = cur.users.as_("u")
o = cur.orders.as_("o")
u.join(o, on=u["id"] == o["user_id"]).select()
```

```sql
SELECT * FROM "users" AS "u"
JOIN "orders" AS "o" ON "u"."id" = "o"."user_id"
```

`u` 和 `o` 是 builder，不是字符串。`u["id"]` 生成一个渲染为
`"u"."id"` 的 `ColumnExpr`。不加别名时，同样的表达式渲染为
`"users"."id"`。

别名主要在以下场合有用：

- 同一张表在一次查询里出现两次。
- 你想要更短的列引用。
- 你 join 的是一个子查询（见下）。

### 只给右边起别名，主表不起

两边可以独立别名：

```python
cur.users.join(cur.orders.as_("o"), on=cur.users["id"] == cur.orders["id"])
```

这里 `cur.users` 保持它的名字，`cur.orders.as_("o")` 只用于
join 目标。条件必须引用别名表达式：

```python
o = cur.orders.as_("o")
cur.users.join(o, on=cur.users["id"] == o["user_id"])
```

否则 `cur.users["id"] == cur.orders["id"]` 会生成对**未别名**的
`orders` 的引用，而它不在作用域里。

### 别名复用

别名就是名字。复用是你的事：

```python
a = cur.users.as_("t")
b = cur.orders.as_("t")     # 错；你有了两个 "t"
```

justorm 不检测这个。数据库会报。

## 子查询作为 join 目标

子查询由 `.select_subquery(...)` 生成：

```python
sub = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"})
```

子查询 join 前**必须**别名：

```python
s = sub.as_("s")
cur.users.join(s, on=cur.users["id"] == s["user_id"]).select()
```

```sql
SELECT * FROM "users"
JOIN (SELECT "user_id" FROM "orders" WHERE "total" > %s) AS "s"
     ON "users"."id" = "s"."user_id"
```

更多见 [子查询](subquery.md)。

## 子查询作为主表

子查询也可以作为起点：

```python
s = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"}).as_("s")
s.join(cur.users, on=s["user_id"] == cur.users["id"]).select()
```

```sql
SELECT * FROM (SELECT "user_id" FROM "orders" WHERE "total" > %s) AS "s"
JOIN "users" ON "s"."user_id" = "users"."id"
```

## join 后的 `WHERE`

`.where(...)` 在 join 后和 join 前一样工作，但你现在要担心歧义。
出现在多个被 join 表里的列名必须限定：

```python
# 如果 "users" 和 "orders" 都有 "id" 列，有歧义
cur.users.join(cur.orders, on=...).where(id=1)

# 无歧义
cur.users.join(cur.orders, on=...).where(cur.users["id"] == 1)
```

justorm **不**试图检测这个。错误来自数据库。这符合"无 schema、
信任服务端"的哲学。

`.where(...)` 的关键字参数总被引用成裸标识符，所以带不了表前缀：

```python
cur.users.join(...).where(id=1)       # "id" = %s   — 有歧义
cur.users.join(...).where(cur.users["id"] == 1)   # "users"."id" = %s
```

## join 后的 `select`

`select` 里的列引用同理。`set` / `list` / `tuple` 形式接受普通
字符串（裸列名）或 `ColumnExpr` 对象（限定引用）：

```python
cur.users.join(cur.orders, on=...).select({cur.users["name"], cur.orders["total"]})
cur.users.join(cur.orders, on=...).select({"name", "total"})    # 两表都有时歧义
```

## join 后的 `ORDER BY`

同样规则：

```python
cur.users.join(cur.orders, on=...).orderby(cur.users["name"]).select()
cur.users.join(cur.orders, on=...).orderby("name").select()
```

## `JOIN` 配 `for_update`

PostgreSQL 上 `SELECT ... FOR UPDATE` 通常锁 `FROM` 里的每一张表。
只锁一张表，用 `FOR UPDATE OF table` 形式。justorm **不**支持
`OF`；需要就用 `where_raw`：

```python
cur.users.join(cur.orders, on=...).where_raw("1=1").select(for_update=True)
# 需要就 where_raw 追 "FOR UPDATE OF users"
```

这是刻意的省略。`FOR UPDATE OF` 罕见，justorm 更愿意留着逃生舱，
而不是建一个半吊子的抽象。

## 不支持的东西

justorm 不提供：

- **LATERAL join**。需要就用 `where_raw`。
- **NATURAL join**。用 `using=...` 或 `on=...`；`NATURAL` 的含义
  取决于 schema，而 justorm 不知道 schema。
- **另一种拼法的 `FULL OUTER JOIN`**。`how="full"` 发出
  `FULL JOIN`，PostgreSQL、SQLite、SQL Server、Oracle 都理解为
  `FULL OUTER JOIN`。MySQL 没有，错误来自 MySQL。
- **逗号 join**（`FROM a, b`）。用 `cross_join` 或显式 `on`；
  逗号形式已经有害二十年了。
- **join 提示**（`/*+ ... */`）。用 `where_raw` 或 `cur[...]`。
- **改变结合性的括号 join 组**。发出的 SQL 总是左结合、无括号。

模式是：justorm 覆盖你日常手写的大部分，其余留着逃生舱。

## 常见模式

### 数关联表的行数

```python
o = cur.orders.as_("o")
cur.users.left_join(o, on=cur.users["id"] == o["user_id"]) \
    .select({cur.users["id"], cur["count(o.id) AS n"]})
```

`group_by` 不在 justorm 里；需要就用 `where_raw`，或用普通
`Expr` `select` 聚合：

```python
cur.users.left_join(o, on=...).select({cur.users["id"], cur["count(o.id) AS n"]})
```

### 过滤右边

属于右边的过滤条件放到 `on` 条件里，而不是 `.where(...)`，才能
保持 left-join 语义：

```python
# 保留没有匹配 order 的 user（LEFT JOIN 语义）
cur.users.left_join(cur.orders, on=(cur.users["id"] == cur.orders["user_id"])
                                    & (cur.orders["paid"] == True))

# 丢掉没有匹配 order 的 user
cur.users.left_join(cur.orders, on=cur.users["id"] == cur.orders["user_id"]) \
    .where(cur.orders["paid"] == True)
```

这是标准 SQL 语义；justorm 不改。

### 自连接

```python
m = cur.users.as_("m")
e = cur.users.as_("e")
m.join(e, on=m["manager_id"] == e["id"]).select({m["name"], e["name"]})
```

## 另见

- [API 参考](api.md#tablebuilder--join) 看方法签名。
- [子查询](subquery.md) 看 `select_subquery` 和 `.as_`。
- [表达式](expr.md) 看 `ColumnExpr` 和 `Condition`。
- [方言](dialects.md) 看各数据库关于 `FOR UPDATE`、`RIGHT JOIN`
  之类的说明。
