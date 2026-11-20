# SQLite 全文与向量检索

模板开发镜像内置 SQLite FTS5 和 sqlite-vec 0.1.9。从部署目录执行 `docker compose run --build --rm check` 即可验收。两项检查使用临时文件，通过正式连接写入并重开查询，完成后清理样本。

| 能力 | 派生项目入口 | 验收预期 |
| --- | --- | --- |
| 中文 BM25 | 主库 transaction() / reader()，FTS5 标题和正文列 | 查询“验收”命中“设备验收”。标题权重为 8、正文为 1 时，标题命中的记录 1 先于正文命中的记录 2 |
| SQL 向量检索 | initialize(vector=True)、transaction(vector=True)、reader(vector=True) | 固定查询向量 [1,0] 的前两个 L2 近邻为记录 1、3，距离约为 0 和 0.1414 |

## 中文索引与查询

派生项目在自己的迁移中定义 FTS5 虚拟表。原始标题和正文保存在权威业务记录中。写入 FTS5 前用 `app.repository.full_text.index_text` 对中文逐字切分，对连续字母数字统一大小写。用相同规则生成字面短语，支持从连续中文匹配“验收”等短词。下面以派生迁移创建的 docs(title, body) 为例：

```python
from app.repository.full_text import index_text, match_phrase
from app.repository.sqlite import reader, transaction

with transaction() as db:
    db.execute("INSERT INTO docs(rowid, title, body) VALUES (?, ?, ?)",
               (1, index_text("设备验收"), index_text("合同付款")))
with reader() as db:
    rows = db.execute("SELECT rowid FROM docs WHERE docs MATCH ? ORDER BY bm25(docs, 8, 1), rowid",
                      (match_phrase("验收"),)).fetchall()
```

## 向量索引

需要索引时调用 `initialize(vector=True)` 创建独立的空向量库，默认位置为 DATA_DIR/vectors.sqlite3。每个向量库连接都会加载镜像内固定版本的扩展，随即关闭加载权限。派生项目在此库创建维度与实际嵌入模型一致的 vec0 表，并记录模型版本。下面以已有二维向量表 vectors(v) 为例：

```python
from app.repository.sqlite import reader

with reader(vector=True) as db:
    nearest = db.execute(
        "SELECT rowid, distance FROM vectors WHERE v MATCH ? AND k=? ORDER BY distance",
        ("[1,0]", 2),
    ).fetchall()
```

主库保存权威记录及版本。派生项目需要异步更新索引时，在主库提交时记录待处理任务，按版本幂等更新或清理索引。向用户展示结果前，按已验证身份回查主库的可见范围、当前版本和删除状态。索引可从权威数据重建。备份与恢复见[主库指南](sqlite.md)。
