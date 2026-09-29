# 安全

justorm 是构建器，不是沙盒。它转义它被要求转义的东西，其余留给
你。这一页精确描述这条线在哪，好让你推理。

短版本：

- **你传给 builder 的值总是绑为参数。** 你不能通过值不小心注入
  SQL。
- **列名和表名被引用为标识符。** 只要你在期望名字的地方传名字，
  你就不能通过名字不小心注入 SQL。
- **`cur["..."]` 原样发出。** 不要把不可信输入放那里。原样片段
  里面没有转义。
- **`where_raw(sql, params)` 把 `sql` 当原样、`params` 当值。**
  切分就是你写的。

这就是整个模型。这一页其余部分解释为什么，以及哪里是尖角。

## 什么被转义

### 值

justorm 放进语句的每个值——来自关键字参数、dict、tuple、list，
或表达式的右侧——都绑为**参数**。不内联到 SQL 文本。

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

因为值随 SQL 一起走，而不是在 SQL 里，值里的引号、注释标记、语句
终止符都无法改变语句含义。其余由驱动处理。

### 标识符

justorm **作为名字**收到的列名和表名按方言的标识符引用规则加
引号。名字里的引号字符按那些规则双写。

```python
cur.users.where(**{user_input: 1}).select()
# -> WHERE "name; DROP TABLE users" = %s   (params: [1])
```

值 `"name; DROP TABLE users"` 被当作单个标识符。如果它碰巧含
`;`，那个 `;` 在引号里的标识符内，没有意义。

期望名字的地方是：

- `.where(...)`、`.where_in(...)` 及其同类方法的**关键字参数**，
- `.where_in(...)` 及其同类方法的 mapping 的 **`str` key**，
- `cur.<table>` 和 `cur.table("...")`，
- `cur.<table>["col"]`，
- `select(...)` 的 `set` / `list` / `tuple` 参数，
- join 的 `using=(...)`，
- `cur.sql.columns(...)` 和 `cur.sql.constraint(...)` 的参数。

### 标识符和值的切分

在每个同时收名字和值的方法里，切分是**语法上的**，不是语义上的。
名字是 key；值是值。

```python
cur.users.where(**{name: value})       # name 是标识符，value 是参数
cur.users.where_in({name: [values]})   # name 是标识符，values 是参数
cur.users.update(**{name: value})      # name 是标识符，value 是参数
```

