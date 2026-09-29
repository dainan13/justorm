# 表达式

justorm 大部分操作的是 Python 值和列名。当你需要写 builder 没有
方法的 SQL——函数调用、`CASE`、cast、不寻常的比较——你拿起一个
**表达式**。这一页讲两类表达式、它们做什么，以及边界在哪。

两类是：

- `Expr`，由 `cur["..."]` 产生——原样 SQL 片段。
- `ColumnExpr`，由 `cur.<table>["col"]` 产生——加引号的列引用。

名字相似；行为非常不同。区别很重要。

## `Expr` —— `cur["..."]`

`cur["..."]` 把给定字符串包成 `Expr`。字符串**原样**发出 SQL。
这是逃生舱，也是 justorm 里唯一一处你亲自负责 SQL 文本。

```python
cur["lower(name)"]           # lower(name)
cur["now()"]                 # now()
cur["count(*) AS n"]         # count(*) AS n
cur["CASE WHEN a > 0 THEN 1 ELSE 0 END"]
```

### 什么会被拒绝

构造时，`cur["..."]` 拒绝四个序列：

| 序列 | 为什么                     |
| ---- | -------------------------- |
| `;`  | 防多语句                   |
| `--` | 防行注释                   |
| `/*` | 防块注释开始               |
| `*/` | 同上                       |

这是**防手滑的安全网**，不是安全边界。它阻止你不小心把两条语句
粘成一条。它**不**让用户输入变安全。见 [安全](security.md)。

```python
cur["name"]                  # fine
cur["name; DROP TABLE users"] # JustormValueError
cur["name -- comment"]       # JustormValueError
```

