import type { ResourceFailoverObservation } from '@/services/api/agentos'

/** 端-边-云部署层级的中文标签。 */
export const tierLabel = (value?: string | null): string => ({
  local: '本地',
  device: '本机设备',
  terminal: '端侧',
  edge: '边缘',
  cloud: '云端'
}[value || ''] || value || '未分层')

/** 资源类型标签，覆盖 skills / mcp / agent 等异构资源。 */
export const resourceTypeLabel = (value?: string | null): string => ({
  agent: 'Agent',
  model: 'Model',
  embedding: 'Embedding',
  tool: 'Tool',
  worker: 'Worker',
  skill: 'Skill',
  mcp: 'MCP',
  execution_backend: '执行后端', model_server: '模型服务', tool_service: '工具服务', model_endpoint: '模型端点'
}[value || ''] || value || '未分类')

/** 资源类型徽章色调，概览/详情/注册表单共用，避免三处硬编码色值。 */
export const RESOURCE_TYPE_TONES: Record<string, string> = {
  agent: '#2563eb',
  skill: '#7c3aed',
  mcp: '#0d9488',
  tool: '#d97706',
  model: '#db2777',
  worker: '#0891b2',
  embedding: '#65a30d'
}

/** 资源类型元数据：标签 + 徽章色调，未知类型回退为中性灰。 */
export const resourceTypeMeta = (value?: string | null): { label: string; tone: string } => ({
  label: resourceTypeLabel(value),
  tone: RESOURCE_TYPE_TONES[value || ''] || '#858585'
})

/** 运行时资源健康状态标签。 */
export const healthLabel = (value: string | null | undefined): string => ({
  unknown: 'Unknown / 未知',
  online: 'Online',
  degraded: 'Degraded',
  offline: 'Offline'
}[value || 'unknown'] || value || 'Unknown / 未知')

/** 数值指标格式化，非有限值返回「未观测」。 */
export const formatMetric = (value: number | null | undefined, unit: string): string => (
  typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)} ${unit}` : '未观测'
)

/** 0-1 小数格式化为百分比，非有限值返回「未观测」。 */
export const formatPercent = (value: number | null | undefined): string => (
  typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : '未观测'
)

/** ISO 时间字符串格式化为中文本地时间。 */
export const formatDate = (value: string | null | undefined): string => {
  if (!value) return '未观测'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

/** 算力画像（CPU 核数 / 内存 / GPU / 带宽）格式化。 */
export const formatCapacity = (capacity?: {
  cpuCores?: number | null
  memoryMb?: number | null
  gpuType?: string | null
  gpuMemoryMb?: number | null
  bandwidthMbps?: number | null
} | null): string => {
  if (!capacity) return '未观测'
  const parts: string[] = []
  if ((capacity.cpuCores ?? 0) > 0) parts.push(`${capacity.cpuCores}核`)
  if ((capacity.memoryMb ?? 0) > 0) parts.push(`${Number(((capacity.memoryMb ?? 0) / 1024).toFixed(1))}G 内存`)
  if (capacity.gpuType) {
    parts.push(`${capacity.gpuType} ${Math.round((capacity.gpuMemoryMb ?? 0) / 1024)}G`)
  } else if (capacity.gpuMemoryMb) {
    parts.push(`GPU ${Math.round(capacity.gpuMemoryMb / 1024)}G`)
  }
  if ((capacity.bandwidthMbps ?? 0) > 0) parts.push(`${capacity.bandwidthMbps}Mbps`)
  return parts.join(' · ') || '未登记'
}

/** New placements and legacy tiers converge without dropping unknown rows. */
export const resourcePlacement = (value?: string | null): string => (
  value === 'local' || value === 'terminal' || !value ? 'device' : value
)

/** 故障转移事件的单行摘要。 */
export const failoverSummary = (event: ResourceFailoverObservation): string => {
  const failed = event.failedResources.map(item => item.resourceId).join('、')
  const retry = event.retryStepIds.join('、') || '原步骤'
  return `${failed} 失效，步骤 ${retry} 重新调度`
}
