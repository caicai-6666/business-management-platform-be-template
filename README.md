# 通用业务管理平台后端模板

这个目录供业务负责人和研发共同定义新平台。可直接运行检索验收工具，也可在本机模拟或专用测试平台上检查中间件接入。HTTP 服务、表结构和审批执行器由派生项目按需求实现。

查找接口、数据库指南和验收记录，请从[项目文档导航](description/readme.md)进入。

## 业务人员从这里开始

1. 复制本模板，在[项目说明](description/project.md)中填写平台名称、负责人和记录范围。用一句话写清谁遇到了什么问题。
2. 拿一条虚构记录走一遍流程。例如，经办人提交设备验收单，负责人决定是否通过，经办人查看结果。写下每一步谁能看、谁能改、遇到退回怎么办。
3. 复制[能力样板](description/capability/application/template.md)，把上述例子写成可以核对的结果。让经办人确认重复点提交、无权查看和服务重启时应看到什么。
4. 研发在隔离环境通过正式入口跑通这些例子，回填观察结果。业务负责人核对页面或导出结果后在能力文档记录日期和结论。

## 复制与提交范围

复制模板时保留隐藏文件。后端根目录的 `assets/` 用于字体、静态模板等运行资源，初始只随仓库分发 `.gitkeep`。正式源码、文档、配置样例和公开命令的依赖随模板交付。运行数据库、私有配置、本地素材、临时脚本和实验结果留在本机。后端与上级部署目录各自管理 Git 规则；新增交付文件时，在所属仓库用 `git status --short --untracked-files=all` 核对。

## 开发环境

Python 依赖和镜像分别由 [requirements.txt](requirements.txt) 和 [Dockerfile](Dockerfile) 定义。在上级部署目录运行 `docker compose run --build --rm check`，即可用模板镜像验收 SQLite 中文全文与向量检索。主库的初始化、事务和备份命令见 [SQLite 指南](description/architecture/data/sqlite.md)。

MySQL 使用部署目录的 Compose 服务，预装中文 ngram 和 MyVector。业务账号连接、启动命令和查询样例见 [MySQL 指南](description/architecture/data/mysql.md)。

## 接入中间件

需要统一登录、入库或删除审核时，先向中间件管理员领取测试平台代号、密钥和地址，模板已实现平台登录与持续心跳、文件送审、删除送审、两类审核结果及文件等级调整消费。派生服务注册提交后确认的业务回调。配置、命令和代码示例见[中间件接入指南](description/api/middleware.md)。

## 接入钉钉

企业内部应用调用 OpenAPI 时使用专属固定出口。业务 Codex 按[应用接入](description/capability/infrastructure/dingtalk.md)准备身份与权限，部署 Codex 按[FRP 单应用固定出口](description/capability/infrastructure/dingtalk-frp-egress.md)构建隧道并验证代理。

## 可以复制给开发助手的第一段话

> 请先阅读 AGENTS.md，再为设备验收小组梳理首个场景。经办人提交设备编号和验收说明，负责人可以通过或退回，经办人只能查看本人记录。用虚构设备 EQ-001 举例：资料完整时负责人可以通过，缺少说明时提示补充，两次点击提交只产生一条待审记录。首轮只覆盖提交、审批和结果查询，先读 description/project.md，把角色、状态和验收例写入能力文档，列出需要我确认的规则。请等我确认后，再在派生项目中实现这一条流程。

将设备、角色、示例和预期换成自己的业务用语即可。
