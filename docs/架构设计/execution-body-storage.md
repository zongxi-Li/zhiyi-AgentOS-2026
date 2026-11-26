# 执行正文存储：第一批改造

本批处理查询、正文增长与保留边界。`runs.payload` 拆分、长期记忆的召回与合并、远端归档不属于本批。正文不是长期记忆本身：记忆可以引用执行证据，但不能因执行结束而失去来源。

## 数据布局与兼容

- `execution_values` 保留原始 reference、Run、Step、kind、时间与操作身份，每次读取的回执独立保存。
- `execution_value_storage` 按 reference 保存 JSON 编码字节数、类型、SHA-256、显式 base64 编码字节数、content_ref、保留状态与 pin owner。
- 小正文继续内联。默认大于等于 256 KiB 的正文写到数据库旁的 `<数据库名>.bodies/<Run哈希>/<checksum>`，数据库仅留可供现有 SQL 使用的身份投影。
- 外置正文中的大字符串（64 KiB 起）按内容拆分复用。同一 Run 中两次读取即使 requestId 不同，也能共享正文块；回执与完整 JSON 各自可还原。不同 Run 的物理文件不共享，避免跨 Run 的寿命和权限耦合。
- 文件先通过临时文件、fsync、原子替换发布，再提交数据库引用。失败回滚数据库；未提交文件只能由显式的无引用文件回收处理。读取验证 Run 归属、命名空间、完整正文的大小/checksum、块 checksum 和数据库身份投影，损坏时失败。
- 旧行继续可读。启动仅建表和索引，不在启动时扫描全部正文。`migrate` 分批补齐元数据和外置文件，可反复执行；未统计旧行以 `unmeasuredRecords` 明示，不冒充零占用。

备份和迁移必须把 SQLite 数据库及相邻 `.bodies` 目录作为一个整体；仅复制数据库已不足以恢复正文。应用运行时应使用一致性备份或停机备份，不能只复制正在写入的 SQLite 主文件。更旧版本不认识外置正文投影，回退必须恢复升级前的完整备份。

## 索引按实际 SQL 验证

| 查询 | 索引与 EXPLAIN 结果 |
| --- | --- |
| `run_id=? AND created_at<? ORDER BY reference` | `(run_id,created_at)`，范围 SEARCH；最终 reference 排序仍有临时 B-tree |
| `run_id=? AND kind='output' AND reference GLOB 'tool:*' ORDER BY reference` | `(run_id,kind,reference)`，Run/kind/引用范围 SEARCH |
| Run 内工具回执按 `created_at DESC LIMIT 100` | `(run_id,created_at)` 可反向读取，SEARCH，无全表排序 |
| Run/Step 内工具上下文与模型回执 | `(run_id,step_id,reference)`，SEARCH |
| Run 内节点执行/提交列表 | `(run_id,operation_id)`、`(run_id,commit_id)` |

原来的工作区写入 WAL 部分索引保留。元数据另有 Run/状态、Run/checksum、文件引用索引。没有为时间反向查询再重复增加一个相同前缀索引。

## 每个 Run 的统计

`GET /api/agentos/v2/runs/{runId}/storage?since=<带时区时间>` 返回聚合元数据，沿用 Run 所有权校验，不返回正文、私有文件路径或 pin 内容。统计接口不打开外置正文文件。

- `logicalBytes`、`largestBytes`、`largestRecord`：原始 JSON 的字节数与最大记录。
- `growthBytes`：`since` 后新建记录的正文总字节数；不是数据库文件大小差值，也不是状态更新写放大。未指定 since 返回 null。
- `duplicatePayloadBytes`：完整 JSON checksum 重复的字节数。
- `duplicateBodyBytes`：外置大字符串块在不同回执中重复使用所节省的字节数。独立回执可能没有完全相同的 JSON，却共享大量文件内容。
- `encodedBinaryBytes/Ratio`：只统计明确标记为 base64/binary 的编码内容；这是编码字节占 JSON 的比例，不猜测普通文本、不代表磁盘二进制文件数量。
- `externalStoredBytes/Files`：根据文件引用元数据计算的唯一外置文件占用，包含 manifest；不是 SQLite 文件尺寸。

