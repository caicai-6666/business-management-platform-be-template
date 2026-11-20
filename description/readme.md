# 项目文档导航

派生项目先在[项目说明](project.md)中填写业务对象、权威数据、角色和系统负责人。新增或修改专题时，按[文档撰写规范](documentation.md)选择位置并更新本页。

## 定义第一个业务场景

| 要回答的问题 | 从哪里开始 |
| --- | --- |
| 谁要完成什么任务，如何判断成功？ | [业务能力样板](capability/application/template.md) |
| 调用方传什么、收到什么，失败后如何处理？ | [接口契约样板](api/template.md) |
| 哪个系统保存权威记录，谁可以变更状态？ | [数据契约样板](architecture/data/template.md) |
| 审批、执行和回执如何区分？ | [可选删除审核设计](architecture/workflow/deletion-review.md) |

## 接入模板基础设施

- 初始化主库、开启事务或恢复快照，见 [SQLite 操作指南](architecture/data/sqlite.md)。
- 为连续中文建立全文索引，或按距离查询向量，见 [SQLite 检索指南](architecture/data/search.md)。
- 使用 MySQL 业务账号连接数据库、查询中文全文和向量，见 [MySQL 操作指南](architecture/data/mysql.md)。
- 接入平台会话、用户身份与审核消息，见[中间件接入指南](api/middleware.md)。
- 钉钉企业内部应用的凭据、令牌与主动请求见[应用接入](capability/infrastructure/dingtalk.md)，出口机与业务侧的部署步骤见[FRP 单应用固定出口](capability/infrastructure/dingtalk-frp-egress.md)。

- 通过映射机 SSH 将开发入口与钉钉出口接到本机，见[本机开发映射](capability/infrastructure/ssh-dev-mapping.md)。

## 核对验收结果

查阅模板已运行的命令、版本和观察结果，见[模板验收记录](standard/template-checks.md)。派生项目验证自己的业务场景时，复制[验收记录样板](standard/acceptance.md)，填写实际结果和未验证项。
