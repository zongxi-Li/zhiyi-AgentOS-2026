# V1 发布候选清单（INT-2E）

2026-10-26，**BLOCKED，尚非可发布候选版本**。详细证据见 [最终报告](PR-C2B-INT-2E-V1-FINAL.md)。

| 项目 | 当前结论 |
| --- | --- |
| 实际可用功能 | 正常 IAM 登录；Workbench 创建 Mission；正式规划接受、物化、暂停激活、Handoff、Permit；用户显式 Dispatch；Native 节点执行；真实 SSE 观察；sealed canonical final 阅读/下载及重登录/重启后读取 |
| 已验证环境 | Windows Docker Desktop、单实例 Linux 容器 Java/Python/Vue、隔离 PostgreSQL/Redis/SQLite、真实 DeepSeek；宿主 Python / Java / Vue 定向回归；Web/Desktop 类型检查及构建 |
| 首次启动依赖 | 先离线备份并检查各库；显式安装 C2 Schema，再安装 Dispatch version 1；内部服务身份与资源加密密钥；正常 IAM 与授权 Provider。未升级时启动应拒绝。不要自动升级真实数据库 |
| 功能阻断 P1 | 创建页 human_in_loop 未绑定正式审核策略，真实 Run 没有审核暂停；尚不能承诺完整“执行→人工审核→交付” |
| 已修复待独立验收 | P1 下载损坏内容提前暴露；P2 Coordinator 取消句柄、SSE EOF/零序号/新连接游标问题 |
| 验证缺口 | 最终正式冻结门禁因原预算阻断；Java 组合计时测试失败；真实多租户、服务端会话撤销、Provider 线上故障、审核/取消/失败 SSE、完整灾备、原生 Windows 服务/容量未验收 |
| 固有限制 | 单实例锁；跨库非原子；SSE 瞬态无持久游标回放；未知远端副作用阻断；无任意外部副作用 exactly-once 或分布式证明；大 Artifact 预校验增加磁盘/I/O/首字节延迟 |
| 允许 V1 最终冻结 | 否。INT-2C / INT-2D 仅按 ACCEPT WITH LIMITATIONS 保留阶段冻结 |
| 允许独立部署验收 | 尚不允许完整入场；先独立复验安全修复及阻断，再补齐必需门禁和全流程 |
| Git / 部署 | 仅本地固化，最终正式门禁未通过故不推送候选版本；未部署、未改生产配置或开关、未操作 Gitee |

隔离测试栈已关闭，复制/生成的凭据文件已删除，专用测试数据卷保留；真实业务数据和历史门禁耗时缓存未清理。
