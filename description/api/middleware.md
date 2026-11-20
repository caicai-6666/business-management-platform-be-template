# 子平台如何接入中间件

以设备验收平台为例：中间件管理员登记“哪个平台在调用”，主系统提供“当前登录的用户是谁”，设备验收平台决定“这个用户能否查看或审批这张单”。先验证平台会话，再接用户身份，最后按业务需要启用消息流。

## 1. 领取测试平台身份

联系中间件维护人，提供唯一平台代号（例如 `equipment-check`）、名称、职责和需要联调的流程。维护人在中间件 `PLATFORM_CONFIG_PATH` 指向的 YAML 的 `platforms` 列表中追加条目，保留已有平台，按部署流程重启使配置生效。下面是一项示例：

```yaml
- code: equipment-check
  name: 设备验收
  description: 提交设备资料并处理审核结果
  secret: "替换为该环境专用随机密钥"
  is_sub_management_platform: true
  a2aresponsibility: 解答设备验收记录与流程问题
```

如需参与跨平台问答，再与维护人确认 `supports_a2a: true` 及对应职责。维护人向后端负责人单独交付地址与密钥；测试环境使用独立代号。派生平台通过中间件 HTTP API 对接，消息资源由中间件管理。

## 2. 验证地址、登录和心跳

`MIDDLEWARE_BASE_URL` 填服务根地址，例如 `https://middleware.example.org`。以下接口统一追加 `/middleware-service/api`。本地运行在后端的私有环境中设置变量；容器运行则填写 deploy 的 `.env`。三个连接项全空时可独立运行；派生应用启用对接时应校验三项齐全。派生服务的请求超时与失败重试间隔分别由 `MIDDLEWARE_REQUEST_TIMEOUT_SECONDS`、`MIDDLEWARE_RETRY_INTERVAL_SECONDS` 指定，单位为秒。

使用 Python 3 标准库，从后端目录运行以下命令。将地址和代号换成联调环境的实际值，按提示输入密钥。工具也可读取进程环境中的 `MIDDLEWARE_SECRET`。本机环回测试支持 HTTP，远程使用 HTTPS。

```sh
MIDDLEWARE_BASE_URL=https://middleware.example.org \
MIDDLEWARE_PLATFORM_CODE=equipment-check \
python3 tests/check_middleware.py
```

| 步骤 | 请求 | 成功时核对 |
| --- | --- | --- |
| 探活 | GET `/health` | 200，`status=ok`。此步只确认 HTTP 可达。 |
| 登录 | POST `/platform/login`，JSON 含 `platform_code`、`secret` | 200，`code` 为申请的代号，保存 `access_token`、有效秒数及建议心跳间隔。 |
| 心跳 | POST `/platform/heartbeat`，头部带 `Authorization: Bearer <平台令牌>`，空请求体 | 200，按响应中的 `heartbeat_interval_seconds` 续期，并更新 `expires_in_seconds`。 |

验收工具使用有限正数作为请求超时，每步只请求一次。登录或心跳提示“未取得完整响应”时，中间件可能已建立或续期会话，应先核对该代号的会话状态。

工具依次输出 `health OK`、`login OK`、`heartbeat OK`，随后退出。同一代号只允许一个活跃会话，没有主动登出接口；再次运行或启动同代号服务前，需等刚续期的会话自然过期。多个 worker 或副本应协调由一个会话持有者登录、续期。登录 401 核对代号与密钥；心跳 401 失效该令牌后重登；登录 409 检查已有实例或等待 TTL；503 核对中间件依赖并退避重试。日志仅记录阶段、状态码及关联标识。

## 3. 将用户身份接入业务入口

派生后端收到用户令牌后，用**平台令牌**作为 Bearer，POST `/user/login-cache`，JSON 为 `{"access_token":"<用户令牌>"}`。响应为 200 时仍要检查 `is_logged_in` 和 `userid`。无效用户令牌会得到 `is_logged_in=false`、`userid=null`、`ttl=0`；有效会话会滑动续期。接口返回 503 时，将受保护操作反馈为暂不可用。路由将验证过的身份交给 service，按本地业务角色及记录归属授权。

