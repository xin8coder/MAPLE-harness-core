# MAPLE 沙盒部署

部署一个可供内网和可选公网入口共用的 MAPLE 服务。该部署沿用应用的中文界面、
MAPLE 专用助手、上传、动态更新、方案选择和下载功能，不修改论文实验代码。

## 边界与要求

- 沙盒服务端需要 Linux x64、systemd 用户服务、bubblewrap、curl 和启用的用户命名空间。
- Windows/Linux 浏览器和远程桌面客户端均可连接服务端。Windows 本机原生启动不等于 Linux 沙盒隔离。
- 需要先安装本仓库的原生运行时和 Caddy。部署文件保存在源码目录外。
- 真实 API Key 只交给宿主上的 DeepSeek 专用代理。沙盒内仅保存占位密钥。
- 沙盒只挂载只读运行时、自身数据目录和两个 Unix socket，不挂载宿主用户目录或论文数据。
- 这不是对任意恶意代码的绝对安全保证。生产部署仍需维护系统更新、访问控制和资源配额。

## 安装

在解压的源码根目录运行：

```bash
# Ubuntu/Debian example; requires administrator permission for the OS package.
sudo apt-get install bubblewrap curl ca-certificates
bash start.sh --install-only
bash scripts/bootstrap_intranet.sh

# Substitute the actual private IPv4 address when sharing on your LAN.
"$HOME/.local/share/maple-harness/runtime/venv/bin/python" deploy/sandbox/setup.py \
  --bind 127.0.0.1 --start
```

安装器会交互读取 API Key 和自行设置的登录密码，输入不回显，不把密钥放在命令行。
默认账号名为 `admin`，没有默认密码。使用 `--username` 可以改变账号名。
已有原生应用凭据时，`--reuse-api-key` 可读取其密钥并只保存到宿主模型代理。

默认安装到 `$HOME/.local/share/maple-sandbox`。`--root` 可指定另外的私有目录，
但不能放入源码仓库。它是新实例，不会自动复制其他原生或内网实例的历史数据。
已有部署迁移时先备份，并明确核对会话、字段映射、产物及工作区路径，不要复制整个宿主目录。

默认 HTTPS 地址是 `https://127.0.0.1:3000/`。共享内网时把 `--bind` 换成服务器的
实际内网地址。Caddy 使用私有 CA，证书位于部署目录的
`run/caddy-front/caddy/pki/authorities/local/root.crt`。核对后导入可信客户端，勿全局关闭证书验证。

后台常驻可由管理员启用用户 lingering：

```bash
sudo loginctl enable-linger "$USER"
systemctl --user status maple-sandbox.target
```

这使服务独立于 VS Code 和 SSH 会话。安装器不会自行请求 sudo。
已占用的端口应通过 `--port`、`--gateway-port`、`--auth-port` 等参数选择其他值，
不要停止不属于该实例的服务。

## 可选公网入口

先单独安装官方 `cloudflared`，再在首次部署时选择 `--tunnel quick`，安装器会为
本实例增加隧道服务。临时地址写在部署目录的 `public-url.txt`，重建后可能变化。
首次注册服务前可去掉 `--start`，先核对配置。

正式入口建议使用自己的域名和命名隧道。按
[固定域名说明](../../docs/cloudflare-tunnel.zh-CN.md)配置，首次部署增加：

```bash
--tunnel named --public-origin https://maple.example.com \
--tunnel-token-file /path/to/private/tunnel-token
```

这里的域名和 token 路径是示例。Cloudflare 发布路由应指向登录网关
`http://127.0.0.1:18990`，不能指向 DSH 或 sidecar，不能绕过登录认证。
`--cloudflared` 可指定已安装的可执行文件路径。

## 升级和备份

先停止本实例并完整备份私有部署目录，再安装新原生运行时，最后更新沙盒部署文件：

```bash
systemctl --user stop maple-sandbox.target
bash start.sh --install-only
"$HOME/.local/share/maple-harness/runtime/venv/bin/python" deploy/sandbox/setup.py --update --start
```

`--update` 保留已有配置、账号密码、API Key、会话、上传和产物，不重新询问或覆盖它们。
使用自定义目录时仍须传入相同的 `--root`。自定义服务前缀用 `--service-prefix` 设置，
不同实例必须选择不同前缀和不冲突的端口。不要让两个实例同时写入同一个数据目录。

私有目录结构：

```text
maple-sandbox/
  app/         可升级的部署程序
  conf/        Caddy 与最小系统配置
  secrets/     API Key、密码哈希、会话签名秘密、可选隧道 token
  data/        会话、上传、优化状态、缓存与结果
  logs/        私有运行日志，可能包含配对链接
  run/         socket 与 Caddy 状态
  systemd/     此实例的用户服务
```

**不要上传上述部署目录、密钥文件、日志或备份。** 仓库中的文件只是通用部署程序，
不包含任何已部署服务器的账号密码、密钥、隧道 token、会话或优化结果。

## 离线隔离检查

模型代理启动后执行以下检查，不调用真实模型 API：

```bash
"$HOME/.local/share/maple-sandbox/app/sandbox.sh" \
  "$HOME/.local/share/maple-harness/runtime/venv/bin/python" /opt/maple-sandbox/probe.py
```

检查包括外网阻断、宿主凭据不可见、运行时只读、数据可写和代理路径白名单。
本地模型模拟的完整 DSH→MCP 检查为 `python scripts/smoke_maple_assistant.py`。
