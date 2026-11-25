import type { RuntimeDeploymentTier, RuntimeResourceHealth, RuntimeResourceType, RuntimeResourceItem } from '@/services/api/agentos'

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
  execution_backend: '执行服务',
  agent_instance: 'Agent 能力',
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


export const resourceDisplayName = (item: RuntimeResourceItem): string => ({
  native_general_agent: '通用任务助手', workspace_developer: '工作区开发助手',
  'Local Runtime': '本机文件与命令服务', '进程内 Agent 运行时': 'Agent 执行服务'
}[item.profile.displayName || ''] || item.profile.displayName || item.profile.resourceId)

export const confirmedResourceSlots = (item: RuntimeResourceItem): number | null => {
  if (!item.profile.enabled) return 0
  if (item.snapshot.healthStatus !== 'online' || item.health?.healthy === false) return null
  const slots = item.snapshot.availableSlots
  return typeof slots === 'number' && Number.isFinite(slots) && slots >= 0 ? slots : null
}

export const resourceCapacityLabel = (item: RuntimeResourceItem): string => {
  const available = confirmedResourceSlots(item)
  return `登记并发 ${item.profile.capacity} · ${available === null ? '可用容量待确认' : `已确认可用 ${available}`}`
}
