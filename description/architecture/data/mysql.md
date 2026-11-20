# MySQL 主库与检索

模板在同一开发镜像中提供 PyMySQL 和 SQLite 驱动。需要 MySQL 的模块直接使用 app.repository.mysql。服务端固定为 MySQL 8.4/InnoDB、中文 ngram 和 MyVector。部署模板与后端一起复制，保留上级 compose.yaml 和 mysql/。

## 从空库开始

在部署目录的私有 .env 中设置 MYSQL_PASSWORD 和 MYSQL_ROOT_PASSWORD 两个不同的随机口令，执行：

```sh
docker compose up --build -d --wait mysql
docker compose run --build --rm --no-deps mysql-client
```

mysql-client 默认用普通账号检查检索能力，可追加 Python 命令运行派生代码。服务地址为 Compose 内网 mysql:3306。用 `docker compose stop mysql` 停止服务并保留卷。若此前使用模板自动生成的 .env.mysql-dev，沿用该凭据文件和原 Compose 项目名（`docker compose --env-file .env.mysql-dev -p 原项目名 …`）即可继续访问原卷。已有实例的项目名可用 `docker compose ls -a` 查看。

空卷首次初始化安装插件、函数与索引管理过程，应用数据库中没有业务表。MyVector 的内部连接配置保存在 mysql-data 内，备份和卷按凭据同级保护。业务账号仅获得本库权限及索引构建、状态查询过程的执行权。MySQL DDL 隐式提交，表结构随派生业务的独立迁移维护。

## Python 读写

```python
from app.repository.mysql import reader, transaction

with reader() as db, db.cursor() as cursor:
    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

with transaction() as db, db.cursor() as cursor:
    cursor.execute("SELECT %s", (1,))
```

reader 开启只读事务，transaction 在正常退出时提交，异常时回滚并关闭连接。迁移创建业务表之后，service 可把同一个连接交给多个 repository 操作。SQLite 和 MySQL 各自维护权威数据，跨库操作需要业务显式协调。

## 中文全文与向量查询

以下为派生迁移的示例结构，仅用于说明索引契约。模板初始化不执行这段 SQL。

```sql
CREATE TABLE documents (
    id BIGINT PRIMARY KEY,
    scope_id BIGINT NOT NULL,
    body TEXT NOT NULL,
    embedding MEDIUMBLOB NOT NULL,
    INDEX ix_scope (scope_id),
    FULLTEXT KEY ft_body (body) WITH PARSER ngram
) ENGINE=InnoDB;
```

ngram_token_size 固定为 2，可从连续中文中匹配“验收”。词法相关度降序、余弦距离升序。下列占位符通过 PyMySQL 绑定；scope_id 应来自 service 已核实的可见范围。

```sql
SELECT id, MATCH(body) AGAINST (%s IN NATURAL LANGUAGE MODE) AS score
FROM documents
WHERE scope_id = %s AND MATCH(body) AGAINST (%s IN NATURAL LANGUAGE MODE)
ORDER BY score DESC, id LIMIT %s;

SELECT id, myvector_distance(embedding, myvector_construct(%s), 'Cosine') AS distance
FROM documents WHERE scope_id = %s
ORDER BY distance, id LIMIT %s;
```

写入 embedding 时用 myvector_construct(%s) 将 JSON 数组转为插件格式。派生项目记录模型版本、维度，校验输入为同一模型空间的有限非零向量。此路径按参考项目在候选范围内精确排序。HNSW 索引需要业务另行设计和验收。

## 部署与验收

部署实例的 MYSQL_DATABASE、MYSQL_USER、MYSQL_PASSWORD、MYSQL_ROOT_PASSWORD 取自部署目录私有 .env，账号名使用字母、数字、下划线或连字符，口令使用无换行的随机值。插件内部连接配置使用 root 口令，业务后端只接收普通账号。卷内为旧版无插件实例时，先做备份，在新镜像的独立空卷初始化后迁移业务数据并核对，保留旧卷直到切换验收完成。初始化脚本只在空卷运行。

从部署目录运行 `./mysql/check.sh`，会在独立临时 Compose 项目创建样本，以业务账号验收两路查询，重启数据库后复查并清理。部署命令见[部署说明](../../../../README.md)，观察结果见[验收记录](../../standard/template-checks.md)。
