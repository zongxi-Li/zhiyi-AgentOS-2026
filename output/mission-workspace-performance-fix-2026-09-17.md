# Mission Workspace 性能修复

用户反馈：工作区首次加载慢，进入后仍慢；保留艺术字体。

## 实际证据

- 最近打开的 Runtime Run SQLite JSON 记录分别约 16 MB、40 MB。
- 40 MB Run 有 53,960 条 Trace，其中 46,658 条 model.output.delta、7,151 条 model.activity。
- 原工作区观察一次加载完整 Trace，再进行事件、工具、审计、问题、进度文档等投影；活跃 Run 每 2 秒重复观察。
- 工作区导航 Run 列表也读取完整 RuntimeRunRecord，8 秒投影刷新会取消并重启观察。
- 现有拓扑图已支持结构不变时原位更新，因此本轮未重复修改图布局。

## 修复

- Trace 增加可选 `view=workspace`，在序列化前移除模型逐字输出和心跳；保留生命周期、失败、规划和其他 Trace 事实。默认接口仍返回完整审计数据，SQLite 原始数据不修改。
- 仅工作区 RuntimeObservation 使用这个视图。实时文本仍由既有 RuntimeEventStore/SSE 处理，正式输出仍通过原有输出引用读取。
- 工作区 Run 导航使用既有轻量 overview，Identity 已注册 Run 的 lineage 仍由 Identity 投影保留；未注册的延迟规划 Run 从 Runtime 获取 lineage。
- Workspace 状态补充、运行详情、Trace、溯源只读路径复用既有内容寻址水合缓存；执行写入路径继续独立读取记录。
- 同一 Run 的投影刷新更新观察回调/诊断，复用正在进行的观察请求；切换 Run 和销毁视图仍取消旧观察。
- 艺术字体保留。

## 真实持久化数据接口测量

在现有 ai-service 容器内，请求实际 HTTP API，继承本地 internal secret 且按对应 owner 授权；未输出或保存 secret。以下是接口时间，不是端到端桌面页面时间。

40 MB Run `run_8a53fc4c67e5`：

| 请求 | 修复前 | 修复后两次 |
| --- | --- | --- |
| workspace | 2.728 s / 161,346 B | 0.186、0.166 s / 同样大小 |
| run | 0.547 s / 95,995 B | 0.119、0.111 s / 同样大小 |
| 工作区 Trace | 4.966 s / 23,129,449 B | 0.344、0.323 s / 442,942 B |
| provenance | 0.520 s / 16,798 B | 0.119、0.108 s / 同样大小 |

工作区 Trace 返回 151 条，eventCount 仍表示完整审计记录的 53,960 条。

另一个 16 MB Run `run_fdd1aafbcbbb`：首次测量 workspace 0.412 s，工作区 Trace 0.586 s / 530,173 B，返回 205 条，完整记录 21,908 条。

## 验证与限制

- 后台 workspace/API、Trace 和 WorkflowStore 合同测试：65 项通过。
- 前端原有 observation、WorkspaceView、runDocument 测试：44 项通过；新增同 Run 刷新回归后 observation 9 项通过。
- vue-tsc、Web 和 Desktop 生产构建通过；Tauri release 可执行程序已重新生成：`F:\DevTools\CargoTarget\release\kinlin-desktop.exe`。
- 开发 AI 服务启用 --reload，编辑过程触发自动重载；检查时无非终态 Run，服务已恢复 HTTP 200。
- 用户当前打开的是旧 debug 桌面程序，日志仍显示完整 `/trace` 请求。新桌面包需要重新启动才能使用前端修复。
- 尚未测量用户已登录桌面的完整首次进入时间、点击响应和滚动帧率；不能将上述接口耗时表述为整个界面的加载时间。

## 桌面登录网络错误修正

切换 release 后，用户反馈登录 Network Error。现场检查发现 `.env.desktop` 配置为 `http://127.0.0.1:8080`，覆盖了平台代码正确的 9050 默认值，也不匹配桌面 CSP 允许的本地 Gateway。9050 的健康接口和 `http://tauri.localhost` 来源的登录预检均正常（200/204）。

已将桌面构建配置改为 9050；新生成 bundle 不再含 8080 API 地址。此次修正只改变非敏感构建配置，不改账户或认证机制。

重新构建 release 后，在隔离的原生 WebView profile 实测：来源 `http://tauri.localhost`，XHR 健康请求返回 200，使用不存在的测试账户调用登录接口返回正常认证拒绝 401，两者均无 Network Error；页面请求 API origin 为 9050。QA 窗口已关闭，更新后的程序已按用户默认 profile 重新打开。真实账户登录尚未代用户验证。

