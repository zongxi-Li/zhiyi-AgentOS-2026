# OScode 命令执行期限与终止归因

命令时长由请求决定：`timeout` 缺省或为 null 时没有执行截止时间；显式填写正数时按秒执行，不再裁剪到工具默认值或 Hands 的 600 秒上限。

## 根因与修改

- `run_command` 原来把 timeout 留在命令 input，而 Hands 读取的是 envelope.limits，导致模型申请的预算没有成为实际预算。现在仅通过 limits.timeoutSeconds 传递。
- 移除命令的 SDK 和 invoke 外层计时器，避免它们先于命令申请值触发取消。旧 terminal 路径也不再使用默认 30 秒和最大 120 秒裁剪。
- Hands 缺省不设 deadline；统一通过后台进程句柄执行，由引擎管理唯一的显式期限，阻止 DSH 自动补入默认 120 秒期限。原生备用 provider 同样移除默认期限。
- 显式期限使用可取消的分段计时器，避免 Node 超长 setTimeout 溢出后立即触发。
- 收据及上层 terminal 传递 timedOut、terminationReason、terminationMessage、effectiveTimeoutSeconds、timeoutSource。超时明确返回 COMMAND_TIMEOUT；取消与进程非零退出保持独立归因。
- 命令工具说明写明缺省无限期、显式正数按秒执行，防止模型继续按旧的隐藏上限推断。

## 边界

本修改移除命令执行的隐式时间限制。权限校验、用户取消、输出保留容量、网络单次请求超时、模型连接与流式等待策略保持各自职责。后台输出轮询等待到期只是返回当前进度，不终止命令。显式调用方填写的期限仍然有效。

不重启现有服务，不中断并行任务。源码和隔离测试通过后，既有服务仍需在任务空闲时按正常发布流程加载新代码。

## timeout 参数兑现复查

补齐首次执行请求直接返回失败收据的分支：保留收据的超时详情、有效预算与部分输出，并将 EXECUTION_TIMEOUT 统一为 COMMAND_TIMEOUT。此前只有事件流终态分支完整处理这些信息。非数字、布尔值、非正数及非有限数的 timeout 明确返回 COMMAND_TIMEOUT_INVALID，禁止执行。

增加真实隔离 HTTP 回归：通过 Chat 工具调用、后台句柄、LocalRuntimeClient、HMAC HTTP 和 Hands 服务启动 PowerShell 的 8 秒睡眠命令，申请 timeout=0.5 秒。轮询验证返回 failed / COMMAND_TIMEOUT，模型可见 terminal 与 Hands 签名收据均报告 timedOut=true、effectiveTimeoutSeconds=0.5，后续文件写入未执行。该测试使用临时工作区、临时凭据、动态端口，不接触现有服务与任务。

## 请求 1800 秒却在 600 秒结束的修复

只读核对原始账本，旧常驻 Hands 的一条超时收据 durationMs=600105，未报告 effectiveTimeoutSeconds、timeoutSource 或 terminationMessage。常驻进程仍是 14:06 启动的旧实现，存在旧资源策略与 DSH 的 600 秒裁剪。上层错误地将请求值直接填入 effectiveTimeoutSeconds，并用该请求值生成终止说明，导致错误的“1800 秒已生效”表述。

- 请求值与执行事实分离：requestedTimeoutSeconds 保留申请值；有效值只取执行层收据，timeoutConfirmed 表示是否已确认。旧收据缺少有效值时显示 null / unconfirmed，不根据申请值或耗时猜测。
- 即时失败收据和事件终态使用相同规则；超时消息根据收据中的有效值生成。申请 1800、实际报告 600 时，消息分别说明 backend deadline (600s) 与 requested 1800s。
- 经过 checksum 验证的收据覆盖事件提示中的有效期限、超时标志与退出码。Hands 原始收据同时保留 requestedTimeoutSeconds 与经资源解析的 effectiveTimeoutSeconds。
- 保持引擎唯一计时器和底层 onExpiry=none；增加虚拟时钟回归，确认 1800 秒期限在 600 秒不触发、到 1800 秒才触发，并确认资源解析保留 1800000ms。

验证：Python 相关 62 项通过；Hands 类型检查通过，期限相关 10 项通过（另 12 项因筛选未执行）。真实隔离 HTTP 链路同时验证短超时及 1800 秒预算的完整传递。

本次确认活动 Chat、正式 Run、未结算 Hands 执行均为零后，在运行时控制锁内平滑重载 Hands 和 AI，就绪检查通过。未重载桌面页面或修改历史对话。常驻 Hands 实测回执：请求 1800 秒、有效 1800 秒、短命令正常结束；请求 0.2 秒、有效 0.2 秒、超时明确为 timeout。没有实际等待 30 分钟，1800 秒触发时刻由虚拟时钟覆盖。
