# V1 发布候选清单（INT-2E）

2026-10-26 CLOSEOUT 后，**BLOCKED，尚非可发布候选版本**（三項原始阻断已关闭，唯一剩余阻断为正式冻结门禁结构性预算冲突）。详细证据见 [收束报告](PR-C2B-INT-2E-CLOSEOUT.md) 与 [最终报告](PR-C2B-INT-2E-V1-FINAL.md)。

| 项目 | 当前结论 |
| --- | --- |
| 实际可用功能 | 正常 IAM 登录；Workbench 创建 Mission（含人工审核模式）；正式规划接受、物化、暂停激活、Handoff、Permit；用户显式 Dispatch；Native 节点执行；human_in_loop 每步暂停正式人工审核（通过/驳回/审核说明，可信主体与写权限复核）；批准前 canonical final 不公开；批准后 sealed final 阅读/下载；真实 SSE 观察；重登录/重启后读取 |
| 已验证环境 | Windows Docker Desktop、单实例 Linux 容器 Java/Python/Vue、隔离 PostgreSQL/Redis/SQLite、真实 DeepSeek（deepseek-v4-flash，浏览器 E2E 即真实 Provider）；宿主 Python / Java / Vue 定向回归（HTTP 66、Runtime 303、Java 53、前端 155）；Web/Desktop 类型检查及构建 |
| 首次启动依赖 | 先离线备份并检查各库；显式安装 C2 Schema，再安装 Dispatch version 1；内部服务身份与资源加密密钥；正常 IAM 与授权 Provider。未升级时启动应拒绝。不要自动升级真实数据库 |
| 功能阻断 P1 | 无。human_in_loop 已形成正式审核屏障（策略 `human-review-all-steps-v1` 冻结于规划/编译输入，恢复期修订 fail-closed，交付公开边界按 Run 终态收口） |
| 已关闭的历史阻断 | P1 下载损坏内容提前暴露；P2 Coordinator 取消句柄、SSE EOF/零序号/新连接游标；P1 人工审核策略缺失；P2 Java 组合计时失败（虚拟时钟 53/0/0/0）；P2 门禁 max-only 预检假阻断（last/max 双记录修复） |
| 当前唯一冻结阻断 | 正式冻结门禁 INCOMPLETE_TIMEOUT：选择集 498 节点（本轮核心源码变更按既有映射合法拉入完整契约测试）vs 300s 冻结预算，结构性冲突；需用户裁决预算再基线/选择策略/分层门禁 |
| 验证缺口 | 真实多租户、服务端会话撤销、Provider 线上故障、审核/取消/失败 SSE、完整灾备、原生 Windows 服务/容量、大 Artifact 磁盘路径未验收 |
| 固有限制 | 单实例锁；跨库非原子；SSE 瞬态无持久游标回放；未知远端副作用阻断；无任意外部副作用 exactly-once 或分布式证明；大 Artifact 预校验增加磁盘/I/O/首字节延迟 |
| 允许 V1 最终冻结 | 否（门禁未完整通过）；V1 内核功能基线可作候选记录，INT-2C / INT-2D 仍按 ACCEPT WITH LIMITATIONS 保留阶段冻结 |
| 允许独立部署验收 | 暂不允许完整入场；功能面可先做只读预演，完整验收以门禁通过为前提 |
| Git / 部署 | 仅本地固化（本轮四笔职责提交在 6192be1a 之上），最终正式门禁未通过故不推送候选版本；未部署、未改生产配置或开关、未操作 Gitee |

隔离测试栈本轮验收后保持运行供复核（codex-int2e-closeout-20261026，入口 127.0.0.1:19089，验收账号 closeout_e2e）；一次性凭据文件保留在 .tmp-tests/int2e-closeout/secrets（不入库）；历史门禁耗时缓存未清空（legacy max 全保留，新增 last 观测）。
