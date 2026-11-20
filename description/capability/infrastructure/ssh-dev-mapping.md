# 通过 SSH 将开发入口和钉钉隧道接到本机

业务人员可以直接告诉派生项目的 Codex：“映射机的 OpenSSH Host 别名是 dev-map，把本项目开发入口和钉钉出口接到本机，验证后告诉我开发地址。”也可提供 HostName、User、Port 和本机 IdentityFile 路径，由 Codex 写入用户私有 SSH 配置。密钥由本机 SSH agent 或 OpenSSH 读取。已登记的服务器指纹、具备相应权限的账号、可用的固定出口和本机已实现的业务入口是联调条件。真实钉钉令牌验收还需要该应用自己的凭据与白名单。

## Codex 接手后的操作

1. 从派生项目前端 base、路由和开发服务器配置确定平台代号、本机端口与 API 代理目标。从项目说明核对归属。仅当模板尚未命名且仓库也推不出唯一代号时，请负责人指定。启动业务服务，以完整开发路径访问页面、一个静态资源和只读 API，记录能辨认这个实例的响应。让本机开发服务器只接受实际开发域名和本机 Host。
2. 使用独立 SSH 别名，先运行 `ssh -G dev-map` 在本机核对解析结果，再以 `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes dev-map true` 验证身份。别名使用普通 SSH 会话配置，无 RemoteCommand 或附带的转发。新主机先通过管理员提供的指纹核对主机密钥。私钥、FRP 令牌、STCP 密钥和钉钉 AppSecret 均不进入聊天、Git 或验收输出。
3. 通过 SSH 查看 `ss -lnt`、运行的服务单元和容器的名称、端口、挂载，定位开发域名实际生效的网关、frps、frpc provider 和专属代理。按进程定位配置源，仅读取需要的字段。记录域名、匹配本平台的 location、上游地址、FRP 版本、代理类型、控制监听、端口范围、服务管理方式，以及 nginx 和 frps 是否共用网络空间。不要把整份 nginx 配置、进程环境或 docker inspect 输出带入日志。
4. 如果已有隧道恰好到达本机，可复用并做下述验收。已有入口指向其他开发机时，为本机建立独立候选隧道，验证后仅切换该平台的网关上游。映射机承载多平台时，保留公共 /dev 入口、其他平台及生产路径。已有钉钉出口先核对 AppKey 归属和出口 EIP，再接入对应 provider。
5. 下面两条链路可以使用同一 SSH 别名。业务 Codex 从以上发现生成私有服务配置，选择未占用的端口，安装匹配服务端版本的 frpc，并执行启动、验收和回滚。示例端口是演示值。两个本地控制端口必须不同。部署仓库中的命令从部署根目录运行。

## 开发网页和 API 入站

流量为浏览器 → 开发域名 HTTPS 网关 → 映射机专用 FRP 上游端口 → 本机 frpc → 本机前端或开发网关。前端按完整前缀转发 API。如派生项目有独立的 API 上游，按同样方式注册独立代理并匹配更具体的 API 路径。

同机 Nginx 与 frps 可使用 [TCP 入站配置](../../../../dev-mapping/ingress.toml)。确认 frps 的 **proxyBindAddr** 为 127.0.0.1，且允许分配的 remotePort；TCP 代理监听地址由 frps 决定。共享 frps 不满足隔离条件时，部署独立 frps：取[服务端样例](../../../../dingtalk-egress/frps.toml)，设 FRP_BIND_ADDR 为 127.0.0.1，改用空闲 bindPort，在顶层加入 `proxyBindAddr = "127.0.0.1"` 及 `allowPorts = [{ single = 24180 }]`，为实例单独生成令牌与 TLS 证书，verify 后作为独立服务启动。容器化网关使用其可达的私有网络地址并限制来源，须从网关网络空间验证连通。现网若使用 HTTP vhost 或共享开发网关，沿用其域名和路径分流方式，在实际分流层添加本平台路由。

在本机私有环境加载 FRP_TOKEN、FRP_CA、FRP_SERVER_NAME（证书 SAN）、FRP_INGRESS_NAME（本平台、本机唯一）、FRP_APP_PORT（本机开发服务）、FRP_UPSTREAM_PORT（映射机候选端口）。例如映射机 frps 控制端口为 7100，在本机执行：

