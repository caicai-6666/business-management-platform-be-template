# SQLite 主库操作指南

SQLite 是派生平台的权威主库。开发命令使用模板自带的 Python 3.12 容器。初始化只创建数据库文件、启用 WAL；初始 schema 为空。表、索引和迁移版本由派生项目定义。

## 初始化与检查

在后端根目录构建镜像并挂载工作区，即可在容器内执行下文的命令。默认主库保存在宿主的 data/ 目录。若要加载私有配置，给 docker run 添加 `--env-file .env`。

```sh
docker build -t platform-backend:local .
docker run --rm -it --user "$(id -u):$(id -g)" -v "$PWD:/template" platform-backend:local sh
```


```sh
python3 -m app.database init
python3 -m app.database check
```

| 环境变量 | 默认值 | 约定 |
| --- | --- | --- |
| DB_ENGINE | sqlite | SQLite 命令仅在 sqlite 模式执行 |
| DATA_DIR | ./data | 相对路径按后端根目录解析，也可使用绝对路径 |
| SQLITE_FILENAME | platform.sqlite3 | 主库文件名，使用单层名称 |
| VECTOR_INDEX_FILENAME | vectors.sqlite3 | 单独的派生索引文件名，与主库名称区分 |

`init` 创建缺失的目录，可重复执行并保留已有数据。`check` 只读打开已有文件，运行 `PRAGMA integrity_check` 并打印日志模式；初始化后的预期输出为 `journal_mode=wal` 和 `check OK`。缺少主库、校验失败或配置无效时返回非零。

Compose 的 backend 将 backend-data 卷挂载到 /var/lib/platform。派生镜像包含本模板并将后端根目录设为工作目录后，可在部署目录执行 `docker compose run --rm --no-deps backend python -m app.database init`，再用同样的命令将 init 换成 check。部署账户需能写入整个数据目录，以便 SQLite 管理 WAL 和共享内存文件。WAL 适用于同一主机上具备 SQLite 文件锁语义的本地存储。备份、卷和文件权限由部署负责人管理。

## 业务代码如何使用连接

启动阶段调用一次 `initialize()`。service 在一次业务操作的边界开启事务，将连接传给参与该操作的 repository 方法；repository 使用参数绑定执行 SQL。以下代码可以直接在空库运行。

```python
from app.repository.sqlite import initialize, reader, transaction

initialize()
with reader() as db:
    schema = db.execute("SELECT name FROM sqlite_schema ORDER BY name").fetchall()

with transaction() as db:
    # 派生项目在这个块内用同一连接完成关联写入。
    db.execute("SELECT ?", (1,)).fetchone()
```

每个上下文创建并关闭一个连接，开启外键校验。reader 只读打开已有文件。transaction 用 BEGIN IMMEDIATE 取得写锁，正常退出时提交，异常退出时回滚。多个写者竞争时最多等待 5 秒，超时抛出 sqlite3.OperationalError。已有事务内复用同一连接，避免开启第二个写事务。在事务块中使用 execute 或 executemany；自行提交或使用会隐式提交的 executescript 会破坏事务边界。外部通知由 service 在提交后处理。业务授权和幂等规则由派生项目落实。

## 在线备份与隔离恢复

以下命令从后端根目录执行。目标目录需可写，支持硬链接；备份目标使用新文件名。备份命令通过 SQLite backup API 读取已提交数据，将完整性校验通过的单文件快照发布到指定路径，遇到同名文件时退出。

```sh
mkdir -p backups
python3 -m app.database backup backups/platform-001.sqlite3
restore_dir=$(mktemp -d)
cp backups/platform-001.sqlite3 "$restore_dir/platform.sqlite3"
DATA_DIR="$restore_dir" SQLITE_FILENAME=platform.sqlite3 python3 -m app.database check
DATA_DIR="$restore_dir" SQLITE_FILENAME=platform.sqlite3 python3 -m app.database init
```

恢复先使用独立空目录，核对完整性与派生项目的业务记录，再停写旧实例并将应用指向已验证的新目录。快照使用单文件日志模式，恢复后的 init 会重新启用 WAL。旧目录及其 WAL 文件作为整体保留到恢复验收完成。宿主机或数据卷故障的恢复依赖卷外备份，备份应保存到有访问控制的存储。

## 隔离验收

在后端根目录运行 `python3 -B -m unittest discover -s tests -p test_sqlite.py`。工具在 tests/tmp 下创建临时目录，使用文件头的 user_version 验证写入结果，结束后自动清理。版本、覆盖范围和容器命令见[验收记录](../../standard/template-checks.md)。全文与向量能力见[检索验收](search.md)。
