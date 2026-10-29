# 工作区文件编辑器与自主选目录实施记录

日期：2026-10-29。基线 HEAD：`88c04151`。本轮未提交 Git。

## 已实现

右侧“文件”现可打开 Windows 原生文件夹选择器，自主选择本机目录。点击文件在中央编辑区打开独立标签，与 canonical Artifact 标签并存。提供行号、Ctrl+S、保存按钮、未保存标记、Tab 缩进、重新读取、关闭/离开前确认；文件内容按文本呈现，不执行 HTML。切换标签保留草稿。

手动选定的文件夹不依赖启动脚本固定工作区，也不依赖 Python/Hands 的编辑版本令牌。显示隐藏目录和依赖目录，按展开动作读取目录。支持 UTF-8 文本（最大 16 MiB），原生操作仍受当前 Windows 用户权限约束。二进制和其他编码有明确提示。

Main 仅接受原生选择器登记的文件夹 ID，Renderer 不传任意 allowedRoot。文件夹选择保存在当前 Electron userData 的 `workspace-folders.json`，重启恢复。手动编辑使用窄 IPC 文件接口，未添加命令执行、Planner 或 Agent Loop。保存使用内容版本比较、同一进程同一文件的保存队列、同目录临时文件替换；外部冲突拒绝并保留草稿，不自动重试不确定保存。

启动时任务工作区的正式 API 路径也保留：Vue → Java JWT Gateway → Python Mission ownership/工具权限 → LocalRuntimeClient → Hands HTTP/HMAC/Grant。补充 Java 的 list/read/save 转发；规范 Hands 目录返回的相对路径。版本化读取与 expectedVersion 条件写入复用 DSH 合同。人工 Save 仅在该次已认证请求内通过原有权限服务解决一次 fs.write 审批；DENY 仍拒绝，不创建 session 授权。

选择编辑目录不等于给 Agent 自动执行新增 Grant；ACG、ExecutionPermit 和自动工具审批保持原合同。当前选目录功能服务于手动文件编辑。

## 真实 Windows/Electron 验证

独立 Home：`%LOCALAPPDATA%\ZhiyiNative\ex-m1-20261029`。端口：Java 18280、Python 18961、Hands 18965、前端 15400、Electron CDP 19422。未切换 default 环境或改动系统服务。

| 验证 | 结论 | 证据 |
| --- | --- | --- |
| 真实 Windows 原生选择器选择 Runtime 根目录外文件夹 | PASS | 使用 Windows UI Automation 操作实际“打开工作文件夹”对话框；目录为 artifacts/windows/workspace-explorer/user-selected-folder |
| 文件树、中央标签、隐藏目录、切换标签 | PASS | electron-editor-after-restart.png；verify-editor.js |
| Ctrl+S 写入实际磁盘 | PASS | user-selected-folder/hello.py；acceptance.json 的 SHA256 |
| 外部修改后拒绝旧版本保存、草稿保留 | PASS | prepare-conflict.js、verify-conflict.js、electron-conflict-final.log |
| 未保存时取消关闭，草稿保留 | PASS | verify-reload-save.js、electron-reload-save.log |
| 正常退出并重启桌面后恢复目录和文件 | PASS | electron-close.log、electron-restart.log、electron-restart-e2e.log、electron-editor-after-restart.png |
| 原任务工作区经 Java/Python/Hands 真实保存并恢复原文 | PASS | electron-hmac-save-restored.log；测试 Home ai.log 中 workspace/file 两次 POST 200；临时 probe 注释已恢复 |

证据目录：`artifacts/windows/workspace-explorer/`。测试窗口留在所选目录，便于人工检查。测试区内只写入独立样例；未更改 default 用户文件。

## 回归

- Java：41 项通过，java-editor-tests.log；隔离 JAR 构建通过，backend-editor-build.log。
- Python API：3 项通过，python-editor-final.log；包含越界拒绝、旧版本不写入、一次审批及请求不能声明 allowedRoot。
- 前端：33 项通过，frontend-editor-tests-final.log；Electron 模式 vue-tsc 通过。
- Electron：14 项通过，electron-editor-tests-final.log；包含真实文件 I/O、隐藏目录、原生保存、恢复、二进制拒绝、冲突及并发保存只有一方成功。TypeScript 通过。
- Hands：最终串行 95/95，hands-editor-serial-final.log；TypeScript 通过。
- 首次 Hands 并行 93/95，两项短超时探针未观察到启动输出。原始日志 hands-editor-tests.log 保留；单文件复验 16/16、最终全套串行 95/95，没有修改命令超时或安全策略。
- 原始截图等待和全局草稿等待的超时记录保留；后续独立截图、作用域内检查、磁盘内容及 HTTP 日志确认结果。不可把早期超时日志单独视为全部验收通过。

## 源码范围

- `apps/desktop/electron/src/lib/workspace-files.ts`、`ipc-contract.ts`、`main.ts`、`preload.ts`、对应原生 I/O 测试：人工选目录、记忆和文件操作。
- `apps/frontend/src/components/workbench/WorkspaceFileEditor.vue`、Explorer、EditorGroup、MissionWorkspaceView、workspace 类型/API、Electron bridge：文件树和中央编辑标签。
- Java Observation/Mission Controller 和 Observation 测试、Python agentos_v2 与 API 测试：原任务工作区接口。
- Hands engine/providers/world、Python LocalRuntimeToolExecutor：显式版本化读取与条件保存字段。
- `persistent_runtime.py`：偏移测试实例使用独立 Electron userData，避免与 default 单实例锁冲突。
- 工作区并行出现的 `native_runtime.py` 修改及 `migrate_from_docker.py` 不属于本功能，没有覆盖或清理。

## 使用与范围

在桌面项目页点击右侧“文件”→“打开文件夹”→选择目录→点文件→中央编辑→Ctrl+S。无需编辑 .env、重启 Runtime 或重新创建 Grant。

当前是基础文本编辑器，还没有 VS Code 的语言服务、语法诊断、全局搜索、文件新建/重命名/删除。不同编码和超大文件需要后续扩展。外部进程与保存之间采用乐观版本校验，不宣称跨所有外部程序的事务锁。手动编辑的操作不冒充 ACG 节点证据，canonical final deliverable 仍由 AgentOS 管理。动态切换 Agent 的执行工作区还需要正式的 Grant 绑定流程。

本轮没有开展安装包、系统服务、权限提升，也没有提交或推送 Git。
