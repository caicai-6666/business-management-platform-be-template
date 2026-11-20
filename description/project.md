# 项目说明（派生时填写）

专题列表见[项目文档导航](readme.md)，编写派生项目文档时参照[文档撰写规范](documentation.md)。

| 需要决定的事项 | 业务负责人填写 |
| --- | --- |
| 平台名称、代码、业务负责人、技术负责人 | 待填 |
| 用户、首个场景及可验收结果 | 待填 |
| 本平台负责的记录、唯一身份和生命周期 | 待填 |
| 角色、权限范围和审核职责 | 待填 |
| 上游身份与消息来源、下游文件和索引责任人 | 待填 |
| 数据保留期限、备份恢复目标 | 待填 |

按业务场景从[能力样板](capability/application/template.md)开始。涉及接口时补[接口契约](api/template.md)，涉及存储时补[数据契约](architecture/data/template.md)。设计可参考[检索验收](architecture/data/search.md)及[可选删除审核](architecture/workflow/deletion-review.md)。上线前按[验收记录](standard/acceptance.md)填写证据。

开发环境预置 Python 3.12、SQLite 和 MySQL 8.4。MySQL 的中文全文与向量检索使用 ngram 和 MyVector，启动与接入见 [MySQL 指南](architecture/data/mysql.md)。SQLite 主库的初始化、事务边界、备份和恢复见 [SQLite 主库操作指南](architecture/data/sqlite.md)。

需要主动调用钉钉时，登记应用与固定出口负责人，按[钉钉应用接入](capability/infrastructure/dingtalk.md)和[FRP 部署指南](capability/infrastructure/dingtalk-frp-egress.md)配置应用白名单。

涉及跨平台协作时，在上表登记平台代号、对接负责人及启用的消息流，按[中间件接入指南](api/middleware.md)完成联调。

本机联调时将映射服务器 SSH 别名交给 Codex，参见[本机开发映射](capability/infrastructure/ssh-dev-mapping.md)。
