<div align="center">

<img src="src/liveopt_dsh/assets/maple-logo.png" width="80" alt="MAPLE Harness 标识">

# MAPLE Harness

**用自然语言提出需求，比较优化方案，在对话中持续调整。**

[下载 v0.2.0](https://github.com/xin8coder/MAPLE-harness-core/releases/tag/v0.2.0) · [中文使用指南](docs/user-guide.zh-CN.md) · [产品演示](https://xin8coder.github.io/MAPLE-harness/) · [English](README.md)

</div>

MAPLE Harness 将自然语言需求和上传的数据转成可计算的优化任务，展示求解进度、目标变化和备选方案，并在后续需求变化时继续修改同一个任务。可用于生产安排、仓储分配、人员排班、配送等规划场景，不限于示例中的服装行业。

## 下载与启动

从 [Releases](https://github.com/xin8coder/MAPLE-harness-core/releases/latest) 下载并**完整解压**：

| 平台 | 推荐文件 | 启动方式 |
|---|---|---|
| Windows 10/11 x64 | `MAPLE-Harness-0.2.0-source.zip` | 双击 `start.cmd`。 |
| Linux x64 | `MAPLE-Harness-0.2.0-source.tar.gz` | 在解压目录执行 `bash start.sh`。 |

这两个包都包含**完整网页版和后端**。启动器会自动下载私有的 Python、Node 和依赖，无需预装 Python/Node，也不需要管理员权限、WSL 或 Docker。Linux 需要 `curl`、`tar`、CA 证书和 glibc 环境，例如 Ubuntu/Debian。启动器也提供 Linux arm64 路径，但原生 CI 目前验证的是 x64。

首次安装需要联网，可能耗时几分钟；之后会复用已安装的依赖。启动成功后自动打开浏览器。使用期间保留终端窗口，按 Ctrl+C 停止服务。没有桌面的 Linux 服务器会显示访问链接，可结合 SSH 端口转发或内网部署使用。

## 第一次使用

1. 在 **Settings → MAPLE Harness** 中填写 DeepSeek API Key。真实调用使用你的账户额度；应用各角色固定使用 `deepseek-flash`，不调用 Pro。
2. 选择工作区并新建对话。用自然语言说明要做什么、想优化什么、哪些条件不能违反，用 **Document** 上传 Excel、CSV、JSON 或支持的文档。
3. 可以先要求智能体检查数据，不要立即求解。需要时选择精确求解或遗传算法，也可以交给智能体判断。
4. 求解中查看进度组件。完成后在 **Solutions（方案）** 查看各目标曲线、最终种群和帕累托解；打开独立方案窗口可高亮查看并选择可行方案。
5. 在**同一个对话**中提交更新，例如提前交期、减少人员或修改资源条件。系统会基于已接受的任务继续求解，并显示重启和解复用情况。
6. 从结果中下载 CSV、JSON 和 ZIP 等产物。

应用支持中文和英文。中文提问会得到中文回复，不需要额外加“请用中文回答”。中文表头可由 LLM 辅助做字段映射，并保留原始名称用于结果展示。默认遗传算法迭代上限为 **100**，可在设置中调整。

浏览器不要求注册账号或输入应用用户名/密码。启动链接用于配对本机服务，包含访问令牌，请不要公开转发。

## 直接试用中文 Excel 示例

[服装外贸示例目录](examples/garment_export/inputs/chinese/)包含：

- `服装外贸排产数据.xlsx`：订单、班组、仓区及规则。
- `初始需求.txt`：要求先检查数据、确认求解方式。
- `确认求解.txt`：确认使用小规模遗传算法，同时考虑费用与逾期。
- `更新需求.txt`：在原任务上提前交期、减少人员，再比较新旧结果。

按这个顺序发送请求，并在初始请求中上传 Excel。完整步骤见[中文使用指南](docs/user-guide.zh-CN.md)。

## 网页部署包与桌面客户端

**在本机一键部署并打开网页，请使用 source ZIP/tar.gz。** `desktop/` 及单独标注的桌面安装包是连接既有服务器的远程客户端，不包含本地优化后端。不要将它当成完整部署包。

## 数据保存与升级

Linux 默认保存到 `~/.local/share/maple-harness`，Windows 默认保存到 `%LOCALAPPDATA%\MAPLEHarness`。任务、历史和产物不保存在解压目录里。

升级前备份这个目录，停止旧启动器，然后解压新版并使用同一应用目录启动。旧的 `liveopt-dsh` 部署不会自动导入，也不要让两个服务同时写入同一份状态。

首选端口为 **3000**，占用时自动选择空闲端口。静默安装使用 `start.cmd -InstallOnly` 或 `bash start.sh --install-only`；不自动打开浏览器使用 `start.cmd -NoBrowser` 或 `bash start.sh --no-browser`。

代理、内网访问、后台常驻、备份和排障见[运维指南](docs/operations.md)。系统会执行生成的 Python 问题代码，请在可信环境使用，或为非可信用户提供适当隔离。

## 版本与验证

本版本基于官方 **DSH 0.2.1-rc.2**，完整主机依赖已锁定。Windows/Linux 原生 CI 覆盖从零安装、应用测试、网页配对、中文上传、方案静态资源和 DSH→MCP 工具调用。测试使用本地模型模拟器，不消耗付费模型额度。

发布包提供 `SHA256SUMS`，源码文件和核心快照由 `RELEASE_MANIFEST.json` 记录。应用仓库与论文实验代码、缓存相互独立。

## 许可

项目采用 [ISC License](LICENSE)。DeepSeek Harness 保留上游 MIT 许可与来源说明，其他第三方许可随包保留。