## final.md 读取链路补修与真实桌面验收

用户继续反馈文件读取慢。排查实际 Java 网关发现 `/trace` 没有接收、转发 `view` 参数，之前 Python 直连的轻量测量没有覆盖这一层；实际桌面仍收到完整 23 MB Trace。这是此前验证范围不足。

- 网关现在显式接收/转发 `view=workspace`，默认完整审计路径不变。
- Artifact 元数据以及 manifest owner 的鉴权改用既有只读水合缓存，避免读取 38 KB 文件时重复解析 40 MB Runtime Run，原鉴权不变。
- ArtifactEditor 的 watch 改为多来源标量监听，相同文件身份的投影对象替换不会重新下载；真正切换 Run/manifest/available 仍重新读取。
- Java Gateway Controller 测试 11 项通过，ArtifactEditor 测试 10 项通过（含新增重复刷新回归），Python Artifact API 测试 1 项通过，Desktop 类型检查、生产构建和 release 构建通过。
- 已重启 Java 网关使改动生效；操作前确认 Runtime 非终态 Run 数量为 0。
- 新 release 在用户默认 WebView profile 内复用已有登录会话进行只读验证，没有输出、保存 token 或登录密码。
- 首轮请求碰到 AI 服务自动重载恢复，曾等待约 10 秒；不以此作为服务稳定后的文件读取时间。

服务稳定后，真实原生 WebView → 9050 Java 网关 → Python API 的并行读取结果：

| 请求 | 毫秒 | 字节 |
| --- | --- | --- |
| Trace workspace | 656 | 442,942，返回 151 条，完整审计计数 53,960 |
| final.md 元数据 | 145 | 1,020 |
| final.md 下载 | 661 | 37,928 |

重新加载整个工作区页面后，最终文档已显示，DOM 正文为 15,882 字符；从页面 navigation start 到确认文档出现约 2,649 毫秒（100 毫秒轮询）。此值包含整个页面初始化、鉴权、工作区加载和渲染，使用当前浏览器缓存，非安装后首次无缓存启动时间。实际页面 Trace 请求已携带 `view=workspace`，后台 access log 也确认参数到达 Python。

验收摘要：`output/playwright/native-artifact-read-2026-09-17.json`。更新后的默认 profile 桌面窗口保持打开，快捷方式目标仍为同一 release 可执行文件。

## 第二轮：正文优先与按需加载

- GraphEditor、RunProgressEditor 改为按需加载，工作区主模块从 199.55 KB 降到 171.05 KB；首次预览 final.md 不加载图编辑器和 vis-network。
- 正文预览只发一次下载请求，从 Blob 获取正文和媒体类型，避免重复请求元数据；原有详情接口和鉴权保留。
- Trace 处理改为 FastAPI 同步处理函数，在线程池中执行，避免大型 Trace 处理阻塞异步事件循环。
- 首次打开文件时优先下载正文，正文读取完成或失败后再启动后台运行观察；切换到其他编辑器也会正常启动观察。
- 前端 API 23 项、ArtifactEditor 10 项、MissionWorkspace 28 项测试通过；Python API 40 项测试通过；桌面类型检查、生产构建和 Tauri release 构建通过。此前 Java 网关 11 项测试通过。

真实登录的原生桌面、同一个 Run、当前浏览器缓存下，两次完整页面重新加载到正文显示分别为 1,462 和 1,363 毫秒，上一轮为 2,649 毫秒。正文有 15,882 字符。这不是首次安装无缓存启动指标。

最终请求时序：工作区投影在 navigation start 后 298 毫秒启动，耗时 836 毫秒；正文下载在 1,150 毫秒启动，耗时 142 毫秒；后台观察在 1,297 毫秒启动，晚于正文下载完成。剩余主要等待仍是工作区投影，不能宣称所有页面都已即时加载。

实际点击 graph.acg 后图画布正常出现，切回 final.md 到正文再次显示为 497 毫秒。最新验收数据保留在 `output/playwright/native-artifact-read-2026-09-17.json`。用户当前窗口和桌面快捷方式使用最新 release 可执行文件，艺术字体保留。

## 临时文件清理

已删除本轮临时原生测试脚本、PID 文件、旧连接测试 JSON 和旧启动测试 JSON。保留本报告、最新实际桌面验收 JSON，以及可回退的原快捷方式备份。

四个临时 WebView 测试目录的递归删除被自动审批拒绝，仅返回 `blocked by policy`，没有具体原因，暂未删除：`native-api-profile-20260917-090310`、`native-startup-profile`、`native-startup-profile-v2`、`native-startup-profile-v3`。用户实际 WebView profile、艺术字体和其他既有资料未清理。
