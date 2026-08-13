# ACG 任务驱动完整流程设计

## 一、整体流程概览（7 个阶段）

```
用户输入 → 意图澄清 → Task 生成 → ACG 规划 → 前端呈现 → 资源分配执行 → 产出交付
```

---

## 二、阶段 1：任务接收（Task Reception）

### 输入
- 用户自然语言描述（自由文本）
- 上传文件列表（PDF、Word、Excel、代码等）
- 选择的角色类型（role_type）和任务类型（task_type）

### 处理
系统接收后，先做基础校验：
- role_type / task_type 是否在预定义枚举范围内
- 文件 ID 列表对应的物理文件是否存在、用户是否有权访问
- 生成一个全局唯一的 task_id，绑定用户身份

### 输出
一个初始 Task 对象，status = CREATED，progress = 0
持久化到数据库，记录 CREATED 事件到事件表
异步触发下一阶段：意图澄清

---

## 三、阶段 2：意图澄清（Intent Clarification）

### 核心思想
**不要让用户一次性把所有需求说清楚。** 系统主动提问，消除歧义和偏差。

### 处理流程
1. 前导模型（Intent Analyzer）接收用户原始输入
2. 语义解析，提取：核心目标、关键实体、显式约束、隐含需求
3. 识别"歧义点"和"缺失信息"——即会影响后续规划的关键不确定项
4. 生成澄清问题（最多 3-5 个，按优先级排序）

### 澄清问题示例
用户说："帮我分析这份合同的风险"

系统识别到的歧义点：
- 风险侧重哪方面？（法律合规 / 商业条款 / 财务责任）
- 输出形式？（摘要报告 / 逐条批注 / 风险评级表）
- 是否需要对比行业标准？
- 目标读者是谁？（法务 / 管理层 / 客户）

### 交互方式
- 前端弹出澄清对话框，逐项提问
- 用户回答后，Intent Analyzer 更新任务语义画像
- 所有澄清结果写入 Task 的 metadata 字段，并生成事件记录

### 输出
一个结构化的 Task 语义画像（TaskProfile），包含：
- primary_goal（精炼后的核心目标）
- key_constraints（约束列表）
- required_capabilities（所需能力向量）
- domain_hint（领域标签）
- implicit_requirements（隐含需求）
- resource_budget（资源预算）
- entropy_budget（通信熵预算）

---

## 四、阶段 3：ACG 规划（Blueprint Generation）

### 输入
TaskProfile（阶段 2 输出）

### 处理流程（8 个子阶段）

#### 3.1 任务分解
将 primary_goal 分解为有序的 Step 列表
每个 Step 包含：step_id、goal、preconditions、expected_output

#### 3.2 通信模式选择
对每个 Step，根据以下规则选择通信模式：

| 条件 | 选择 |
|------|------|
| 主干步骤 + 输出可结构化 + 需审计 | STRICT_CONTRACT |
| 探索性 / 创意生成 | BLACKBOARD |
| 多专家决策 + 高风险 | DEBATE |
| 信号通知 | EVENT |

#### 3.3 Slot 契约生成（仅 STRICT_CONTRACT 步骤）
为每个 Step 生成：
- output_slots：该步骤承诺产出的字段清单
- input_slots：该步骤需要从上游获取的字段清单

#### 3.4 认知路由
- 根据每个 Step 的 required_capabilities
- 在 Agent 注册中心匹配最优 Agent
- 硬性过滤 → 效用评分 → 协作网络构建 → 资源预留

#### 3.5 角色分配
- 将选出的 Agent 绑定到对应 Step
- 若现有 Agent 无法满足，触发动态角色生成
- 生成临时 Agent 描述符，注册到临时区

#### 3.6 记忆策略注入
- 在关键 Step 后插入 Memory Node
- 标记哪些 Step 需要读工作记忆、情节记忆、语义记忆
- 配置信息唤醒算法的权重参数

#### 3.7 控制节点插入
- 条件分支 → IF Control Node
- 并行步骤 → PARALLEL Control Node
- 人工审核点 → REVIEW Control Node
- 循环/重试 → LOOP Control Node

#### 3.8 ACG 验证
- 环检测（确保无循环依赖）
- Slot 完整性检查（每个 input_slot 都有对应 output_slot）
- 资源可行性评估
- 熵预算预估 vs 总额对比

### 输出
ACGBlueprint 对象，包含：
- 所有 Step Node（含 comm_mode、slots、agent 绑定）
- 所有 Dependency Edge
- 所有 Control Node
- Memory Node 和 Evidence Node
- 全局 metadata（复杂度、风险等级、预算）

---

## 五、阶段 4：前端呈现（ACG Visualization）

### 设计原则
1. **以 Step 为主导**：每个 Step 是一个可视化节点，Agent 信息折叠在节点详情中
2. **线不重叠**：使用分层布局算法（如 Dagre 的 rank + order 优化）
3. **分层清晰**：从上到下 = 执行顺序；从左到右 = 并行分支
4. **详情可展开**：点击节点弹出抽屉，展示完整信息