涉及文件读取时，用已核实的 userid 调用 POST `/user/file-permission`，JSON 为 `{"userid":"<已验证的用户ID>"}`。响应中的 `file_level=null` 表示无本平台授权，整数 0 是有效等级。文件列表、下载与检索都需执行同一可见性规则。

## 4. 按需对接入库、删除审核

下表各接口均为 POST，并携带平台 Bearer。子平台发布申请，注册中心消费申请并发布结果，子平台拉取和确认自己的结果。模板的 MiddlewareClient 封装 HTTP，MiddlewarePlatform 管理会话和确认时机。派生项目在 repository 持久化申请 ID、消息关联及处理回执。

| 子平台动作 | 路径及数据 |
| --- | --- |
| 申请入库 | `/ingestion-requests/publish`，multipart 提交 name、abstract、source_id、reviewer、file_extension 和单个 file，可带 note。 |
| 申请删除 | `/deletion-requests/publish`，表单提交 source_id、passport、name、abstract、uploader、applicant，可带 note。多个 passport 重复提交同名字段，保留原实例身份。 |
| 拉取结果 | `/ingestion-results/pull` 或 `/deletion-results/pull`，空请求体。204 表示暂无结果，200 读取 message。 |
| 确认结果 | 对应的 `/ingestion-results/ack` 或 `/deletion-results/ack`，JSON 为 `{"message_id":"<反馈自身的消息ID>"}`。 |

例如，删除发布成功返回 201 后，保存申请的 message_id。收到反馈时，用反馈的 request_id 找到该申请。拒绝后先保存结果；批准后核对实例、完成清理并写入回执。两者都用**反馈自身**的 message_id 确认。遇到发送超时先标记送达不明并对账，未知关联保留待查；重放已完成的反馈可依据回执补 ack。详见[删除审核与恢复](../architecture/workflow/deletion-review.md)。

## 5. 在派生服务中使用

应用启动时调用 `MiddlewareSettings.from_env()` 读取进程变量，Compose backend 已传入这五项配置。三项身份配置全空返回 None，部分填写会报错。使用 HTTPS；隔离局域网或 Compose 私网也可配置受控 HTTP 服务地址。登录与心跳只保留一个会话持有者，同一代号只在一个 worker 运行。应用关闭时退出异步上下文，客户端会取消轮询并释放连接。

```python
from app.config.middleware import MiddlewareSettings
from app.schema.middleware import IngestionRequest, DeletionRequest, Stream
from app.service.middleware import MiddlewarePlatform

# 以下在派生服务的异步 lifespan 中运行，三个回调由业务层提供。
settings = MiddlewareSettings.from_env()
if settings is not None:
    async with MiddlewarePlatform(settings) as platform:
        platform.start_consumer(Stream.INGESTION, handle_ingestion_result)
        platform.start_consumer(Stream.DELETION, handle_deletion_result)
        platform.start_consumer(Stream.FILE_LEVEL, apply_file_level)
        app.state.middleware = platform
        yield
else:
    yield
```

start 创建后台登录作业，登录成功后按服务端建议间隔续期。需要首个请求就绪时可用 `await platform.wait_ready(timeout=30)`。令牌过期时停止用于业务调用，401 唤醒登录任务；登录冲突与临时故障退避。用户接口为 `query_user_login(SecretStr(user_token))` 和 `query_user_permission(verified_userid)`，先核对 is_logged_in，再使用返回的 userid。等级 0 有效，None 或依赖异常时拒绝文件读取。

在已授权的 service 中发送申请。示例中的人员来自可信身份和记录快照，文件后缀来自派生项目验证过的文件。调用方持有打开的文件并负责关闭，传入二进制流时从当前位置读取。