如果你需要 SQL 里的分号或注释，用
[`where_raw`](api.md#where_rawsql-paramsnone) 加驱动的
`execute`，或者把工作拆成两条语句。

### `Expr` 上的运算符

`Expr` 支持算术和比较运算符。右侧是 Python 值时总是绑为参数——
从不内联：

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

右侧是另一个 `Expr` 时，比较不加参数发出：

```python
cur["a"] == cur["b"]         # Condition: (a = b), no params
cur["a"] > cur["b"]          # Condition: (a > b)
```

这就是**参数化**和**原样**的区别：

```python
cur["age + 1"]               # 原样：age + 1
cur["age"] + 1               # 参数化：(age + %s), params [1]
```

两者都有用。只有第二种保护值不被内联。

### `None` 和比较

右侧是 `None` 的比较变成 `IS NULL` 或 `IS NOT NULL`：

```python
cur["deleted_at"] == None    # Condition: (deleted_at IS NULL)
cur["deleted_at"] != None    # Condition: (deleted_at IS NOT NULL)
```

注意这是**只在比较里**的行为。赋值里（`update`、`insert`、
`on_conflict` 的 `do=cur.sql.update`），`None` 意思是 `= NULL`：

```python
cur.users.where(id=1).update(deleted_at=None)
# SET "deleted_at" = %s, params [None]
```

### 嵌套表达式

算术按你预期嵌套：

```python
cur["a"] + cur["b"] * 2      # (a + (b * %s)), params [2]
```

括号是 justorm 加的，不是你加的，且总是正确的。表达式树就是你
写的；SQL 就是你得到的。

### 在 `select` 里用 `Expr`

`Expr` 项可以出现在 `select` 的列列表里：

```python
cur.users.select({cur["id"], cur["lower(name) AS lname"]})
# SELECT "id", lower(name) AS lname FROM "users"
```

单个 `Expr` 作为唯一参数时产生标量，不是 dict：

```python
cur.users.select(cur["count(*)"])    # [3]
```

## `ColumnExpr` —— `cur.<table>["col"]`

`cur.users["name"]` 创建一个 `ColumnExpr`。它和 `Expr` 相似，但
它知道表和列名，所以两个都能按方言加引号：

```python
cur.users["name"]            # "users"."name"
cur.users["name"] == "Alice" # Condition: ("users"."name" = %s), params ["Alice"]
cur.users["name"] + " x"     # ColumnExpr: ("users"."name" + %s)
```

引号是方言特定的：

- PostgreSQL、SQLite、Oracle：`"users"."name"`
- MySQL：`` `users`.`name` ``
- SQL Server：`[users].[name]`

引号不用你写。如果列名本身含引号字符，按方言规则双写。

### `cur.<table>["*"]` 被拒绝

通配符不是列名，justorm 不假装它是：

```python
cur.users["*"]               # JustormValueError
cur["users.*"]               # 原样：users.*
```

`select` 里想要 `users.*`，用 `Expr` 形式。

### 别名：`ColumnExpr.as_(alias)`

`as_` 方法返回一个携带别名的 `Expr`，所以结果集列被正确命名：

```python
cur.users["name"].as_("n")    # "users"."name" AS "n"
```

别名表达式是普通 `Expr`（不再需要表知识），但它为 `select` 机制
记住了别名：

```python
cur.users.select({cur.users["name"].as_("n")})
# SELECT "users"."name" AS "n" FROM "users"
# [{"n": "Alice"}, ...]
```

这就是多表查询里解决名字冲突的方式：

```python
cur.users.join(cur.orders, on=...).select({
    cur.users["id"].as_("user_id"),
    cur.orders["id"].as_("order_id"),
})
```

## 条件

`Condition` 是比较运算符产生的东西。它是你传给 `.where(...)` 的，
`where_raw` 直接收 SQL 文本，join 通过 `on=` 收。

条件用三个运算符组合：

```python
a = cur.users["age"] > 18
b = cur.users["active"] == True

a & b         # AND: ((age > %s) AND (active = %s))
a | b         # OR:  ((age > %s) OR (active = %s))
~a            # NOT: (NOT (age > %s))
```

### 加括号

Python 运算符优先级把 `&` 和 `|` 放在比较**之上**。不加括号时，
这：

```python
cur["a"] > 1 & cur["b"] > 2
```

解析成：

```python
cur["a"] > (1 & cur["b"]) > 2
```

不是你的意思。组合时永远给比较操作数加括号：

```python
(cur["a"] > 1) & (cur["b"] > 2)
```

justorm 在 Python 里改不了这个；语言级规则。搞错通常会产生
`&` 运算符的 `TypeError`，但不总是。

### 条件没有自己的 SQL

`Condition` 不是字符串。它是抽象节点。它的 SQL 在包住它的语句
渲染时生成，这就是为什么条件可以跨方言复用：

```python
cond = cur.users["age"] > 18
# ... 后来，在 MySQL cursor 上 ...
cur.users.where(cond).select()
```

`Condition` 持有结构，不是方言特定文本。`Condition.params` 暴露
绑定参数列表，调试用：

```python
(cur.users["age"] > 18).params       # [18]
(cur.users["name"] == "Alice").params # ["Alice"]
```

### `where` 配关键字参数

`.where(...)` 内，关键字参数是裸列名等值条件的简写：

```python
cur.users.where(age=30)              # "age" = %s, params [30]
cur.users.where(age=None)            # "age" IS NULL
```

key 总是裸列名，被方言加引号。要限定列，用 `ColumnExpr` 形式：

```python
cur.users.where(cur.users["age"] == 30)
```

同一次调用里既传位置 `Condition` 又传关键字参数是错误。

### `where` 配 dict

`.where_in`、`.where_not_in`、`.where_between`、`.where_like`、
`.where_ilike` 接受关键字参数或 mapping。mapping 可以用 `str`
key（加引号成标识符）或 `Expr` key（原样发出）：

```python
cur.users.where_in(id=[1, 2, 3])                  # "id" IN (%s, %s, %s)
cur.users.where_in({"id": [1, 2, 3]})             # 同上
cur.users.where_in({cur["lower(name)"]: ["a"]})   # lower(name) IN (%s)
cur.users.where_in({cur.users["id"]: [1, 2, 3]})  # "users"."id" IN (%s, %s, %s)
```

同一次调用里既传 mapping 又传关键字参数是错误。

## 用哪个

| 你想要……                                 | 用                            |
| ---------------------------------------- | ----------------------------- |
| 普通列                                   | `cur.table["col"]`            |
| 带别名的列                               | `cur.table["col"].as_("x")`   |
| 函数调用                                 | `cur["lower(name)"]`          |
| SQL 关键字（`DEFAULT`、`NULL`）          | `cur["DEFAULT"]`              |
| 比较                                     | `cur.x == 1`、`cur.t["a"] > cur.t["b"]` |
| 逻辑组合                                 | `a & b`、`a | b`、`~a`        |
| `IN` 列表                                | `where_in(...)`               |
| `BETWEEN`                                | `where_between(...)`          |
| `LIKE`                                   | `where_like(...)`             |
| 其他                                     | `where_raw(...)`              |

最后一行很重要。justorm 的表达式词汇表刻意做小；逃生舱永远是
`where_raw`（条件）和 `cur[...]`（其他片段）。

## `%` 问题

PostgreSQL、MySQL、SQL Server 上驱动用 `%s` 占位符，意味着 SQL
文本里的字面 `%` 必须双写。justorm 对 `Expr` 内容和 `where_raw`
片段自动处理：

```python
cur["name LIKE 'a%'"]        # PostgreSQL/MySQL/SQL Server：发出 name LIKE 'a%%'
                             # SQLite/Oracle：发出 name LIKE 'a%'
```

你写你的 SQL；方言渲染器在驱动需要的地方双写百分号。唯一的例外
是你在 `cur[...]` 里自己写的 `%s`：

```python
cur["name LIKE %s"]          # 看起来像占位符，但没有参数可绑——别这么写
```

需要占位符就用收参数的方法（`where_raw`、`where_in`……）。见
[安全](security.md)。

## 一个完整例子

假设你要：

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

用 justorm：

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

参数是 `[18, True]`。`18` 和 `True` 被绑定；`'adult'` 和 `'minor'`
在字面 `Expr` 里，被内联——是你写的，你负责。规则见
[安全](security.md)。

## 另见

- [API 参考](api.md#表达式) 看方法签名。
- [安全](security.md) 看安全/不安全输入之间的边界。
- [方言](dialects.md#占位符) 看占位符和 `%` 规则。
- [迁移](migration.md) 看把裸 SQL 移进 builder。