如果名字来自用户输入，它仍被引用为标识符，所以无法逃出引号。它
**能**做的是命名一个不存在的列，或用户本不该看到的列——但那是
授权问题，不是引用问题。见下面 [授权](#授权)。

## 什么不被转义

### `cur["..."]`

`cur["..."]` 的内容**原样**发出。里面没有引用、没有双写、没有
占位符替换。这是刻意的：它是逃生舱，而逃生舱必须让你逃出去。

```python
cur["lower(name)"]            # 发出：lower(name)
cur["count(*) AS n"]          # 发出：count(*) AS n
cur["name = 'x'"]             # 发出：name = 'x'  — 'x' 被内联
```

四个禁用序列（`;`、`--`、`/*`、`*/`）在构造时被拒绝，阻止最常见
的事故：

```python
cur["name; DROP TABLE users"] # JustormValueError
```

但这是**防手滑**，**不是**安全边界。SQL 是丰富语言，而这个守卫
是四个字符串长，有很多写法它抓不到。

**不要把不可信输入放进 `cur["..."]`。** 不在引号里，不在你自己
转义后。如果你需要把函数名和值组合，用运算符形式，它把值绑为
参数：

```python
cur["lower("] + cur["name"] + cur[")"]   # 原样，无参数——别这么写
```

没有一种 builder 形式能把 Python 字符串变成
`lower(<quoted identifier>)` 而不加引号，所以诚实的建议是：需要
`lower(name)` 就写 `cur["lower(name)"]`，把整个东西当可信代码。
它就是干这个的。

### `where_raw(sql, params)`

`where_raw` 把输入切两半：

- `sql` 原样，
- `params` 是绑为参数的值序列。

```python
cur.users.where_raw("length(name) > %s", [5]).select()
# -> WHERE length(name) > %s   (params: [5])
```

把值插入到 `sql` 里就是你自己负责：

```python
cur.users.where_raw(f"length(name) > {n}", [])   # 别这么写
cur.users.where_raw("length(name) > %s", [n])    # 安全形式
```

`where_raw` **不**翻译占位符。写你的驱动期望的那个：psycopg、
psycopg2、PyMySQL、pymssql 用 `%s`，sqlite3 用 `?`，Oracle 用
`:name`。见 [方言](dialects.md#占位符)。

### 传给驱动的裸 SQL

`cur.execute(...)` 是驱动自己的方法。justorm 不碰它。按驱动文档
用它；psycopg 之类就是参数化查询，不是 f-string。

## `%` 字符

psycopg、psycopg2、PyMySQL、pymssql 用 `%s` 占位符。SQL 文本里
的字面 `%` 必须双写，驱动才不会把它误当占位符。

justorm 在这些方言上对 `cur["..."]` 内容和 `where_raw` 片段双写
`%`。SQLite 用 `?`，Oracle 用命名占位符 `:p<hex>`，不需要双写，
所以 justorm 在那两个方言上什么都不做。

```python
cur["name LIKE 'a%'"]        # PG/MySQL/SQL Server 上发出 name LIKE 'a%%'
                             # SQLite/Oracle 上发出 name LIKE 'a%'
```

你写你的 SQL。不要自己写 `%%`，也不要指望 `cur["..."]` 里的
`%s` 会被绑参数：没有参数会被绑，因为 `cur["..."]` 不收。

## 授权

正确引用标识符和授权访问不是一回事。如果列名来自请求参数，用户
能请求本不该看到的列：

```python
col = request.args["col"]              # 不可信
cur.users.select({col})                # 运行 SELECT "col" FROM "users"
```

justorm 会乐意引用 `"secret_token"` 并把值给你。那是不是问题，
是你应用的决定，不是 builder 的。

一般规则：**引用你该引用的，授权你该授权的，永远不要把二者混
为一谈。**

## SQL 注入实操

query builder 里 SQL 注入的发生方式有：

1. **把值内联到 SQL 文本。** justorm 把值绑为参数，所以通过
   builder 的值位置不会发生。
2. **把标识符内联到 SQL 文本而不加引号。** justorm 在期望名字的
   地方都加引号。逃生舱（`cur["..."]`）不加，但那正是逃生舱的
   意义。
3. **信任用字符串拼接构造的 `where_raw` 片段。** 把值放第一个
   参数而不是第二个时，`where_raw` 帮不了你。用参数。
4. **把用户输入拼接到 `cur["..."]` 字符串里。** 别。
5. **信任驱动做它不做的事。** 比如指望 SQLite 拒绝一个 `%s`
   占位符；它不会，因为 `%s` 在那里不是占位符，是字面量。写你的
   驱动期望的占位符。

避开 (1) 到 (5)，你就避开了 SQL 注入。

## 四个禁用序列

`cur["..."]` 拒绝这些子串：

| 子串 | 原因           |
| ---- | -------------- |
| `;`  | 语句分隔符     |
| `--` | 行注释         |
| `/*` | 块注释开始     |
| `*/` | 块注释结束     |

这是**便利**，不是保证。它抓最常见的"我把两条语句粘成一条字符串"
错误。它抓不到：

- 写成 `chr(59)` 或通过其他构造的 `;`，
- 没有 `;` 也危险的 SQL（比如读不该读的表的子查询），
- 写成 `#`（MySQL）的注释——那些不被拒绝，
- 任何 justorm 没想到的。

别依赖守卫。把 `cur["..."]` 当作 `cur.execute("...")` 调用：当
可信代码。

## `where_raw` 也不是沙盒

`where_raw` 不解析、不校验它收到的 SQL。它把它切成"SQL"和
"params"并把两个都交给驱动。

```python
cur.users.where_raw("1=1 OR 1=1", []).select()   # 返回所有行
```

这是 `where_raw` 的合法用法。如果你自己构造字符串，它也是恶意
输入能做的事。

## 日志

justorm 不记任何东西。要看生成的 SQL，用驱动自己的日志，或自己
记 `cur.execute` 调用。一个常见模式是薄包装：

```python
class LoggingCursor(justorm.psycopg.Cursor):
    def _execute(self, sql, params):
        logger.debug("SQL: %s  PARAMS: %r", sql, params)
        super()._execute(sql, params)
```

`_execute` 和 `_execute_and_fetch` 是 builder 把 SQL 交给驱动的
两个地方。两者都是内部接口的稳定部分；覆盖它们是给库插桩的受支持
方式。

如果记 SQL，记住绑参数可能含敏感数据（密码、token、个人信息）。
占位符风格意味着值不在 SQL 字符串里——这对安全是好事——但你在
记 `params` 时它们会出现在那里。

## 参数和类型

justorm 把值原样传给驱动。驱动决定怎么适配。这意味着：

- 驱动不知道如何适配的值会从驱动抛错，不是从 justorm。
- 在不同方言上适配不同的值（比如带时区的 `datetime`、或
  `Decimal`）会按驱动和数据库的决定行为，不按 justorm 的决定。

justorm 不试图跨方言规范化类型。常见映射见
[方言](dialects.md#类型适配)。

## Oracle 的命名占位符

python-oracledb 用命名占位符。justorm 的 Oracle 分支给每个
占位符分配随机名 `:p<hex>`，并把参数作为 dict 传给驱动。就安全
而言：

- 名字是 `os.urandom(4).hex()`，密码学随机，不是可预测计数器。
- 值仍在 dict 里，仍绑为参数。`cur["..."]` 的规则不变：原样片段
  仍然原样。

随机名不改变安全模型。它们改变的是"占位符名字从哪来"。

## 汇总

| 你写                                | 被转义？ | 对不可信输入安全？ |
| ----------------------------------- | -------- | ------------------ |
| `cur.users.where(name=value)`       | 是       | 是                 |
| `cur.users.where(**{name: value})`  | 是       | 是                 |
| `cur.users["name"]`                 | 是       | 是（名字不是值）   |
| `cur.users.select({name})`          | 是       | 是（名字不是值）   |
| `cur["..."]`                        | **否**   | **否**             |
| `where_raw("... %s ...", [value])`  | 是       | 是                 |
| `where_raw(f"... {value} ...", [])` | **否**   | **否**             |
| `cur.execute("...")`                | **否**   | **否**（除非驱动做） |

如果一段数据不可信，它只能出现在第三列是"是"的位置。其余是你
的责任。

## 另见

- [表达式](expr.md) 看 `cur["..."]` 和 `cur.<table>["col"]` 的
  区别。
- [API 参考](api.md) 看方法签名。
- [方言](dialects.md#占位符) 看 `%s` vs `?` vs `:name` 规则。
- [迁移](migration.md) 看把裸 SQL 移进 builder 而不丢安全。