### 节点视觉设计
| 元素 | 说明 |
|------|------|
| 节点形状 | 圆角矩形（Step） |
| 颜色编码 | 绿色=已完成，蓝色=待执行，黄色=执行中，红色=失败，灰色=未激活 |
| 节点标题 | Step 的 goal（一句话） |
| 节点副标题 | 绑定的 Agent 名称 + 角色 |
| 节点图标 | 通信模式图标（契约=锁，黑板=板，辩论=对话气泡，事件=闪电） |

### 节点详情抽屉（点击展开）
```
┌─────────────────────────────────────────┐
│  Step: risk_analysis                   │
│  Goal: 分析合同条款中的风险点          │
│  Status: PENDING                      │
│  ───────────────────────────────────── │
│  Agent: agent_legal_001               │
│  Role: 法律分析师                    │
│  Model: deepseek-r1                   │
│  ───────────────────────────────────── │
│  Input Slots:                         │
│    • contract_text ← step_parse       │
│    • parties ← step_parse             │
│  Output Slots:                        │
│    • risk_items (list)                │
│    • risk_level (enum)                │
│  ───────────────────────────────────── │
│  Comm Mode: STRICT_CONTRACT           │
│  Memory: 读-情节记忆(step_parse)     │
│           写-情节记忆(risk_conclusion)│
│  ───────────────────────────────────── │
│  Est. Tokens: 2,500                  │
│  Est. Duration: 12s                  │
│  Entropy Cost: 0.8 / 5.0            │
└─────────────────────────────────────────┘
```

### 边视觉设计
| 边类型 | 样式 |
|--------|------|
| Dependency Edge | 实线箭头（灰色） |
| Control Edge | 虚线箭头（橙色） |
| Communication Edge | 实线 + 标注传输字段名（蓝色小字） |

### 前端交互
- ** hover 节点**：显示预估耗时、Token 消耗、风险等级
- **点击节点**：右侧弹出详情抽屉
- **点击边**：显示传输的字段名和数据类型
- **缩放/拖拽**：支持画布缩放和平移
- **进度实时更新**：执行中节点颜色动态变化

### 技术选型建议
- 图渲染：React + ReactFlow 或 D3.js
- 布局算法：Dagre（分层有向图布局，保证线不重叠）
- 状态同步：WebSocket 推送执行进度

---

## 六、阶段 5：资源分配与执行（Resource Allocation & Execution）

### 输入
ACGBlueprint + TaskProfile

### 处理流程

#### 5.1 资源画像查询
调度器向 Resource Profiler 查询：
- 当前所有可用节点的健康状态
- 各节点的算力、内存、GPU、带宽
- 各节点已部署的 Agent 和模型
- 隐私等级与位置映射

#### 5.2 多目标决策
对每个 Step，调度器综合：
- 性能（模型推理速度）
- 成本（Token 单价 × 预估消耗）
- 延迟（节点到数据的网络距离）
- 隐私（数据敏感度 → 部署位置约束）

输出：每个 Step 的 target_endpoint（执行位置）

#### 5.3 Agent 实例化
- 在目标节点上启动 Agent 实例
- 注入该 Step 的 input_slots 定义
- 注入记忆系统连接（工作记忆 + 情节记忆读取）
- 返回 agent_instance_id

#### 5.4 按序执行
LangGraph 引擎按 ACG 拓扑驱动执行：

```
for each Step in topological_order:
    # 1. 从 State 中按 input_slots 精确提取
    inputs = extract_by_input_slots(state, step.input_slots)
    
    # 2. 记忆唤醒：获取相关历史上下文
    context = memory.recall(step, inputs)
    
    # 3. 低熵通信校验
    entropy_cost = estimate_entropy(inputs, step.output_slots)
    if not check_budget(entropy_cost):
        trigger_compress_or_replan()
    
    # 4. 执行 Agent
    result = agent_registry.execute(
        agent_instance_id=step.agent_instance_id,
        inputs=inputs,
        context=context
    )
    
    # 5. 按 output_slots 校验
    validated = validate_output(result, step.output_slots)
    
    # 6. 写入 State（只写 slots 声明的字段）
    state.steps_output[step.step_id] = validated
    
    # 7. 审计记录
    audit.record_production(step, validated, entropy_cost)
    
    # 8. 检查点保存
    if step.is_checkpoint_trigger:
        checkpoint.save(state, step.step_id)
    
    # 9. 进度更新
    progress = compute_progress(completed_steps, total_steps)
    notify_frontend(task_id, progress)
```

#### 5.5 通信模式差异化执行

| 模式 | 执行差异 |
|------|----------|
| STRICT_CONTRACT | 按 slots 精确提取/写入，强制 schema 校验 |
| BLACKBOARD | 写入共享消息池的指定 topic，下游按订阅拉取 |
| DEBATE | 多 Agent 多轮辩论，投票/共识后输出 |
| EVENT | 只发事件信号，不传数据体 |

