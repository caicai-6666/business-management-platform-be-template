# 模板工具验收记录

历史记录保留当时执行的命令。当前开发与验收入口见[后端说明](../../README.md)和[部署说明](../../../README.md)。

2026-11-20 在后端根目录使用 Python 3.10.1 运行下列命令。检索使用内存库；中间件检查使用临时环回端口和虚构凭据，每次启动独立的命令行进程。

| 命令 | 观察结果 |
| --- | --- |
| `python3 tools/check_search.py` | SQLite 3.35.5 的 FTS5 命中记录 1、2；标题命中的记录 1 排在首位，退出码为 0。 |
| `python3 -B tests/test_check_middleware.py` | 三组测试通过。正常流程核对请求路径、登录载荷、心跳令牌及空请求体。模拟登录 401、409、连接中断、响应结构或字段异常时，工具在对应步骤退出。超时值为 0、nan、inf 时未发出请求。所有场景的输出均未包含样本密钥和令牌。 |

本次未连接真实中间件。真实会话的并发互斥、到期重登与重启恢复需在专用测试平台联调。本次也未运行 Docker、MySQL 或可选向量检索验收。

## SQLite 主库专项验收（2026-11-20）

| 环境与命令 | 观察结果 |
| --- | --- |
| 本机 Python 3.10.1 / SQLite 3.35.5，`python3 -B -m unittest discover -s tests` | SQLite 四组、中间件三组测试通过。SQLite 测试数据位于 tests/tmp 的独立临时目录。 |
| 部署目录，`docker compose --env-file .env.example --profile check config -q` | Compose v5.6.1 配置校验通过。 |
| 部署目录，`docker compose run --rm --no-deps -w /template -v /template/tests/tmp check python -B -m unittest discover -s tests -p test_sqlite.py` | 容器 Python 3.12.16 / SQLite 3.46.1，四组通过。源码只读，临时库使用匿名卷。 |

检查覆盖初次与重复初始化、空 schema、配置拒绝、只读连接拒写、事务提交及回滚、并发读取已提交状态、竞争写锁超时、写进程中断后重开、在线备份与独立快照恢复、同名备份保护。未验证宿主机掉电或真实生产卷恢复。业务授权和外部消息送达须在派生服务具备对应入口后验收。

## 从模板副本开始开发（2026-11-20）

将版本管理范围内的模板文件复制到新的临时目录，保留 tools/dev 的可执行权限。副本中没有私有 .env 或已有数据库。使用 Docker 和 Python 3.12.16 镜像验收：

| 命令 | 观察结果 |
| --- | --- |
| 连续两次运行 `./tools/dev` | 两次均完成中文 BM25 与向量近邻查询，主库初始化成功，完整性检查通过，日志模式为 WAL。查询主库 sqlite_schema 返回空集。 |
| `./tools/dev python -m unittest discover -s tests` | 7 项通过，覆盖 SQLite 文件生命周期与中间件模拟服务。 |
| 部署目录运行 `docker compose --env-file .env.example --profile '*' config -q` 和 `docker compose run --build --rm --no-deps check` | Compose 配置有效。SQLite 3.46.1 返回关键词记录 1、2，sqlite-vec 0.1.9 返回近邻 1、3，距离为 0、约 0.1414。 |

本次验收使用固定样本向量，覆盖向量写入、扩展随新连接加载和 SQL 查询。真实业务文本的 embedding 生成和效果评估随派生需求验收。

## MySQL 主库专项验收（2026-11-20）

在完整模板的临时副本与独立 Compose 项目中验收，使用 MySQL 8.4.13、PyMySQL 1.1.2，MyVector 插件来源固定在部署层 mysql/Dockerfile 的镜像摘要。

| 命令或入口 | 观察结果 |
| --- | --- |
| 后端目录 `./tools/dev mysql` | 从空卷启动成功，普通账号检查 ngram=2 和 MyVector 余弦函数通过。开发凭据文件权限为 0600。再次通过开发入口执行 SHOW TABLES，业务库为空。 |
| 部署目录 `./tools/check-mysql.sh` | 中文“验收”命中记录 1、2，重复命中的记录排第一。固定查询向量的余弦距离返回记录 1、3。两个连接并发时读取不到未提交的更新，重复主键触发回滚，只读事务拒绝更新。重启后两路排序仍通过。 |
| 后端目录 `./tools/dev` 和 `./tools/dev python -m unittest discover -s tests` | SQLite BM25、sqlite-vec 近邻查询和空主库初始化均通过。原有 7 项测试通过。 |

