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
