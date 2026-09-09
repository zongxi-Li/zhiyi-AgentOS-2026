export type ModelStatus = 'draft' | 'training' | 'ready' | 'online' | 'offline'

export interface ModelCard {
  id: string
  name: string
  scene: string
  version: string
  status: ModelStatus
  federated: boolean
  owner: string
  accuracy: number
  latency: number
  updatedAt: string
  description: string
  modelType: string
  modelSize: string
  loss: number
  params: string
  framework: string
  trainingRounds: number
  participants: number
}

export const makeDefaultModels = (): ModelCard[] => [
  {
    id: 'fed-lawyer-1',
    name: '律师Agent模型',
    scene: '法律咨询',
    version: '3.2',
    status: 'online',
    federated: true,
    owner: '联邦平台',
    accuracy: 87.3,
    latency: 156,
    updatedAt: new Date().toISOString(),
    description: '面向法律领域的联邦模型，支持案例检索、法规查询、证据分析等技能的联邦协同优化。',
    modelType: 'RAG-Enhanced LLM',
    modelSize: '2.4 GB',
    loss: 0.35,
    params: '7B',
    framework: 'FedAvg + DP-SGD',
    trainingRounds: 32,
    participants: 4
  },
  {
    id: 'fed-teacher-1',
    name: '教师Agent模型',
    scene: '教学辅导',
    version: '2.8',
    status: 'online',
    federated: true,
    owner: '联邦平台',
    accuracy: 84.6,
    latency: 142,
    updatedAt: new Date(Date.now() - 35 * 60 * 1000).toISOString(),
    description: '面向教育领域的联邦模型，支持学情诊断、教案生成、错题推送等技能的联邦协同优化。',
    modelType: 'RAG-Enhanced LLM',
    modelSize: '2.1 GB',
    loss: 0.42,
    params: '7B',
    framework: 'FedAvg + SecAgg',
    trainingRounds: 28,
    participants: 4
  },
  {
    id: 'fed-programmer-1',
    name: '程序员Agent模型',
    scene: '代码开发',
    version: '4.1',
    status: 'training',
    federated: true,
    owner: '联邦平台',
    accuracy: 86.1,
    latency: 118,
    updatedAt: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    description: '面向开发领域的联邦模型，支持需求分析、代码检索、代码生成等技能的联邦协同优化。',
    modelType: 'RAG-Enhanced LLM',
    modelSize: '2.8 GB',
    loss: 0.38,
    params: '7B',
    framework: 'FedAvg + HE',
    trainingRounds: 21,
    participants: 4
  },
  {
    id: 'fed-writer-1',
    name: '作家Agent模型',
    scene: '创意写作',
    version: '2.3',
    status: 'ready',
    federated: true,
    owner: '联邦平台',
    accuracy: 83.2,
    latency: 168,
    updatedAt: new Date(Date.now() - 8 * 60 * 60 * 1000).toISOString(),
    description: '面向写作领域的联邦模型，支持灵感拓展、大纲生成、内容撰写等技能的联邦协同优化。',
    modelType: 'RAG-Enhanced LLM',
    modelSize: '1.9 GB',
    loss: 0.48,
    params: '7B',
    framework: 'FedAvg + DP-SGD',
    trainingRounds: 16,
    participants: 3
  },
  {
    id: 'fed-cross-1',
    name: '跨领域融合模型',
    scene: '知识融合',
    version: '1.5',
    status: 'online',
    federated: true,
    owner: '联邦平台',
    accuracy: 81.7,
    latency: 195,
    updatedAt: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
    description: '融合4个Agent领域知识的联邦模型，验证跨领域知识迁移与协同推理能力。',
    modelType: 'Multi-Domain LLM',
    modelSize: '3.2 GB',
    loss: 0.52,
    params: '13B',
    framework: 'FedAvg + HE + DP-SGD',
    trainingRounds: 40,
    participants: 4
  },
  {
    id: 'fed-privacy-1',
    name: '隐私保护基准模型',
    scene: '隐私评估',
    version: '1.2',
    status: 'offline',
    federated: true,
    owner: '安全团队',
    accuracy: 79.4,
    latency: 210,
    updatedAt: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
    description: '用于评估差分隐私与同态加密机制对联邦训练精度影响的基准模型。',
    modelType: 'Privacy-Preserving LLM',
    modelSize: '2.0 GB',
    loss: 0.58,
    params: '7B',
    framework: 'FedAvg + DP-SGD + HE',
    trainingRounds: 20,
    participants: 4
  },
  {
    id: 'fed-comm-1',
    name: '通信效率优化模型',
    scene: '通信优化',
    version: '0.8',
    status: 'draft',
    federated: true,
    owner: '基础设施组',
    accuracy: 74.8,
    latency: 85,
    updatedAt: new Date(Date.now() - 12 * 60 * 60 * 1000).toISOString(),
    description: '测试梯度压缩与稀疏化策略对联邦训练通信效率的提升，当前处于实验阶段。',
    modelType: 'Compressed LLM',
    modelSize: '1.2 GB',
    loss: 0.86,
    params: '3B',
    framework: 'FedAvg + Gradient Sparsification',
    trainingRounds: 3,
    participants: 2
  },
  {
    id: 'local-lawyer-1',
    name: '律师本地基线模型',
    scene: '法律咨询',
    version: '1.0',
    status: 'ready',
    federated: false,
    owner: '律师Agent',
    accuracy: 78.6,
    latency: 98,
    updatedAt: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(),
    description: '律师Agent的本地基线模型，未参与联邦训练，用于对比联邦优化效果。',
    modelType: 'Local LLM',
    modelSize: '1.8 GB',
    loss: 0.72,
    params: '7B',
    framework: 'Local Training',
    trainingRounds: 0,
    participants: 1
  }
]
