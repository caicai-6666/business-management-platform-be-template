# 用 FRP 为一个钉钉应用建立固定出口

目标是让一个 AppKey 的所有业务副本经同一公网 IP 访问钉钉。选一台具有固定公网出口的 Linux 主机，确认其默认路由或云 NAT 始终使用同一 EIP。公网 IP 由出口路由决定，FRP 将业务连接送到这台主机上的正向代理。

```text
应用 → 本地 frpc visitor:22888 → TLS/STCP → 出口机 frps:7000
     → 出口机 frpc provider → 127.0.0.1:3128 Squid
     → 固定公网出口 → api.dingtalk.com:443
```

visitor 与 provider 均主动连接 frps。业务主机可位于 NAT 后。为这个应用分配独立的 FRP 凭据和 STCP 密钥，仅分发给其部署实例；按应用隔离 visitor 所在的主机或容器网络命名空间。控制端口 7000/TCP 仅允许业务侧和出口侧的受控地址接入。3128 和 22888 都绑定回环地址。

## 1. 准备二进制与配置

以下以已验收的 FRP v0.64.0 为例。在目标架构的 Linux 构建机安装 Git、make 和 Go 1.23 或该版本 go.mod 要求的更新版本，执行：

```sh
git clone --depth 1 --branch v0.64.0 https://github.com/fatedier/frp.git
cd frp
make build
bin/frps -v
bin/frpc -v
```

