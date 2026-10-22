import type { RuntimeDeploymentTier, RuntimeResourceHealth, RuntimeResourceType } from '@/services/api/agentos'

export type CustomerDeploymentGroup = {
  id: 'device' | 'edge' | 'cloud' | 'other'
  label: string
}

export const deploymentGroup = (tier: RuntimeDeploymentTier | null | undefined): CustomerDeploymentGroup => {
  if (tier === 'edge') return { id: 'edge', label: '边缘节点' }
  if (tier === 'cloud') return { id: 'cloud', label: '云端服务' }
  if (tier === 'local' || tier === 'device' || tier === 'terminal' || !tier) return { id: 'device', label: '我的设备' }
  return { id: 'other', label: '其他位置' }
}

export const customerResourceType = (kind: RuntimeResourceType | string | null | undefined): string => ({
  model_server: '模型',
  model_endpoint: '模型',
  tool_service: '工具',
  execution_backend: '设备服务',
  agent: '智能体',
  worker: '执行服务',
  embedding: '向量模型',
  mcp: 'MCP 工具',
  skill: '技能'
}[kind || ''] || '资源')

export const connectionGuidance = (health: RuntimeResourceHealth | string | null | undefined) => {
  if (health === 'offline') return { tone: 'danger', action: '检测连接' }
  if (health === 'degraded') return { tone: 'warning', action: '查看状态' }
  if (health === 'unknown') return { tone: 'neutral', action: '检测连接' }
  return { tone: 'success', action: '查看详情' }
}

export const customerHealthLabel = (health: RuntimeResourceHealth | string | null | undefined): string => ({
  online: '可用', degraded: '需关注', offline: '离线', unknown: '待检测'
}[health || ''] || '状态未知')

export const customerPrivacyLabel = (privacy: string | null | undefined): string => ({
  public: '公开数据', internal: '内部数据', confidential: '敏感数据', restricted: '受限数据'
}[privacy || ''] || privacy || '隐私未标注')
