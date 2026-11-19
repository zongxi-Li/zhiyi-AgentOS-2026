# 差分隐私架构图组

2026-11-19。承接差分隐私文字方案，共 **6 张图，中英文各一套**。原生 draw.io 节点、文字、连线均可编辑；SVG/PDF 保留矢量和文本，PNG 用于预览。

## 使用入口

- [中文六页 draw.io](drawio/DP_Paper_Figures_zh.drawio)
- [英文六页 draw.io](drawio/DP_Paper_Figures_en.drawio)
- [中文 PDF 合集](pdf/DP_Paper_Figures_zh.pdf)
- [英文 PDF 合集](pdf/DP_Paper_Figures_en.pdf)
- [全部交付文件 ZIP](DP_Paper_Figures_Package.zip)
- [中英文图注、符号与来源](CAPTIONS.md)
- [逻辑审查与实现前提](LOGIC_REVIEW.md)
- [导出检查记录](validation.json)

在 draw.io / diagrams.net 中选择“文件 → 从设备打开”，打开任一 `.drawio`。多页文件通过底部标签切换，单图文件用于独立修改。不要把 PNG 作为编辑源。

## 图清单

| 图 | 内容 | 中文源文件 | 英文矢量 PDF | 建议位置 |
|---|---|---|---|---|
| 1 | 系统架构、可信本机与云端边界 | [draw.io](drawio/fig01_zh.drawio) | [PDF](pdf/fig01_en.pdf) | 主文 |
| 2 | 发布数据流与持久化顺序 | [draw.io](drawio/fig02_zh.drawio) | [PDF](pdf/fig02_en.pdf) | 主文或方法附录 |
| 3 | 持久发布状态机与故障终止 | [draw.io](drawio/fig03_zh.drawio) | [PDF](pdf/fig03_en.pdf) | 补充材料 |
| 4 | Gaussian 发布与 RDP 前瞻会计 | [draw.io](drawio/fig04_zh.drawio) | [PDF](pdf/fig04_en.pdf) | 主文 |
| 5 | 丢失回执后的恢复时序 | [draw.io](drawio/fig05_zh.drawio) | [PDF](pdf/fig05_en.pdf) | 补充材料 |
| 6 | 数值、元数据、交互行为的可观测范围 | [draw.io](drawio/fig06_zh.drawio) | [PDF](pdf/fig06_en.pdf) | 威胁模型或附录 |

逐图文件在 `drawio/`、`svg/`、`pdf/`、`png/` 中采用相同编号；`_en` 为英文，`_zh` 为中文。

## 论文排版

白底、无阴影，五类有限配色；同时用文字、线型和容器表达含义，颜色不是唯一编码。蓝色为本地/私有计算，青色为隐私机制，紫色为持久状态，灰色为公开配置或云端，橙色为拒绝与故障。连线采用正交布局，图 5 按时序图规则保留垂直生命线。

英文主字体 Arial，中文为 Microsoft YaHei；数学字符使用系统字体回退，PDF 嵌入实际使用的字体。PDF 按约 180 mm 双栏宽度导出，最小标签约 8.1 pt；PNG 宽 2880 px，在 180 mm 宽度下约 406 dpi。请优先使用英文矢量 PDF 嵌入 LaTeX，SVG 用于支持该格式的排版工具。

这些图按双栏通栏尺寸设计。直接缩到约 85–90 mm 单栏会使文字过小，应拆分子图或重新排版。图内标题为独立可编辑对象，若正文图注已经包含标题，可删除对应标题对象后重新导出。最终宽度、字体和图注仍须按具体会议模板核对。

## 设计边界

这是固定公开协议下、针对推理输入的 Gaussian 基线**目标设计**。图中流程、RDP 费用和恢复规则不表示项目已经实现或获得形式化隐私保证。机制参数、最大发布次数、公开信息和保护域必须在实现前冻结；有限精度噪声、完整 transcript 及故障恢复还需独立验证。详细条件见 `CAPTIONS.md` 与 `LOGIC_REVIEW.md`。

## 可复现来源

`tools/build_drawio.py` 生成原生 XML；`tools/render_drawio.cjs` 和 `tools/renderer.html` 调用官方 draw.io viewer 的 Graph/mxCodec/getSvg 引擎渲染，再使用本地 Edge 导出 PNG/PDF。图形内容只经本机临时 HTTP 服务传递，渲染期间禁止外部请求。

生成器依赖 Python 3；渲染器依赖 Node.js、Playwright 与本机 Edge，并通过 `KINLIN_NODE_MODULES` 指定包含 Playwright 的模块目录。官方 viewer 脚本缓存于 `.build/viewer.min.js`，来源为 <https://www.draw.io/js/viewer.min.js>，本次版本哈希见 `validation.json`。ZIP 不包含该第三方缓存。重新构建前应下载或提供与记录哈希相符的脚本；更新 viewer 后须重新检查导出。

运行顺序：`python tools/build_drawio.py` → `node tools/render_drawio.cjs` → `python tools/finalize_figures.py`。最后一步依赖 PyMuPDF 与 Pillow，执行结构/几何/导出检查、合并 PDF 并打包。人工视觉复核单独记录，不由脚本替代。