将 bin/frps、bin/frpc 安装到出口机 /usr/local/bin，业务机只需 frpc。也可选用上游同版本、对应操作系统和架构的发布包。上游项目及发行包见 [FRP v0.64.0](https://github.com/fatedier/frp/releases/tag/v0.64.0)。

取部署仓库的四个配置样例。将前三份安装在出口机，对应的 visitor 配置安装在业务侧。配置中 `{{ .Envs.变量名 }}` 由 FRP 从进程环境读取。

| 配置 | 安装位置 |
| --- | --- |
| [frps.toml](../../../../dingtalk-egress/frps.toml) | 出口机 /etc/frp/frps.toml |
| [provider.toml](../../../../dingtalk-egress/provider.toml) | 出口机 /etc/frp/provider.toml |
| [squid.conf](../../../../dingtalk-egress/squid.conf) | 出口机专属 Squid 实例 /etc/squid/squid.conf |
| [visitor.toml](../../../../dingtalk-egress/visitor.toml) | 业务进程网络空间 /etc/frp/visitor.toml |

## 2. 准备凭据、证书和环境

在私有凭据管理环境分别运行两次 `openssl rand -hex 32`，生成 FRP_TOKEN 和 FRP_STCP_KEY。部署负责人为 frps 准备带 DNS SAN 的服务端证书、私钥，以及两个 frpc 可读取的 CA 证书。可使用组织 PKI；服务端证书须覆盖 FRP_SERVER_NAME，证书链须可用该 CA 验证。以下变量通过服务管理器的私有环境文件注入，每个进程只分发该列所需的值，文件权限 0600。

| 进程 | 必填环境变量 |
| --- | --- |
| frps | FRP_BIND_ADDR（业务侧可路由的出口机地址）、FRP_TOKEN、FRP_TLS_CERT、FRP_TLS_KEY（后两项为文件路径） |
| provider | FRP_SERVER_ADDR（出口机上可达的 frps 监听地址）、FRP_SERVER_NAME、FRP_CA（CA 文件路径）、FRP_TOKEN、FRP_STCP_KEY |
| visitor | FRP_SERVER_ADDR（从业务侧可达的 frps 域名或 IP）、FRP_SERVER_NAME、FRP_CA、FRP_TOKEN、FRP_STCP_KEY |

provider 和 visitor 使用相同的 STCP 服务名和密钥。FRP_TOKEN 用于登录 frps。钉钉 AppSecret 只配置给业务后端。配置文件验证前先为当前进程加载上述变量。

## 3. 在固定出口机启动代理和隧道

在专用实例中安装 Squid，例如 Debian/Ubuntu 使用 `apt-get install squid`。先安装本模板的 squid.conf，再校验并启动。Squid 仅允许本机 provider 对 api.dingtalk.com:443 发起 CONNECT，HTTPS 由业务客户端与钉钉端到端建立。

```sh
squid -k parse -f /etc/squid/squid.conf
systemctl restart squid
frps verify -c /etc/frp/frps.toml
frps -c /etc/frp/frps.toml
```

在出口机另一进程启动 provider：

```sh
frpc verify -c /etc/frp/provider.toml
frpc -c /etc/frp/provider.toml
```

业务侧启动 visitor：

```sh
frpc verify -c /etc/frp/visitor.toml
frpc -c /etc/frp/visitor.toml
```

长期运行时分别用 systemd 或容器管理三个前台进程，设置故障重启和私有 EnvironmentFile。每个服务使用自己的配置文件和已验证的启动命令。扩容业务实例时为新实例启动 visitor，复用同一出口机。

### Compose 后端的 visitor

容器内的 127.0.0.1 属于容器自身。使用与部署节点架构匹配的 Linux 静态 bin/frpc，在上面构建出的 frp 源码目录执行：

```sh
docker build -t dingtalk-frpc:0.64.0 -f - . <<'DOCKER'
FROM scratch
COPY bin/frpc /frpc
ENTRYPOINT ["/frpc"]
DOCKER
```

把下列覆盖文件放在部署目录，命名为 compose.dingtalk.yaml。在部署目录创建私有文件 .env.frp-visitor（填写上表 visitor 的五项）与 frp-ca.crt；其中 FRP_CA 填容器内的 /etc/frp/ca.crt。

```yaml
services:
  dingtalk-visitor:
    profiles: [app]
    image: dingtalk-frpc:0.64.0
    pull_policy: never
    restart: unless-stopped
    network_mode: "service:backend"
    env_file: .env.frp-visitor
    volumes:
      - ./dingtalk-egress/visitor.toml:/etc/frp/visitor.toml:ro
      - ./frp-ca.crt:/etc/frp/ca.crt:ro
    command: ["-c", "/etc/frp/visitor.toml"]
```

在部署 .env 设置 `DINGTALK_PROXY_URL=http://127.0.0.1:22888` 和[应用凭据](dingtalk.md)。派生镜像已实现业务服务后执行 `docker compose -f compose.yaml -f compose.dingtalk.yaml --profile app up -d backend dingtalk-visitor`。更新 backend 和 visitor 时沿用相同 Compose 文件和项目名。此例两个容器共享回环地址，宿主机无需发布代理端口。

## 4. 配置白名单并验收

1. 从云 NAT 或出口防火墙的 SNAT 记录核对该代理访问钉钉时使用的固定公网 IP，在钉钉后台为对应企业内部应用加入该 IP。控制连接的 frps 入口地址可能与 SNAT 公网地址不同。
2. 在业务进程的网络空间执行 `curl --noproxy '' -x http://127.0.0.1:22888 -sS -o /dev/null -w 'CONNECT %{http_connect}\n' https://api.dingtalk.com/`。预期 CONNECT 200；用 https://example.org/ 重试应在 CONNECT 阶段收到 403。业务镜像缺少 curl 时使用共享同一网络命名空间的诊断容器。
3. 用该应用运行接入指南中的 check_application，随后调用一个已获授权的只读接口。记录应用代号、时间、出口 IP 与状态；凭据、令牌和返回的业务正文均不进入验收记录。
4. 在隔离环境停止 provider，再用新客户端请求应用令牌，应收到连接异常；恢复 provider 后重新验收。CONNECT 失败优先检查 visitor 监听、TLS 主机名、STCP 密钥、Squid 的域名与端口规则。CONNECT 成功但业务被拒绝时，核对应用白名单、凭据和接口权限。

同一应用新增旧版 OpenAPI 或媒体域名时，先确认服务端实际目标及该接口的授权，再逐项增加代理白名单。数据库、中间件和服务端入站回调使用各自的网络配置。

已有映射机 SSH 配置时，接入本机的步骤见[本机开发映射](ssh-dev-mapping.md)。