```sh
./dev-mapping/connect.sh dev-map 7100 27100 ./dev-mapping/ingress.toml 127.0.0.1
```

该入口会校验配置，通过 SSH 将本机 27100 转到映射机可达的 frps，再以前台进程运行 frpc。最后一个参数是从 SSH 服务器看见的 frps 地址。先从网关网络空间访问候选上游并携带真实 Host，再修改生效的虚拟主机。例如平台代号为 inventory、映射机候选端口为 24180 时，目标 location 的核心配置如下：

```nginx
location ^~ /dev/knowledge-accumulation/inventory/ {
    proxy_pass http://127.0.0.1:24180;
    proxy_set_header Host $host;
    proxy_http_version 1.1;
    proxy_buffering off;
}
```

保留原站点的鉴权、转发头、上传限制、SSE 超时和 WebSocket Upgrade/Connection 配置。涉及独立 API location 时检查匹配优先级。proxy_pass 末尾省略斜杠以完整保留路径；无尾斜杠的页面入口按站点惯例重定向到带斜杠地址。

## 本机钉钉请求出站

流量为业务客户端 → 本机专属 visitor → FRP STCP → 固定出口机 provider → Squid → 钉钉。SSH 只需连到能访问该 frps 的映射机。先确认固定出口机和应用白名单；两者是不同主机时，从映射机核实到出口 frps 的可达地址。新建出口按[单应用固定出口](dingtalk-frp-egress.md)部署出口机的 frps、provider 和受限 Squid；全部客户端都走 SSH 且同机运行时可将 frps 控制端口仅绑定回环。各应用单独配置凭据、服务名和端口。若需要管理另一台出口机且当前身份无权限，记录缺少的主机访问授权。

在本机私有环境加载**出口实例**的 FRP_TOKEN、FRP_STCP_KEY、FRP_CA 和 FRP_SERVER_NAME。已有 provider 时在 visitor 私有副本中对齐 serverName（STCP 代理名）、FRP 服务端证书名、visitor 本地端口与凭据。示例使用同一映射机上已有的 7000 控制端口：

```sh
./dev-mapping/connect.sh dev-map 7000 27000 ./dingtalk-egress/visitor.toml 127.0.0.1
```

宿主机后端使用 `DINGTALK_PROXY_URL=http://127.0.0.1:22888`。容器后端按出口指南使用共享网络空间的 visitor；走 SSH 时也把 SSH 本地监听放在同一网络空间，或使用受限且从 visitor 可达的控制转发地址。AppSecret 只由业务后端读取。SSH 别名只用于建立隧道，本机与 frps 的 TLS 主机名仍须匹配证书。

## 生效、验收和撤回

- 切换前为目标网关文件保存私有备份、校验和与原上游。沿用现网部署锁或变更流程；落盘前比对校验和以免覆盖并发编辑。候选上游验收通过后原子替换目标配置，在实际服务或容器中执行 nginx -t，成功再 reload。语法失败时先恢复文件。若 reload 回执不明，核对生效上游与公网响应后决定下一步。
- 从真实 HTTPS 入口访问首页、深层链接、静态资源和只读 API，对比本机实例标识，并复查一个相邻平台路径。使用 Vite 热更新时验证 WebSocket 升级。只有公网入口与候选上游的结果一致才算完成切换。
- 从后端网络空间按出口指南检查 CONNECT：钉钉域名返回 200，非白名单域名返回 403。核对该 AppKey 的 SNAT 地址，再运行应用令牌检查及已授权的只读请求；缺少应用凭据时只记录隧道级结果。
- 用用户级 systemd 或 launchd 托管两个 connect.sh 前台命令，分别注入权限 0600 的私有配置及绝对路径，并配置退出后重启。SSH 断开会终止本次 frpc；恢复后复验两条路径。重复执行时复用同一项目服务、候选端口与路由，避免创建重复代理。
- 撤回时仅还原本次修改的路由，检查配置自变更后未被其他人编辑，再执行 nginx -t 和 reload，确认原上游恢复后停止本项目新增的客户端、专属监听及服务。将变更时间、开发 URL、原/新上游、服务名和各项验收结果写入派生项目的私有部署记录。