```python
ingestion = IngestionRequest(source_id="EQ-001", name="设备验收单", abstract="设备验收材料",
                             reviewer="审核员甲", file_extension="pdf")
sent = await platform.publish_ingestion(ingestion, file_bytes)
deletion = DeletionRequest(source_id="EQ-001", name="设备验收单", abstract="设备验收材料",
                           uploader="经办人乙", applicant="申请人丙", passport=["签发实例一"])
result = await platform.publish_deletion(deletion)
```

| 发布结果 state | 业务处理 |
| --- | --- |
| published | 保存服务端 message_id，作为反馈 request_id 的关联键 |
| duplicate | 核对返回的旧申请 ID 和本地原始申请，同 source_id 在 registry ack 后可再次发布 |
| retry | 尚未连接、无有效会话或上游明确未发布，按业务重试策略处理 |
| blocked | 403 或 422，修正权限或字段 |
| uncertain | 保存候选 message_id，按原申请对账；调用超时可能已经送达。客户端只发送一次 |

### 消费、确认与文件等级

三个流分别串行消费。轮询间隔与失败退避复用 MIDDLEWARE_RETRY_INTERVAL_SECONDS。也可用 `await platform.consume_once(stream, handler)` 手动消费一条；204 返回 False，完成确认返回 True。传入回调的是类型化 Delivery，包含 offset 和 message。回调遵循以下提交边界：

1. 在当前平台和流内，以反馈自身 message_id 查询持久回执，核验消息身份。若已处理且内容一致，返回 `"replayed"`。发现冲突或未知关联时抛出异常并保留现场。
2. 入库结果用 request_id 关联本地申请，passport 为空表示未签发；历史消息可能缺少 file_level，此时保留既有等级。删除结果使用严格布尔 approved，批准后核对实例并实际完成清理，拒绝时记录决定。跨存储清理需有可恢复的执行记录。
3. 等级调整从 registry 专属发布端进入 `file-permission-adjustments/pull`。核对 target_platform_code 和 source_id，只更新对应文件的 file_level；它与用户访问等级是不同字段。把本地业务修改和回执持久化后返回 `"committed"`。回调失败、返回其他值或任务被取消时不发 ack。
4. 模板向本流的 /ack 提交反馈 message_id，核对响应的 message_id 和 offset。确认丢失时重新拉取，已完成的回执可补 ack。不同流之间没有消费顺序保证，申请映射、幂等回执、等级冲突和已删除记录的处理由派生项目的业务规则决定。

连接层与会话层可直接复用。模板初始化保持空业务库，真实文件变更由派生项目注册回调执行。[协议模型](../../app/schema/middleware.py) · [会话与消费入口](../../app/service/middleware.py)

## 6. 派生项目联调验收

用隔离环境的虚构用户和资源，从派生平台正式入口逐项验收：

1. 记录探活、平台登录和心跳的状态；用错误测试密钥验证登录 401，用已登录的代号验证 409。
2. 有效用户仅可读取授权记录，过期用户被拒绝；模拟身份服务不可用时，受保护数据不可见。
3. 若启用审批，提交一条样本并由测试注册中心处理，核对申请与反馈的两种消息 ID。模拟处理后、ack 前重启，检查副作用只执行一次。
4. 记录环境、版本、平台代号、脱敏的状态码和结果，使用[验收记录样板](../standard/acceptance.md)。工具覆盖前两类平台接口（登录和心跳）及探活，业务验收由派生项目执行。

针对部署版本核对服务根地址下的 `/openapi.json`。消息重试、附件与 A2A 等协议细节请中间件维护人提供对应版本的 `description/api/` 文档。

本机可从后端目录运行 `python3 -B tests/test_check_middleware.py`，用环回服务复核请求内容、异常退出和凭据脱敏。已验证的范围见[模板验收记录](../standard/template-checks.md)。
