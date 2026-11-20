# 钉钉企业内部应用接入

派生平台可以用企业内部应用身份主动调用新版钉钉 OpenAPI。应用负责人管理钉钉后台的凭据、接口权限与发布范围；部署负责人管理该应用的固定出口。模板默认关闭对接。

## 在钉钉后台准备应用

1. 进入钉钉开放平台开发者后台，选择目标企业，创建或打开对应的企业内部应用。记录企业 CorpId 以及该应用的 AppKey（Client ID）、AppSecret（Client Secret）。同一个平台的测试和生产身份分别由负责人确认。
2. 在应用的权限管理中按将要调用的接口开通权限，按企业流程完成授权并发布相应版本。例如，读取审批实例时核对该接口要求的审批读取权限。记录接口、获准权限及可见范围。
3. 在该应用的服务器出口 IP 白名单中登记出口网关实际用于访问互联网的固定公网 IPv4（云上可能是 NAT 网关的 EIP）。多个业务副本访问同一 visitor 或各自的 visitor，最终都经同一出口代理转发。[FRP 单应用固定出口搭建](dingtalk-frp-egress.md)

## 配置与调用

Compose backend 从部署目录私有 .env 取得下列配置。直接运行 Python 时，把变量导出到进程环境。身份与代理四项全空时 `DingTalkSettings.from_env()` 返回 None，部分填写时报告配置错误。

| 变量 | 用途 |
| --- | --- |
| DINGTALK_CORP_ID | 企业身份标识 |
| DINGTALK_APP_KEY、DINGTALK_APP_SECRET | 内部应用凭据，用于向钉钉申请应用令牌 |
| DINGTALK_PROXY_URL | 该应用的 HTTP/HTTPS 正向代理地址。FRP visitor 与应用共享网络命名空间时填 http://127.0.0.1:22888 |
| DINGTALK_TIMEOUT_SECONDS | 单次 HTTP 请求总超时，默认 30 秒 |

```python
from app.config.dingtalk import DingTalkSettings
from app.infrastructure.dingtalk import DingTalkClient

async def check_application():
    settings = DingTalkSettings.from_env()
    if settings is None:
        return "未启用"
    async with DingTalkClient(settings) as client:
        await client.access_token()
        return "应用认证成功"
```

业务 service 在应用生命周期内复用一个 DingTalkClient。客户端通过 `POST https://api.dingtalk.com/v1.0/oauth2/accessToken` 获取令牌，按 expireIn 提前刷新，并用异步锁合并并发刷新。调用 `await client.request("GET", "/v1.0/…", params={…})` 时传入已获授权的真实接口路径和查询参数，客户端添加 x-acs-dingtalk-access-token 头并返回 JSON。写请求超时可能已经送达；401 使缓存失效，下次调用重新取令牌。业务方按接口契约处理返回体和幂等。

模板将取令牌和后续请求都限定在同一显式代理上，校验目标 TLS 证书。代理断开时返回 DingTalkError。后台入站 OAuth 回调和事件订阅属于单独的接入链路。本次实现范围为企业内部应用主动 HTTP 请求。
