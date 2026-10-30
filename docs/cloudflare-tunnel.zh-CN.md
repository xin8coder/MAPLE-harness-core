# 固定域名访问 MAPLE

固定入口使用 Cloudflare 管理的命名隧道和自己的域名。应用、会话和数据仍在
MAPLE 服务器上，Cloudflare 负责公网流量转发。

## 准备域名

1. 注册 Cloudflare 账号，并购买或使用自己已有的域名。
2. 在 Cloudflare 控制台添加域名，按引导修改域名注册商处的 nameserver。
3. 等待域名状态变为 Active。无需把域名注册商也迁移到 Cloudflare。

## 创建隧道

按照 [Cloudflare 官方指南](https://developers.cloudflare.com/tunnel/get-started/)，
在控制台的 **Networking → Tunnels** 创建命名隧道，例如 `maple-production`。
为运行 MAPLE 的服务器选择系统和架构，并按页面提示安装连接器。

连接器的 token 是服务器凭据。不要写进仓库、截图、聊天记录或公开命令示例。
正式部署将 token 保存在服务器的私有配置中，通过后台服务运行连接器。
不要让原生安装命令覆盖已有的隧道服务，应先核对现有 systemd 配置。

## 绑定公开地址

在隧道的 **Routes → Add route → Published application** 中填写：

| 字段 | 示例 |
|---|---|
| Hostname | `maple.example.com`，替换为自己的域名 |
| Service URL | 已有登录网关的本地地址，例如 `http://127.0.0.1:18990` |

不要指向原始 DSH 端口或绕过登录网关的 sidecar 端口。服务器入口应同时允许
新域名作为合法 Origin，以便聊天连接、上传、下载和方案选择继续正常工作。

确认新地址能登录、读取历史会话、上传数据、显示优化进度并下载结果后，再停用
临时 `trycloudflare.com` 隧道。固定隧道重启后保留绑定的域名，不依赖随机地址。

## 安全和运行

- 固定域名不会改变 MAPLE 账号验证和沙盒边界。
- 内外网入口可以连接同一个沙盒并共用数据，无需启动第二套优化服务。
- 连接器作为后台服务运行，退出浏览器或 VS Code 不影响服务器进程。
- 公网流量经过 Cloudflare。按数据管理要求选择是否公开业务数据的入口。
- 不要将临时地址简单地设置为自有域名的 CNAME，正式入口应绑定命名隧道。
