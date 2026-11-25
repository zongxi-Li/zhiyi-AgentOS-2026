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


export interface ProviderModelProfile {
  provider: string
  model: string
  usable: boolean
  active: boolean
  key_source: string
}

export interface DiscoveredModels {
  provider: string
  models: string[]
  status?: 'loaded' | 'unavailable'
}

export interface ProviderModel {
  provider: string
  model: string
  discovered: boolean
  profile?: ProviderModelProfile
}

export function providerModelKey(provider: string, model: string): string {
  const name = provider.trim().toLowerCase()
  const id = model.trim()
  // The DeepSeek chat and reasoning aliases resolve to the same Flash model.
  const canonical = name === 'deepseek' && ['deepseek-chat', 'deepseek-reasoner'].includes(id)
    ? 'deepseek-flash' : id
  return JSON.stringify([name, canonical])
}

export function mergeProviderModels(profiles: ProviderModelProfile[], catalogs: DiscoveredModels[]): ProviderModel[] {
  const entries = new Map<string, ProviderModel>()
  for (const profile of profiles) {
    if (!profile.provider || !profile.model) continue
    const key = providerModelKey(profile.provider, profile.model)
    const previous = entries.get(key)?.profile
    if (previous?.active || (previous?.usable && !profile.active && !profile.usable)) continue
    entries.set(key, { provider: profile.provider, model: profile.model, profile, discovered: false })
  }
  for (const catalog of catalogs) {
    if (!catalog.provider) continue
    for (const model of catalog.models) {
      if (!model) continue
      const key = providerModelKey(catalog.provider, model)
      entries.set(key, { ...entries.get(key), provider: catalog.provider, model, discovered: true })
    }
  }
  return [...entries.values()]
}

export function providerModelStatus(item: ProviderModel): string {
  if (item.discovered) return '提供商模型 · 未登记为任务资源'
  if (item.profile?.key_source === 'missing') return '待配置凭据'
  return item.profile?.usable ? '已配置 · 未登记为任务资源' : '连接配置不完整'
}