## 保留状态与保护

正文经历 `online → archived → deletable`。本批的 archived 是可继续读取的本地逻辑归档，尚未实现远端冷存储。状态转换不会改变原始 reference。

- `migrate` 可处理活动 Run，保持身份与正文不变。
- `archive/eligible` 必须是 completed、failed、cancelled 或 superseded 的 Run，并显式提供年龄阈值和本次最大变更条数。活动、重试、规划和等待审核的 Run 不允许进入保留维护。
- `eligible` 只接受 archived、未 pin 且未受保护的正文。当前状态、提交、检查点、审核意图、节点 artifact refs、工具 WAL 和现有记忆内容中的来源引用均受保护。工具 WAL 当前采取保守保留，不因取消自动回收。
- pin 的 owner 可使用 `memory:<memoryId>` 等稳定来源标识；增加 pin 会恢复 online，物理删除也会再次检查 pin。后续长期记忆服务应先 pin 来源再发布引用，引用解除后才能 unpin。跨库原子提交和可检索的长期记忆关系表仍是下一批工作。
- 旧的 SQLite orphan 清理入口也检查终态和 deletable 状态，并重查记忆/恢复保护，不能绕过状态流程。底层存储删除方法是受信任的内部原语，不是用户接口。
- 公开维护接口只有 `migrate/archive/eligible`，没有 purge；不在任务结束时自动删除，不自动 VACUUM，不默认设置会丢失证据的保留天数。真正物理清理需由受信任内部维护重新计算保护集合。分批 limit 限制本次变更量，保护关系和候选元数据仍需在 Run 范围内检查。

## 探索默认范围

推断的仓库目录读取默认添加 `.git`、`node_modules`、`dist`、`build`、`.venv`、缓存等目录的字面排除前缀，并在发现与规划提示中要求优先源码/配置文本，二进制内容必须有具体任务理由并定向读取。用户明确指定的读取范围保持原要求。

现有排除合同是字面路径，不是 glob。根目录默认前缀不会自动等同于任意深度的 `**/node_modules`；发现嵌套依赖目录后，规划需把对应字面路径纳入范围，并报告排除项。文本读取本身继续拒绝 NUL/无效 UTF-8；没有将显式二进制读取能力全部关闭。

## 使用

后端使用新代码启动后，通过已有本机网关访问；脚本默认只读：

```powershell
python scripts/execution_storage.py run_4a3ff242d526 --since 2026-11-25T00:00:00Z
python scripts/execution_storage.py run_4a3ff242d526 --action migrate --limit 100
python scripts/execution_storage.py run_4a3ff242d526 --action archive --older-than 2026-11-01T00:00:00Z --limit 100
python scripts/execution_storage.py run_4a3ff242d526 --action eligible --older-than 2026-11-01T00:00:00Z --limit 100
```

migrate 返回 changed=0 后该 Run 当前历史行的回填完成。原数据库删除或外置 JSON 后会留下可复用空页，SQLite 主文件不会自动缩小；本批没有对生产数据库执行 VACUUM。

## 真实副本验证

2026-11-26 对 `run_4a3ff242d526` 的在线数据库做只读 SQLite backup，然后只在独立副本迁移：

| 项目 | 结果 |
| --- | --- |
| 完整校验的独立记录 | 2,526，迁移前后规范 JSON 摘要逐条一致 |
| 数据库中 JSON 字节 | 91,887,487 → 21,617,390 |
| 唯一外置文件 | 94 个，共 6,242,371 字节 |
| 外置块复用节省 | 40,270,176 字节 |
| 明确 base64 编码字节占比 | 82.88% |
| 最大正文 | 1,919,077 字节 |
| 原始生产数据 | 未修改 |

这些数字是该 Run 的逻辑正文和文件引用统计，不是整个数据库的磁盘缩减量。验证报告位于 `.tmp-tests/storage-batch1-real/report.json`。真实副本验证也确认查询计划从全表/主键扫描变成 Run 范围索引 SEARCH。
