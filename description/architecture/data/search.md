# 存储与检索验收

单机、低写入并发可选 SQLite。派生服务在 DATA_DIR 下打开 SQLITE_FILENAME，连接启用外键并设置锁等待时间；使用 WAL 时对活动数据库用 SQLite backup API 做一致性备份。多实例并发写入可选 MySQL 8.4/InnoDB，统一 utf8mb4、UTC、事务边界及迁移版本。切换 DB_ENGINE 仅选择驱动，迁移历史数据需单独导出、导入并核对主键、行数及索引命中。

| 模式 | 索引和查询 | 验收结果 |
| --- | --- | --- |
| SQLite FTS5 | 样例对中文预先按词加空格；标题和正文建列，MATCH 参数绑定，bm25 标题权重 8，分数升序 | 查询“验收”，标题命中的 1 先于正文命中的 2，排除 3 |
| MySQL FULLTEXT | InnoDB 上使用 ngram 解析器，默认双字切分，提交写入后 MATCH AGAINST 自然语言查询，相关度降序 | 连续中文样本中查询“验收”，两次命中的 1 先于一次命中的 2，排除 3 |
| 可选 sqlite-vec | 独立 vec0 表，二维固定向量，L2 距离升序取前二 | 查询 [1,0] 返回 1、3，距离约为 0 和 0.1414 |

本目录可直接运行：

```sh
python3 tools/check_search.py
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements/vector.txt
.venv/bin/python tools/check_search.py --vector
```

向量路径需要 Python 的 sqlite3 支持运行时加载扩展。仅加载安装包内的扩展，随后立即关闭加载权限。已验证 Python 3.12/Linux ARM64、sqlite-vec 0.1.9；宿主 Python 缺少 enable_load_extension 时可用[容器命令](../../../../README.md)。MySQL 验收用上级目录的 `./tools/check-mysql.sh`。这三个检查使用人工样本，独立于业务服务或嵌入模型。

## 派生平台的索引契约

SQLite 默认分词器对连续中文的处理与预分词样例有差异。导入与查询应使用同一分词规则并以真实领域词验收。MySQL 的 ngram_token_size、停用词与字符集同样影响短词查询，修改后重建索引。两引擎的相关度数值分别解释。

VECTOR_ENABLED 默认关闭。启用时由派生服务在 DATA_DIR/VECTOR_INDEX_FILENAME 建立可重建的 SQLite 派生库。MySQL 主库也可采用此设计，向量文件随后端数据卷保存。本模板只实测向量查询原语；跨库同步、混合排序、模型调用及权限联查均由派生平台实现。记录资源 ID、实例版本、租户、嵌入模型版本和维度。主库提交时同事务记录待索引任务，单写者按版本幂等更新，失败可重放，定期核对漏项；多副本部署需明确索引复制和写入归属。文本和向量召回后都要回查主库当前版本、删除状态和读取权限，再生成可见摘要。删除后即时阻止读取，确认索引清理后完成删除任务。

索引失效时可关闭向量，继续使用全文查询；重建完成后再启用。真实数据卷按主库同等级限制访问。备份包含主库与归属文件，派生索引可从权威数据重建。

派生服务创建虚拟环境后，以 `python -m pip install -r requirements.txt` 安装 HTTP 基础依赖；MySQL 模式追加 `python -m pip install -r requirements/mysql.txt`。检索工具可独立运行，SQLite 基础路径无需安装上述两组依赖。