本次检索使用隔离样本与固定向量。HNSW 索引、真实嵌入模型和生产 MySQL 旧卷迁移未验收。

## 目录精简后的入口复验（2026-11-20）

在按 Git 放行范围复制的临时部署和后端目录执行。后端 `./dev` 完成 SQLite 3.46.1 中文 BM25、sqlite-vec 0.1.9 近邻查询和 WAL 空库检查；`./dev python -m unittest discover -s tests` 通过 7 项测试。`./dev mysql` 从空卷启动 MySQL 8.4.13 并通过能力检查。部署目录 `./mysql/check.sh` 在重启前后均得到全文命中 1、2 和向量近邻 1、3。

## 中间件子平台基础设施（2026-11-20）

合同后端主开发助手在独立 Docker 环境使用真实 middleware-service、RabbitMQ Stream 4.3 和 Redis 7.4.8，分别构造 registry 与子平台身份，通过模板公开 API 执行 `python -B client/check.py` 和 `python -B lifecycle.py`（独立验收工作目录）。验收结论为通过。临时容器和卷已清理。

| 场景 | 独立验收观察 |
| --- | --- |
| 会话与用户 | 服务端 TTL 30 秒、心跳间隔 2 秒。重启中间件后旧令牌心跳 401，模板重新登录并恢复拉取。Redis 返回用户部门、离职状态、文件访问等级 2 和过期令牌的未登录响应。 |
| 发布与去重 | 两类首次申请均 201；registry ack 前重复申请均 409，返回原消息 ID。删除申请两个 passport 原样交付。 |
| 消费与恢复 | 入库反馈提交后确认；删除反馈提交前失败，按相同 ID、offset 重投；文件等级调整提交后失败，重放凭回执仅产生一次业务写入。三个流最终均返回 204。 |

本仓库可运行 `docker compose run --build --rm check python -m unittest discover -s tests -p test_middleware_platform.py` 复核报文、严格类型、单消费者并发、提交边界、401 重登、发布超时及 ack 响应丢失。独立验收未覆盖多 worker 共用同一代号或生产环境；业务回执表由派生项目实现。

## 钉钉应用与固定出口（2026-11-20）

模板全量回归命令为 `docker compose run --build --rm --no-deps check python -B -m unittest discover -s tests`，15 项通过。钉钉专项通过真实环回 HTTP CONNECT 检查代理拒绝场景，并用模拟响应检查应用凭据、并发令牌缓存、401 后刷新和写请求不自动重发。两份环境变量样例和 Compose backend 的钉钉配置一致。

额外验收在无外网的 Linux ARM64 临时容器执行。使用 FRP v0.64.0、Squid 6.13、临时 CA 和本地模拟钉钉 HTTPS 源站，按 [FRP 出口指南](../capability/infrastructure/dingtalk-frp-egress.md) 对三份 TOML 执行 verify，对 squid.conf 执行 parse，再启动四个进程。实际 DingTalkClient 经 visitor → frps → provider → Squid 取得虚构令牌并完成带令牌请求。代理对非白名单域名的 CONNECT 返回 403；停止 provider 后，新客户端取令牌失败。Compose visitor 覆盖示例已通过配置解析。

未使用真实企业凭据，未修改公网白名单。生产公网出口 IP、钉钉授权范围、应用发布状态与账号联调需由部署负责人核验。本轮使用官方发布的 FRP 二进制；源码构建命令已核对对应版本 Makefile。

## 通过 SSH 接入本机开发入口和钉钉出口（2026-11-20）

在无外网的 Linux 容器中启动真实 OpenSSH 服务、FRP 0.64.0、Squid 6.13、测试网页和模拟钉钉 HTTPS 源站。使用临时 SSH 身份和已登记的主机公钥，分别对 ingress.toml、visitor.toml 执行[接入指南](../capability/infrastructure/ssh-dev-mapping.md)中的 connect.sh 命令，以两个本地控制端口连接同一个测试 frps。

映射端口对完整开发路径返回本机网页标识。模板 DingTalkClient 经第二条 SSH/FRP 链路取得模拟令牌并访问受保护接口；非许可域名 CONNECT 返回 403。终止 visitor 对应的 connect.sh 后，新的钉钉请求失败，网页仍能访问。随后停止入站实例，候选上游端口关闭。未连接真实映射服务器、切换公网 Nginx、验证企业白名单或测试操作系统服务的开机恢复。
