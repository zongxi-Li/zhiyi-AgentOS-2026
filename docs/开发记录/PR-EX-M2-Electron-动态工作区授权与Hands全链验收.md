# PR-EX-M2 Electron 动态工作区授权与 Hands 全链验收

本轮在 PR-EX-M1 的 Electron 唯一桌面宿主和 Hands 正式执行链之上，增加用户选择真实 Windows 项目目录的动态授权闭环。

## 已实现

- Electron Main/Preload/PlatformAdapter 目录选择仍只返回候选路径；后端 `WorkspaceAuthority` 在现有 PostgreSQL/Flyway 中校验目录、规范化大小写、拒绝 `..` 与 reparse point，并签发稳定 `workspaceId` / `grantId`。
- 授权记录绑定用户、租户、资源和 Grant，支持查询、撤销和重启恢复。每个 Run 创建时冻结 `workspaceBinding`；工具审批后及执行前重新校验撤销状态、根身份和 Grant。
- Hands 服务按可信 Grant 的 canonicalRoot 选择动态 World；模型输入不能提供 `allowedRoot`、`grantId`、`workspaceId`、`resourceId` 或安全档位。`confinement=none` 继续标注为 host-approved，明确不是 OS 沙箱。
- `run_tests` 支持受信任的 Python `pytest`、Node `node --test` 和 `npm test`，收据保存 executable、argv、workdir、退出码、stdout/stderr、超时和取消状态。正式测试命令失败会让执行失败，不能把接收或非零命令当成功。
- 工作台显示当前工作区、授权风险、待授权目录和撤销按钮；文件浏览使用已冻结 Run 的授权上下文。

## 真实验证

独立 Home：`%LOCALAPPDATA%\\ZhiyiNative\\ex-m2-20261029`；Backend=hands；端口偏移 400；独立 Electron user-data、PostgreSQL、Memurai、Hands ledger 和项目目录。N03 default 未参与启停。

- `persistent.ps1 init/up/status -Desktop`：PostgreSQL、Memurai、Hands、Python、Java、Vite、Electron 均由独立 Home 启动并健康。
- Electron 登录测试账户后，`/api/agentos/v2/workspaces/current` 返回未授权状态；通过实际 Electron 前端授权 API 选择 `projects/python-project`，返回 `workspaceId`、`grantId`、root identity 和风险标记。
- 选择 `..` 路径被后端以 403 `Parent traversal is forbidden` 拒绝；授权后撤销返回 `revoked=true`，current 立即为空。
- Python 编译、Java Maven package、Electron 14 项测试、前端 `vue-tsc`、WorkspaceFileEditor 测试通过；Hands 回归保留历史 shell receipt 语义，正式测试命令单独按非零退出失败。

## 与 M1 的边界

M1 验收固定启动工作区和 Hands 正式执行/冷重启；M2 扩展为用户目录选择、可信后端动态 Grant、Run 冻结、撤销生命周期和 Python/Node 测试命令。仍不实施安装包、服务、自更新、签名或商业发布，不覆盖 N03 default 数据。

## 剩余风险

Windows 普通权限下 symlink/junction 夹具能力受系统策略限制；实现按真实 `lstat/realpath` 和 reparse 检查 fail-closed。`confinement=none` 仍是宿主权限命令模式，不宣称 OS 沙箱。完整 ACG Mission 需要真实模型凭据和人工审批队列；本轮已验证授权、撤销、路径拒绝和运行时绑定链路。
