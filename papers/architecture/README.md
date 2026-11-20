# 三大模块架构设计

2026-11-18。根据用户确认，三个方向为差分隐私、前导模型、自进化。交付为架构方案与三页演示，不包含业务功能实施。

- [架构与实施设计](ARCHITECTURE_DESIGN.md)：总体分工、模块接口、事务状态、故障语义、代码映射和验收顺序。
- [差分隐私论文图组](dp_figures/README.md)：六张专业架构/数据流/状态/会计/恢复时序/协议边界图，中英文原生 draw.io，并附矢量 PDF、SVG、高清 PNG、图注与逻辑审查。
- [图与 Skills 自进化论文图组](evolution_figures/README.md)：九张图覆盖图补丁、技能抽象与检索、受控贡献评测、生命周期及联合版本清单发布；中英文原生 draw.io、矢量图、高清预览、图注与逻辑审查。
- [三页可编辑 PowerPoint](output/Kinlin_Architecture_Three_Modules.pptx)：每个方向一页，无额外封面，架构节点、文字和连接线可编辑，备注附来源及解释。
- [第 1 页：差分隐私](output/01_差分隐私.png)：可信本地发布、组合会计、预算预留和持久载荷。
- [第 2 页：前导模型](output/02_前导模型.png)：意图入口与本地前 K 层拆分，含逐 token 循环。
- [第 3 页：自进化](output/03_自进化.png)：图与 Skills 双候选、共用评测、正式版本发布与证据回流。

PPT 用原生可编辑对象制作，并逐页渲染检查。字体为 Microsoft YaHei，画布为 16:9。现有能力与待实现模块在每页底部区分，外部论文和项目状态依据见备注及设计文档。

deck_source.js 是本次 Artifact Session 的编排源，绑定当前 artifactRef，适合后续在该演示中修订；不是生产模块实现或独立启动脚本。validation.json 记录包结构、页数、资源哈希、本地链接和画布边界检查。

[返回研究总览](../RESEARCH_OVERVIEW.md)
