> 仓库瘦身（2026-11-21）：保留研究笔记、索引、脚本和可编辑源图；PDF、全文提取、页面快照、导出文件与 `.build` 不再进入 Git。本地原件未删除。退出跟踪的路径、字节数与原 Git blob 见 [ARTIFACTS.csv](ARTIFACTS.csv)，完整原件可从提交 `ba2799ba` 恢复。新克隆中的这些本地资源链接需要先恢复原件，不能当作随仓交付的文件。
>
> 恢复到独立 ZIP（不覆盖当前文档）：`git archive --format=zip --output=../kinlin-research-ba2799ba.zip ba2799ba -- papers`。退出当前版本跟踪不会缩减既有 Git 历史，不做历史改写。

# 论文下载清单：AI Agent「记忆」与「通讯」两部分

检索来源：arXiv（外部学术网站）。检索与下载日期：2026-11-18。
共 15 篇，均为有效 PDF，按方向分两个子目录存放。

---

## 一、记忆方向（memory/，8 篇）

| # | 标题 | arXiv | 年份 | 类型 | 本地文件 |
|---|------|-------|------|------|----------|
| 1 | Memory in the Age of AI Agents: A Survey（Forms, Functions and Dynamics） | 2512.13564 | 2025 | 综述 | `2512.13564_Memory-in-the-Age-of-AI-Agents-Survey.pdf` |
| 2 | A Survey of Agent Memory in the Second Half: Towards Self-Evolving and Long-Horizon Agents | 2602.06052 | 2026 | 综述（TMLR 认证） | `2602.06052_Agent-Memory-Second-Half-Survey.pdf` |
| 3 | Rethinking Memory in AI: Taxonomy, Operations, Topics, and Future Directions | 2505.00675 | 2025 | 综述（六大原子操作） | `2505.00675_Rethinking-Memory-in-AI-Taxonomy-Operations.pdf` |
| 4 | Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory | 2504.19413 | 2025 | 系统/方法 | `2504.19413_Mem0-Scalable-Long-Term-Memory.pdf` |
| 5 | MemoryBank: Enhancing LLMs with Long-Term Memory | 2305.10250 | 2023 | 奠基工作 | `2305.10250_MemoryBank-Long-Term-Memory.pdf` |
| 6 | MemGPT: Towards LLMs as Operating Systems | 2310.08560 | 2023 | 奠基工作 | `2310.08560_MemGPT-LLMs-as-Operating-Systems.pdf` |
| 7 | A-Mem: Agentic Memory for LLM Agents | 2502.12110 | 2025 | 方法（NeurIPS） | `2502.12110_A-Mem-Agentic-Memory.pdf` |
| 8 | Zep: A Temporal Knowledge Graph Architecture for Agent Memory | 2501.13956 | 2025 | 系统/方法 | `2501.13956_Zep-Temporal-Knowledge-Graph-Memory.pdf` |

原始链接：`https://arxiv.org/abs/<arXiv编号>`

## 二、通讯方向（communication/，7 篇）

| # | 标题 | arXiv | 年份 | 类型 | 本地文件 |
|---|------|-------|------|------|----------|
| 1 | A Survey of AI Agent Protocols | 2504.16736 | 2025 | 综述（协议分类） | `2504.16736_Survey-of-AI-Agent-Protocols.pdf` |
| 2 | A Survey of Agent Interoperability Protocols: MCP, ACP, A2A, ANP | 2505.02279 | 2025 | 综述（四大协议对比） | `2505.02279_Survey-of-Agent-Interoperability-Protocols-MCP-ACP-A2A-ANP.pdf` |
| 3 | From LLM Reasoning to Autonomous AI Agents: A Comprehensive Review | 2504.19678 | 2025 | 综述（含 ACP/MCP/A2A） | `2504.19678_From-LLM-Reasoning-to-Autonomous-AI-Agents.pdf` |
| 4 | Beyond Individual Intelligence: Surveying Collaboration, Failure Attribution, and Self-Evolution in LLM-based Multi-Agent Systems | 2605.14892 | 2026 | 综述（多智能体协作） | `2605.14892_Beyond-Individual-Intelligence-Multi-Agent-Systems.pdf` |
| 5 | Large Language Model based Multi-Agents: A Survey of Progress and Challenges | 2402.01680 | 2024 | 综述（多智能体通讯机制） | `2402.01680_LLM-based-Multi-Agents-Survey-Progress-Challenges.pdf` |
| 6 | A Survey on Large Language Model based Autonomous Agents | 2308.11432 | 2023 | 综述（含多智能体通讯） | `2308.11432_Survey-on-LLM-based-Autonomous-Agents.pdf` |
| 7 | The Rise and Potential of Large Language Model Based Agents: A Survey | 2309.07864 | 2023 | 综述（含多智能体场景/智能体社会） | `2309.07864_Rise-and-Potential-of-LLM-Based-Agents-Survey.pdf` |

原始链接：`https://arxiv.org/abs/<arXiv编号>`

---

## 备注
- 若某篇需要最新版，可用 `https://arxiv.org/pdf/<arXiv编号>` 重新下载。
- 记忆方向前两篇（2512.13564、2602.06052）是较新的大综述，适合先看；通讯方向建议先看 2505.02279 和 2504.16736 建立协议框架，再看多智能体协作类。
