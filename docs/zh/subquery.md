# 子查询

子查询是"作为值用在另一个语句里的 `SELECT`"。justorm 在一个具体
位置支持子查询：**`FROM` 子句的来源**，也就是你可以 join 或从它
起始的表。

其他位置的子查询——`WHERE` 里、`IN` 右侧、`EXISTS` 参数——**不**
在 builder 里。用 [`where_raw`](api.md#where_rawsql-paramsnone)；
见下面[不支持](#不支持)。

## 创建子查询

在 `TableBuilder` 上调 `.select_subquery(...)` 而不是 `.select()`
来构建子查询：

```python
sub = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"})
```

`.select_subquery(...)` 是终端方法：它结束 builder 链。但和
`.select()` 不同，它**不执行**任何东西。它返回一个 `Subquery`
对象，持有生成的 SQL，可以嵌进外层查询。

参数和 `select` 一样——决定子查询暴露哪些列：

```python
cur.orders.select_subquery()                    # SELECT *
cur.orders.select_subquery({"user_id"})         # SELECT "user_id"
cur.orders.select_subquery(["user_id", "total"])  # 列有序
cur.orders.select_subquery(("user_id", "total"))  # 同上，这里不需要元组
```

`select` 的返回形状参数（`set` vs `list` vs `tuple` vs `str`）
只影响子查询的列在元数据里怎么命名。子查询不取，唯一重要的是
列表达式列表和它们的输出名。

## 给子查询起别名

`FROM` 子句里的每个子查询**必须**有别名。PostgreSQL、SQL Server、
Oracle 里 `FROM` 里没别名的子查询是语法错误；SQLite 和 MySQL
接受，但引用很别扭。justorm 统一要求别名：

```python
s = sub.as_("s")
```

`.as_` 返回一个新对象——别名——可以用作：

- `JOIN` 的右表，
- 查询的主表，
- 通过 `s["col"]` 作为 `ColumnExpr` 的来源。

`.as_` 是幂等的，意思是每次调用都返回一个新的别名；原 `sub` 不变。

## join 子查询

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

`s["user_id"]` 是一个 `ColumnExpr`，它的表是别名 `"s"`。渲染为
`"s"."user_id"`（MySQL 上是 `` `s`.`user_id` ``，SQL Server 上是
`[s].[user_id]`）。

通常的 join 规则适用：见 [JOIN](join.md) 关于 `on=` vs `using=`、
join 类型、left-join 过滤模式。

## 用子查询作为主表

别名也可以作为查询的起点：

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

别名对象支持和 `TableBuilder` 一样的 surface：`.join`、`.left_join`、
`.where`、`.orderby`、`.limit`、`.select`，等等。唯一区别是主表是
带括号的 `SELECT` 而不是表名。

## 不 join 直接从子查询 select

如果只想从子查询 select，主表形式就够了：

```python
s = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"}).as_("s")
s.select()
```

```sql
SELECT * FROM (SELECT "user_id" FROM "orders" WHERE "total" > %s) AS "s"
```

## 嵌套

子查询自然地嵌套，因为每次 `.select_subquery()` 都开一个新 builder：

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

深度只受数据库自身限制。

## 子查询里的列命名

子查询里的列引用和其他地方规则一样：`cur.orders["total"]` 在
子查询里用时渲染为 `"orders"."total"`。如果子查询的 `FROM` 本身
别名了，引用必须用别名：

```python
o = cur.orders.as_("o")
sub = o.where(o["total"] > 100).select_subquery({"user_id"})
```

`sub` 里，列是 `"o"."total"`，不是 `"orders"."total"`。

## 子查询的结果形状

`.select_subquery()` 不取行，所以 `select` 的返回形状参数（`set`
vs `tuple` vs `str`，以及 `key=`）没有意义并被忽略。只有列的选择
重要。

给 `select_subquery` 传 `key=` 允许但无效；调用不被拒绝，因为
同一个参数在 `.select()` 里有意义，而写一个既能构造子查询又能
构造查询的辅助函数时方便。

## 限制

### `WHERE` 里的子查询

不作为一等 builder 构造支持。用 `where_raw`：

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

`where_raw` 不翻译占位符，写你的驱动期望的那个（PostgreSQL、MySQL、
SQL Server 是 `%s`，SQLite 是 `?`，Oracle 是 `:name`）。见
[方言](dialects.md#占位符)。

### `EXISTS` / `IN` 作为 builder 构造

不支持。这个模式很常见，诱人，但变体太多（相关子查询、
`NOT EXISTS`、`ANY`/`ALL`……），而 raw 逃生舱就在那里。justorm
刻意保持小。

### `SELECT` 里的标量子查询

不作为一等构造支持。用 `cur[...]`：

```python
cur.users.select({
    cur["id"],
    cur["(SELECT count(*) FROM orders o WHERE o.user_id = users.id) AS n"],
})
```

这是原样 SQL。引号你自己负责，如果你传参数——**不能**，因为
`cur[...]` 不收参数。需要参数就用 `where_raw` 加 join，或回落到
驱动的 `execute`。

### `LATERAL`

不支持。用 `where_raw`。

### `UPDATE` / `DELETE` 里的子查询

不支持。用 `where_raw`：

```python
cur.users.where_raw(
    "id IN (SELECT user_id FROM orders WHERE total > %s)",
    [100],
).delete()
```

### `WITH`（公共表表达式）

不支持。用 `where_raw`，或通过驱动直接执行 CTE，把结果传回来。

## 和替代方案比较

没有 justorm 的子查询支持，同样的查询是：

```python
cur.execute("""
    SELECT * FROM users
    JOIN (
        SELECT user_id FROM orders WHERE total > %s
    ) AS s ON users.id = s.user_id
""", [100])
rows = cur.fetchall()
```

用 justorm：

```python
sub = cur.orders.where(cur.orders["total"] > 100).select_subquery({"user_id"})
s = sub.as_("s")
rows = cur.users.join(s, on=cur.users["id"] == s["user_id"]).select()
```

builder 版本更容易组合——子查询可以单独构造、复用、被周围代码
参数化——生成的 SQL 一样。

## 另见

- [JOIN](join.md) 看别名和 join 条件怎么工作。
- [表达式](expr.md) 看 `ColumnExpr` 和 `Condition`。
- [API 参考](api.md#子查询) 看 `select_subquery` 签名。
- [方言](dialects.md) 如果你在一个代码库里混用多个方言。
