# 本地工作区自由选择

日期：2026-10-30。

## 问题与改动

默认 N03 使用 Python Host。此前工作区 API 仅确认启动时的固定根目录，选择其他目录会被拒绝；动态 PostgreSQL 工作区授权仅接入 Hands。

本次把同一工作区授权接入默认 Python 后端，不更换执行后端，不移动数据，不重建环境：

- `WorkspaceAuthority.canonical_directory` 接受当前操作系统用户可访问的真实目录。去除磁盘根目录、目录链接、UNC 和路径规范化的额外禁令；保留绝对路径、目录存在性和根身份校验。目录链接保存为真实路径。
- N03 两种后端共用 PostgreSQL 授权与原子 JSON 投影，启动时重新从 PostgreSQL 投影。保留原 `hands-grants.json` 路径，避免另建第二个权威。
- Python `ProjectedGrantStore` 每次授权重新读取投影，实时识别选定目录、新 Grant 和撤销。调用方与能力集合仍受已有 Host 配置限制，破损投影拒绝授权。
- Chat 在工具审批前绑定当前用户选择的工作区，并在该次调用中保持不变；审批期间切换目录不会让操作落入另一个目录。
- 已有冻结目录的 Run 继续使用原目录。没有冻结目录的旧 Python Run 仍能读取启动目录；新建或重跑时可冻结用户当时的选择。

本次放开目录选择；登录、用户与租户隔离、工具执行审批、相对文件路径边界和操作系统权限未变。网络目录未配置可用共享进行真机验证，只确认应用不再主动禁止此类目录。

## 验证

- 本地 Host 全套：52 passed，1 skipped。
- 目录选择、Chat 绑定与真实 Chat→Host HTTP：14 passed。
- 工作区 API / 语义边界回归：74 passed，包含旧 Python Run 浏览与重跑兼容。
- 生产权威装配及失败清理：33 passed。
- N03 启停与启动器：37 passed。
- 扩展 Pack 回归中另有 2 项失败：原始 `HEAD` 的 wiring 在独立测试进程中复现相同失败（测试规划器输出 / 拓扑前置能力问题）。保留 `tmp/workspace-agent-regression.log` 与 `tmp/workspace-agent-baseline.log`，没有修改这些测试或放宽门禁。

真实本机验收 `tmp/workspace-selection-live-receipt.json` 为 PASS：

1. 通过已有内部认证 HTTP 接口选择启动目录外的两个临时文件夹，签名调用运行中的 Python Host，分别读到各自内容。
2. 选择磁盘根目录并由 Host 正确解析。
3. 选择目录 junction 并从其真实目标读取文件。
4. 其他身份不能撤销授权；撤销后 Host 拒绝原 Grant；未认证选择返回 401。

验收使用独立临时身份，结束时只删除该身份的测试授权并重新投影；临时目录与测试行均已清理，没有改变真实用户的所选工作区。没有创建、执行或重放业务 Run。

## 生效与数据保留

已通过既有 N03 生命周期优雅重启服务，完整状态为 UP。原有 PostgreSQL、SQLite、账户和工作区目录保留。重启前后 Run 状态计数一致：completed 93、failed 100、cancelled 4、waiting_review 2；停止无强制升级。

旧 Run 兼容修正后只对 Python 服务做了一次身份核验后的优雅重载，其他服务未重启；`tmp/workspace-ai-refresh.json` 确认全部服务 alive、整体 UP。

在界面中选择目标目录并点击信任即可，无需重新初始化环境。使用宿主当前 Windows 用户权限，不能绕过系统 ACL 或网络共享自身的访问要求。