---

## 七、阶段 6：进度检测与治理（Progress Monitoring & Governance）

### 实时进度计算
```
progress = (已完成步骤权重之和 / 总步骤权重之和) × 100%
```

### 进度推送
- WebSocket 实时推送到前端
- 前端进度条 + 节点颜色动态更新

### 治理检查点（每个 Step 执行后）
1. **策略引擎检查**：输出是否触发风险规则？
2. **证据链校验**：关键结论是否绑定了 evidence_refs？
3. **置信度检查**：输出置信度是否低于阈值？
4. **人工审核触发**：高风险 Step 完成后，自动暂停 → WAITING_REVIEW

### 异常处理
| 异常类型 | 处理方式 |
|----------|----------|
| Slot 缺失 | 尝试默认值修复 → 触发上游重试 → 标记降级 |
| Agent 超时 | 重试（指数退避）→ 切换备选 Agent → 标记失败 |
| 熵预算超限 | 触发压缩 → 合并通信边 → 重规划 |
| 节点失联 | 切换等价资源 → 从检查点续跑 |

---

## 八、阶段 7：最终产出（Delivery）

### 产出物
1. **最终交付物**：报告、代码、分析结果等（按用户要求的格式）
2. **执行轨迹**：完整的 ACG 执行图（带颜色标注每个节点的状态）
3. **审计日志**：所有 Data Production/Consumption Event
4. **证据链**：每个关键结论的来源引用
5. **资源报告**：Token 消耗、成本、耗时统计

### 交付流程
1. 最终 Step 输出 → 格式化为用户要求的产出形式
2. 审计器做最终质量校验（规则 + 一致性 + 证据完整性）
3. 通过后，status → COMPLETED
4. 前端展示最终结果 + 可下载的审计包

---

## 九、完整时序图（一张图看懂全流程）

```
用户          前端           Task Manager    规划器       调度器      执行引擎      记忆系统    审计系统
 │             │                │            │            │           │            │          │
 │ 输入需求+文件│                │            │            │           │            │          │
 │───────────→│                │            │            │           │            │          │
 │             │ 创建 Task     │            │            │           │            │          │
 │             │──────────────→│            │            │           │            │          │
 │             │                │ 意图澄清   │            │           │            │          │
 │←────────────│(如需澄清)     │──────────→│            │           │            │          │
 │ 回答澄清    │                │            │            │           │            │          │
 │───────────→│                │            │            │           │            │          │
 │             │                │ 生成 ACG  │            │           │            │          │
 │             │                │──────────→│            │           │            │          │
 │             │                │            │ 返回蓝图    │           │            │          │
 │             │                │←──────────│            │           │            │          │
 │             │ 展示 ACG 图   │            │            │           │            │          │
 │             │←──────────────│            │            │           │            │          │
 │ 确认执行    │                │            │            │           │            │          │
 │───────────→│                │            │            │           │            │          │
 │             │                │ 请求资源   │            │           │            │          │
 │             │                │──────────────────────→│           │            │          │
 │             │                │            │            │ 分配Agent │            │          │
 │             │                │            │            │─────────→│            │          │
 │             │                │            │            │           │ 读取记忆   │          │
 │             │                │            │            │           │──────────→│          │
 │             │                │            │            │           │ 写入审计   │          │          │
 │             │                │            │            │           │──────────────────→│
 │             │ 推送进度       │            │            │           │            │          │
 │             │←──────────────│            │            │           │            │          │
 │ 查看进度    │                │            │            │           │            │          │
 │←────────────│                │            │            │           │            │          │
 │             │                │            │            │           │ 逐步执行... │          │
 │             │                │            │            │           │            │          │
 │             │                │            │            │           │ 最终产出   │          │
 │             │                │            │            │           │──────────→│          │
 │             │                │ 返回结果   │            │           │            │          │
 │             │←──────────────│            │            │           │            │          │
 │ 查看结果    │                │            │            │           │            │          │
 │←────────────│                │            │            │           │            │          │
 │ 下载审计包  │                │            │            │           │            │          │
 │───────────→│                │            │            │           │            │          │
```

---

## 十、关键设计决策总结

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 图执行引擎 | LangGraph | 成熟、有 checkpoint、支持 interrupt |
| 通信模式 | 混合（4 种） | 不同步骤特性不同，一刀切不现实 |
| 主干通信 | STRICT_CONTRACT | 低熵、可审计、可恢复 |
| 前端布局 | 分层有向图（Dagre） | 保证线不重叠，Step 主导 |
| 进度计算 | 权重加权 | 简单步骤和复杂步骤权重不同 |
| 资源调度 | 多目标决策（UCB） | 性能/成本/隐私综合优化 |
| 恢复机制 | LG Checkpointer + 自定义检查点 | 底层复用，上层增强 |
| 审计粒度 | 字段级 Data Event | 精确追溯每个数据的来源和去向 |
