# 方言

justorm **不**试图抹平 PostgreSQL、MySQL、SQLite、SQL Server、
Oracle 之间的差异。你连的是 MySQL，就写 `.on_duplicate(...)`；
连的是 PostgreSQL，就写 `.on_conflict(...)`。如果你的数据库没有某
个特性，justorm 会**在最后时刻**报错——终端方法运行时，不是构建
时。

这一页是这些差异的参考。和 [API 参考](api.md) 一起看，后者描述
公共 surface。

## 方言一览

| 模块                | 驱动                                                       | 数据库          |
| ------------------- | ---------------------------------------------------------- | --------------- |
| `justorm.psycopg`   | [psycopg](https://www.psycopg.org/psycopg3/) (v3)          | PostgreSQL      |
| `justorm.psycopg2`  | [psycopg2](https://www.psycopg.org/)                       | PostgreSQL      |
| `justorm.pymysql`   | [PyMySQL](https://pymysql.readthedocs.io/)                 | MySQL / MariaDB |
| `justorm.sqlite`    | `sqlite3`（标准库）                                         | SQLite 3        |
| `justorm.pymssql`   | [pymssql](https://pymssql.readthedocs.io/)                 | SQL Server      |
| `justorm.oracledb`  | [python-oracledb](https://python-oracledb.readthedocs.io/) | Oracle          |

`psycopg` 和 `psycopg2` 共用一个 renderer，它们发出的 SQL 语法完全
一样。区别在驱动层，不在 SQL 层，justorm 不做任何隐藏：每个都是
独立模块，各有各的 `Cursor` 类。

## 汇总表

| 特性                            | PostgreSQL | MySQL        | SQLite         | SQL Server   | Oracle        |
| ------------------------------- | ---------- | ------------ | -------------- | ------------ | ------------- |
| 标识符引号                      | `"col"`    | `` `col` ``  | `` `col` ``    | `[col]`      | `"col"`       |
| 占位符                          | `%s`       | `%s`         | `?`            | `%s`         | `:p<hex>`     |
| `RETURNING`                     | 是         | **否**       | 3.35+          | **否**       | **否**        |
| UPSERT                          | `ON CONFLICT` | `ON DUPLICATE KEY` | `ON CONFLICT`（部分） | **否**（用 `MERGE`） | **否**（用 `MERGE`） |
| `ON CONFLICT ... ON CONSTRAINT` | 是         | n/a          | **否**         | n/a          | n/a           |
| `ON CONFLICT ( ... ) WHERE ...` | 是         | n/a          | **否**         | n/a          | n/a           |
| `DISTINCT ON`                   | 是         | **否**       | **否**         | **否**       | **否**        |
| `ILIKE`                         | 是         | **否**       | **否**         | **否**       | **否**        |
| `FOR UPDATE` / `FOR SHARE`      | 是         | 8.0+         | **否**         | **否**       | 是            |
| `LIMIT` 无 `OFFSET`             | 是         | 是           | 是             | 是           | 是            |
| `OFFSET` 无 `LIMIT`             | 是         | **否**       | 是（3.30+）    | 是           | 是            |
| `VALUES` 里的 `DEFAULT`         | 是         | 是           | **否**         | 是           | **否**        |
| `RETURNING` / `OUTPUT` 输出     | `RETURNING` | —           | `RETURNING`    | `OUTPUT`     | `RETURNING INTO` |

**"是"/"否"** 是指 justorm 是否生成这段 SQL。有些特性数据库本身
有，但 justorm 不建模（比如 MySQL 的 `UPDATE ... LIMIT`、SQL
Server 和 Oracle 的 `MERGE`），一律在 API 层拒绝，需要用
`cur.query(...)` 走原生 SQL。

## 标识符引号

| 方言       | 示例                                     |
| ---------- | ---------------------------------------- |
| PostgreSQL | `"users"`、`"public"."users"`            |
| MySQL      | `` `users` ``、`` `mydb`.`users` ``      |
| SQLite     | `` `users` ``                            |
| SQL Server | `[users]`、`[dbo].[users]`               |
| Oracle     | `"users"`、`"schema"."users"`            |

引号通常不用自己写。`cur.users`、`cur.table("users")`、
`cur.users["name"]`、`.where(...)` 的关键字参数都走方言的标识符
渲染器。

`cur["..."]` 是例外：里面的内容原样发出，里面的引号自己负责。

### SQLite 用反引号

SQLite 的双引号形式在标识符不存在时会**回退成字符串字面量**——
`WHERE "no_such_col" = 1` 会被解析成 `WHERE 'no_such_col' = 1`，
把"没有这个列"的错误悄悄吞掉。反引号没有这个回退。所以
justorm 的 SQLite renderer 用反引号。

## 占位符

| 方言       | 占位符     |
| ---------- | ---------- |
| PostgreSQL | `%s`       |
| MySQL      | `%s`       |
| SQLite     | `?`        |
| SQL Server | `%s`       |
| Oracle     | `:p<hex>`  |

占位符通常不用自己写，但用 `.where_raw(...)` 或 `cur["..."]` 时会
碰到：

```python
cur.users.where_raw("length(name) > %s", [5])       # PostgreSQL / MySQL / SQL Server
cur.users.where_raw("length(name) > ?", [5])        # SQLite
cur.users.where_raw("length(name) > :p1", [5])      # Oracle（但用 builder 更好）
```

justorm **不**翻译 raw 片段里的占位符。写你的驱动期望的那个。

### Oracle 的命名占位符

python-oracledb 用命名占位符（`:name`）。justorm 的 Oracle 分支会
在渲染时给每个 `_PH` 分配一个随机名 `:p<hex>`，并把参数作为
**dict** 传给驱动。用户看到的是：

```python
cur.users.where(name="Alice").select()
# 内部：
#   SQL:    SELECT * FROM "users" WHERE "name" = :p3a4f1b2c
#   params: {"p3a4f1b2c": "Alice"}
```

随机名意味着：

- 生成占位符时**不需要全局计数器**。
- SQL 字符串和参数 dict 彼此独立，可以跨连接、跨重试复用。
- `params` 类型是 Oracle 特有的；其他方言仍是 list。

### 百分号转义

用 `%s` 占位符的驱动（psycopg、psycopg2、PyMySQL、pymssql）要求
SQL 文本里的字面 `%` 双写：

```python
cur["name LIKE 'a%%'"]     # PostgreSQL / MySQL / SQL Server：匹配 a 开头
cur["name LIKE 'a%'"]      # SQLite / Oracle：同上
```

justorm 在需要双写的方言上对 `Expr` 内容和 `.where_raw` 片段自动
应用这一转义。SQLite 和 Oracle 不用（它们不用 `%s`）。

## RETURNING

| 方言       | 支持                        |
| ---------- | --------------------------- |
| PostgreSQL | 是                          |
| MySQL      | **否**                      |
| SQLite     | 3.35+                       |
| SQL Server | **否**                      |
| Oracle     | **否**                      |

```python
cur.users.returning("id").append(name="Alice")   # -> 1
```

在 MySQL、SQL Server、Oracle 上，终端方法运行时抛
`JustormDialectError`。

**MySQL 用户**用 `LAST_INSERT_ID()`：

```python
cur.users.append(name="Alice")
new_id = cur.execute("SELECT LAST_INSERT_ID()").fetchone()[0]
```

**SQL Server 用户**用 `OUTPUT` 子句，通过 `cur.query(...)`：

```python
cur.query(
    "INSERT INTO users (name) OUTPUT INSERTED.id VALUES (%s)",
    ["Alice"],
)
```

**Oracle 用户**用 `RETURNING col INTO :var` 加 OUT 绑定变量，
通过 `cur.execute(...)`。

SQLite 3.35 之前不支持 `RETURNING`；justorm 不检测版本，错误来自
SQLite 本身，在运行时。

## UPSERT

这是最大的方言差异，justorm 直接暴露它。

### PostgreSQL / SQLite —— `on_conflict`

```python
cur.users.on_conflict(
    on=cur.sql.columns("id"),
    do=cur.sql.update(name=cur["EXCLUDED.name"]),
).append(id=1, name="Alice")
```

| 形式                                 | PostgreSQL | SQLite |
| ------------------------------------ | ---------- | ------ |
| `on=cur.sql.columns(...)`            | 是         | 是     |
| `on=cur.sql.constraint(...)`         | 是         | **否** |
| `on=cur.sql.where(...).columns(...)` | 是         | **否** |
| `on=` 省略（无目标）                 | 是         | 是     |
| `do=cur.sql.nothing()`               | 是         | 是     |
| `do=cur.sql.update(...)`             | 是         | 是     |
| `do=cur.sql.where(...).update(...)`  | 是         | 是     |

被 SQLite 拒绝的形式在终端方法运行时抛 `JustormDialectError`。

`ON CONFLICT ON CONSTRAINT` 要求冲突目标是命名约束（用
`CONSTRAINT ... UNIQUE` 或 `CONSTRAINT ... PRIMARY KEY` 创建）。
SQLite 没有 PostgreSQL 意义上的命名约束，所以有这个限制。

### MySQL —— `on_duplicate`

```python
cur.users.on_duplicate(update={"name": cur["VALUES(name)"]}).append(
    id=1, name="Alice",
)
```

MySQL 的 `ON DUPLICATE KEY UPDATE` 没有冲突目标——它在**任何**
重复键上触发。也没有 `DO NOTHING`；最接近的等价物是把某列更新成
它自己。MySQL 8.0.20+ 偏好行别名而非 `VALUES(col)`；需要就自己
写：

```python
cur.users.on_duplicate(update={"name": cur["new.name"]}).append(
    id=1, name="Alice",
)
```

### SQL Server / Oracle —— 都不支持

两者都用 `MERGE`，语法和 `ON CONFLICT` 完全不同：

```sql
MERGE INTO users AS t
USING (VALUES (1, 'Alice')) AS s (id, name)
ON t.id = s.id
WHEN MATCHED THEN UPDATE SET name = s.name
WHEN NOT MATCHED THEN INSERT (id, name) VALUES (s.id, s.name);
```

justorm 不建模 `MERGE`。用 `cur.query(...)` 写原生 SQL。

### 跨方言错误

在 MySQL 上用 `on_conflict`，或在 PostgreSQL / SQLite 上用
`on_duplicate`，都在最后时刻被拒绝：

```python
cur.users.on_conflict(do=cur.sql.nothing()).append(id=1)   # PG / SQLite OK
# ... 同样的调用在 MySQL 上：append() 跑时抛 JustormDialectError
```

## DISTINCT ON

仅 PostgreSQL。MySQL、SQLite、SQL Server、Oracle 在最后时刻拒绝。

```python
cur.users.distinct_on("name").orderby("name").orderby_desc("id").select()
```

注意 `DISTINCT ON` 要求开头的 `ORDER BY` 表达式和 `DISTINCT ON`
表达式匹配；这是 PostgreSQL 的规则，justorm 不强制。数据库会报。

## ILIKE

仅 PostgreSQL。MySQL、SQLite、SQL Server、Oracle 在最后时刻拒绝。

```python
cur.users.where_ilike(name="a%").select()
```

MySQL 上通常的绕过是大小写不敏感的排序规则：

```python
cur.users.where_raw("name LIKE %s COLLATE utf8mb4_0900_ai_ci", ["a%"])
```

SQLite 上 `LIKE` 对 ASCII 默认就大小写不敏感，所以普通 `LIKE` 常常
够用。

SQL Server 上用大小写不敏感的排序规则，或者：

```python
cur.users.where_raw("LOWER(name) LIKE LOWER(%s)", ["a%"])
```

Oracle 上：

```python
cur.users.where_raw("NLS_UPPER(name) LIKE NLS_UPPER(:p1)", ["a%"])
```

## FOR UPDATE / FOR SHARE

| 方言       | 支持                             |
| ---------- | -------------------------------- |
| PostgreSQL | `FOR UPDATE`、`FOR SHARE`        |
| MySQL      | `FOR UPDATE`、`FOR SHARE`（8.0+） |
| SQLite     | **否**                           |
| SQL Server | **否**（用 `WITH (UPDLOCK)`）    |
| Oracle     | `FOR UPDATE`（无 `FOR SHARE`）   |

```python
cur.users.where(id=1).select(for_update=True)
cur.users.where(id=1).select(for_update=True, skip_locked=True)
cur.users.where(id=1).select(for_update="share")
```

`nowait=True` 和 `skip_locked=True` 互斥，语句构建前抛
`JustormValueError`。

SQLite 和 SQL Server 在最后时刻拒绝 `FOR UPDATE`。

Oracle 上 `share=True` 映射成 `FOR UPDATE`——Oracle 没有
`FOR SHARE`，锁意图一样。

## LIMIT / OFFSET

| 方言       | 备注                                              |
| ---------- | ------------------------------------------------- |
| PostgreSQL | `LIMIT n OFFSET m`，任意顺序                       |
| MySQL      | `OFFSET` 需要 `LIMIT`；builder 抛错               |
| SQLite     | 3.30 起 `OFFSET` 不配 `LIMIT` 也行                 |
| SQL Server | `OFFSET n ROWS FETCH NEXT m ROWS ONLY`（需要 `ORDER BY`） |
| Oracle     | `OFFSET n ROWS FETCH NEXT m ROWS ONLY`（12c+）   |

```python
cur.users.limit(10).offset(20).select()
```

MySQL 的 `LIMIT offset, count` 简写不生成；用上面的 `LIMIT` /
`OFFSET`，或 `.where_raw(...)`。

SQL Server 需要 `ORDER BY` 才合法；自己加。

## UPDATE / DELETE 限制

`UPDATE ... LIMIT` 和 `DELETE ... LIMIT` 在 MySQL、SQLite、SQL
Server 上存在，但 PostgreSQL 没有。justorm 在所有方言上都不生成，
所以：

```python
cur.users.where(id=1).limit(1).delete()     # 抛
cur.users.where(id=1).orderby("id").update(name="x")   # 抛
```

终端方法运行时抛错。需要这些形式时用 `where_raw(...)` 或子查询。

## 类型适配

值类型由驱动适配，不由 justorm。常见映射：

| Python 类型 | PostgreSQL | MySQL        | SQLite    | SQL Server  | Oracle     |
| ----------- | ---------- | ------------ | --------- | ----------- | ---------- |
| `bool`      | `boolean`  | `tinyint(1)` | `integer` | `bit`       | `number(1)` |
| `int`       | `bigint`   | `bigint`     | `integer` | `bigint`    | `number`   |
| `float`     | `double precision` | `double` | `real` | `float` | `binary_double` |
| `str`       | `text`     | `text`       | `text`    | `nvarchar`  | `varchar2` |
| `bytes`     | `bytea`    | `blob`       | `blob`    | `varbinary` | `raw`      |
| `datetime`  | `timestamp`| `datetime`   | (text)    | `datetime2` | `timestamp` |
| `Decimal`   | `numeric`  | `decimal`    | (text)    | `decimal`   | `number`   |
| `dict`      | `jsonb`    | `json`       | (text)    | `nvarchar`  | `varchar2` |
| `list` / `tuple` | `array` | (json)    | (text)    | (json)      | (json)     |

因为值总是作为参数传，justorm 不需要知道这些。它的含义是：一个
方言上没问题的值，另一个方言上可能失败。比如：

```python
cur.users.where(tags=["a", "b"]).select()
# PostgreSQL: WHERE "tags" = ARRAY['a','b']
# MySQL:      报错，数组不是值类型
# Oracle:     报错，同理
```

## 检测方言

方言由你实例化哪个 cursor 类决定。没有运行时检测，也没有
`dialect=` 参数：你为你的驱动 import 模块，用它的 `Cursor`。

如果你想在自己的代码里分支，用 renderer 属性：

```python
if cur.dialect_name == "postgresql":
    ...
```

`dialect_name` 由每个 renderer 设置（`"postgresql"`、`"mysql"`、
`"sqlite"`、`"pymssql"`、`"oracledb"`）。它用于日志和诊断；应用
逻辑一般不需要它，因为方言在 import 处已知。

## 版本说明

- SQLite `RETURNING`：3.35.0（2021-03-12）。
- SQLite `ON CONFLICT`：3.24.0（2018-06-04）。
- SQLite `OFFSET` 不配 `LIMIT`：3.30.0（2019-10-04）。
- MySQL `FOR SHARE`：8.0.1。
- MySQL `ON DUPLICATE KEY UPDATE` 行别名：8.0.19+。
- SQL Server `OFFSET ... FETCH`：2012。
- Oracle `OFFSET ... FETCH`：12c。

justorm 不查询服务端版本。用了服务端没有的特性，错误来自服务端，
不来自 justorm。这和"无 schema、最后时刻抛"的哲学一致。
