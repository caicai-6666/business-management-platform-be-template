# 后端协作约定

先读 [description/project.md](description/project.md)，确定业务对象、权威数据、读写角色和外部系统所有者。关键规则由业务负责人确认。派生项目每次改变接口、状态或配置时，在同一变更中更新相应文档、示例变量和验收证据。

开发环境由 Dockerfile、requirements.txt 和上级 compose.yaml 定义。SQLite 使用 FTS5/BM25 与 sqlite-vec，MySQL 使用 ngram 与 MyVector。分别复用 [SQLite 连接与事务](description/architecture/data/sqlite.md)和 [MySQL 连接与事务](description/architecture/data/mysql.md)。初始化保持空 schema，业务迁移随已确认的需求提交。

| Python 包 | 责任 |
| --- | --- |
| app/router、app/schema | 从可信会话取得身份，验证输入，定义响应和错误。客户端传入的操作者字段不得用于授权。 |
| app/service | 编排授权、业务事务和生命周期；明确提交点以及事务外的副作用。 |
| app/repository | 维护权威状态、唯一约束、事务和并发更新；查询按主体和可见范围过滤。 |
| app/model | 领域对象、持久化字段、状态含义；序列化契约放入 schema。 |
| app/infrastructure | 适配外部身份、消息、文件和检索协议；处理超时与回执。 |
| app/config | 解析、验证环境配置，明确路径基准和必填条件。 |
| app/agent、app/tool | 按需启用。工具调用复用 service 的授权与校验，模型输出需经业务规则确认。 |

assets/ 放应用运行时读取的静态资源。模板仅放行 assets/.gitkeep；派生项目引入资源时逐项放行文件及所需许可证，并为容器运行所需的文件同步更新 .dockerignore 和 Dockerfile。新增本地工具及测试默认忽略，模板公开命令直接依赖的脚本在 .gitignore 中逐个列出。部署编排和 MySQL 初始化由上级部署仓库管理。

真实运行数据放 data/，虚构样本放 tests/fixtures/，临时库放 tests/tmp/，实验结论放 experiment/。日志只保留关联 ID、阶段和脱敏错误码。样例配置可纳入版本管理，真实密码留在私有环境。参考 project-management-be 的分层与 description 文档组织；可选删除流程取自 contract-service-be 的审核、回执及执行分离设计。

交付前用隔离数据从正式入口验证正常路径、越权、重复请求、并发、重启恢复和外部送达不明。记录命令、版本、观察结果与未验证项。当前模板只验收工具和部署契约。新增业务代码须属于派生项目的明确需求。

依赖由 router 指向 service，再由 service 调用 repository 和 infrastructure。数据访问与外部适配层不得反向依赖路由。仅在事务提交点、幂等判断、权限范围、外部协议限制等难以从代码推断的位置加中文注释，说明规则及原因。

description/ 下使用小写短横线文件名。project.md 汇总入口；api/ 记录外部接口；architecture/data/、architecture/workflow/ 记录数据与状态迁移；capability/application/ 记录用户可感知的能力；standard/ 记录跨模块规范。复制同层 template.md 并替换占位符，以相对链接关联能力、接口、配置和证据。变更输入输出时联动请求样例与异常用例；变更状态或索引时联动数据契约、恢复步骤与验收工具；变更配置时同时核对本地示例、上级 .env.example、compose.yaml 与部署说明。

业务人员提供映射服务器 SSH 配置并要求接到本机时，按[开发入口与钉钉隧道](description/capability/infrastructure/ssh-dev-mapping.md)发现现网配置、建立两条 FRP 链路、切换本平台开发路径并分别验收。
