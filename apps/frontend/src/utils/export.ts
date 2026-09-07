/**
 * 导出工具
 */
export interface ConversationExport {
  messages: Array<{
    role: string
    content: string
    time: string
  }>
  role?: string
  createdAt: string
}

/**
 * 导出对话为JSON
 */
export function exportConversationToJson(data: ConversationExport): string {
  return JSON.stringify(data, null, 2)
}

/**
 * 导出对话为TXT
 */
export function exportConversationToTxt(data: ConversationExport): string {
  let content = `对话导出\n`
  content += `角色: ${data.role || '默认'}\n`
  content += `创建时间: ${data.createdAt}\n`
  content += `\n${'='.repeat(50)}\n\n`

  data.messages.forEach((msg, index) => {
    content += `[${msg.role.toUpperCase()}] ${msg.time}\n`
    content += `${msg.content}\n\n`
  })

  return content
}

/**
 * 导出对话为CSV
 */
export function exportConversationToCsv(data: ConversationExport): string {
  // CSV头部（使用BOM支持中文）
  let content = '\uFEFF时间,角色,内容\n'
  
  data.messages.forEach((msg) => {
    // 转义CSV特殊字符
    const time = `"${msg.time.replace(/"/g, '""')}"`
    const role = `"${msg.role.replace(/"/g, '""')}"`
    const msgContent = `"${msg.content.replace(/"/g, '""').replace(/\n/g, ' ')}"`
    content += `${time},${role},${msgContent}\n`
  })

  return content
}

/**
 * 导出对话为Markdown
 */
export function exportConversationToMarkdown(data: ConversationExport): string {
  let content = `# 对话导出\n\n`
  content += `**角色**: ${data.role || '默认'}\n\n`
  content += `**创建时间**: ${data.createdAt}\n\n`
  content += `---\n\n`

  data.messages.forEach((msg) => {
    const roleLabel = msg.role === 'user' ? '用户' : 'AI助手'
    content += `## ${roleLabel} - ${msg.time}\n\n`
    // 转义Markdown特殊字符，但保留换行
    const escapedContent = msg.content
      .replace(/\n/g, '\n\n')
      .replace(/\*\*/g, '\\*\\*')
      .replace(/#/g, '\\#')
    content += `${escapedContent}\n\n`
    content += `---\n\n`
  })

  return content
}

export interface MissionJsonExport {
  exportedAt: string
  total: number
  missions: unknown[]
}

export interface MissionExportRecord {
  name: string
  missionId: string
  status: string
  latestRunStatus: string
  runCount: number
  latestRunId: string
  description: string
  createdAt: string
  updatedAt: string
}

export interface MissionTableExport {
  exportedAt: string
  total: number
  missions: MissionExportRecord[]
}

/**
 * 导出项目列表为JSON（保留原始字段）
 */
export function exportMissionsToJson(data: MissionJsonExport): string {
  return JSON.stringify(data, null, 2)
}

/**
 * 导出项目列表为TXT
 */
export function exportMissionsToTxt(data: MissionTableExport): string {
  let content = `工程项目导出\n`
  content += `导出时间: ${data.exportedAt}\n`
  content += `项目数量: ${data.total}\n`
  content += `\n${'='.repeat(50)}\n\n`

  data.missions.forEach((mission, index) => {
    content += `[${index + 1}] ${mission.name}\n`
    content += `Mission ID: ${mission.missionId}\n`
    content += `状态: ${mission.status}（最近运行：${mission.latestRunStatus || '无'}，共 ${mission.runCount} 次）\n`
    if (mission.latestRunId) content += `最近运行: ${mission.latestRunId}\n`
    if (mission.description) content += `描述: ${mission.description}\n`
    content += `创建时间: ${mission.createdAt}\n`
    content += `更新时间: ${mission.updatedAt}\n\n`
  })

  return content
}

/**
 * 导出项目列表为CSV（带BOM，Excel可直接打开）
 */
export function exportMissionsToCsv(data: MissionTableExport): string {
  const header = ['名称', 'Mission ID', '状态', '最近运行状态', '运行次数', '最近运行 ID', '创建时间', '更新时间', '描述']
  const escapeCsv = (value: string | number) => `"${String(value).replace(/"/g, '""').replace(/\n/g, ' ')}"`
  let content = `\uFEFF${header.map(escapeCsv).join(',')}\n`

  data.missions.forEach((mission) => {
    const row = [mission.name, mission.missionId, mission.status, mission.latestRunStatus, mission.runCount, mission.latestRunId, mission.createdAt, mission.updatedAt, mission.description]
    content += `${row.map(escapeCsv).join(',')}\n`
  })

  return content
}

/**
 * 导出项目列表为Markdown表格
 */
export function exportMissionsToMarkdown(data: MissionTableExport): string {
  const escapeCell = (value: string | number) => String(value).replace(/\|/g, '\\|').replace(/\n/g, ' ')
  let content = `# 工程项目导出\n\n`
  content += `**导出时间**: ${data.exportedAt}\n\n`
  content += `**项目数量**: ${data.total}\n\n`
  content += `| 名称 | Mission ID | 状态 | 最近运行 | 运行次数 | 更新时间 |\n`
  content += `| --- | --- | --- | --- | --- | --- |\n`

  data.missions.forEach((mission) => {
    const cells = [mission.name, mission.missionId, mission.status, mission.latestRunStatus || '—', mission.runCount, mission.updatedAt]
    content += `| ${cells.map(escapeCell).join(' | ')} |\n`
  })

  return content
}

export interface MissionDetailRecord {
  missionId: string
  title: string
  description: string
  status: string
  statusLabel: string
  runCount: number
  createdAt: string
  updatedAt: string
}

export interface MissionRunRecord {
  runId: string
  status: string
  statusLabel: string
  phase: string
  phaseLabel: string
  message: string
  totalSteps: number
  completedSteps: number
  failedSteps: number
  startedAt: string
  updatedAt: string
}

export interface MissionDetailExport {
  exportedAt: string
  mission: MissionDetailRecord
  totalRuns: number
  runs: MissionRunRecord[]
}

/**
 * 导出单个任务及其运行记录为JSON（含原始状态字段与中文标签）
 */
export function exportMissionDetailToJson(data: MissionDetailExport): string {
  return JSON.stringify(data, null, 2)
}

/**
 * 导出单个任务及其运行记录为TXT
 */
export function exportMissionDetailToTxt(data: MissionDetailExport): string {
  let content = `任务数据导出\n`
  content += `导出时间: ${data.exportedAt}\n`
  content += `任务标题: ${data.mission.title}\n`
  content += `Mission ID: ${data.mission.missionId}\n`
  content += `任务状态: ${data.mission.statusLabel}\n`
  content += `运行次数: ${data.mission.runCount}\n`
  if (data.mission.description) content += `任务描述: ${data.mission.description}\n`
  content += `\n${'='.repeat(50)}\n\n`

  if (!data.runs.length) {
    content += `该任务暂无运行记录。\n`
    return content
  }
  data.runs.forEach((run, index) => {
    content += `[${index + 1}] ${run.runId}\n`
    content += `状态: ${run.statusLabel}（阶段：${run.phaseLabel}）\n`
    content += `步骤: ${run.completedSteps}/${run.totalSteps}${run.failedSteps ? `（失败 ${run.failedSteps}）` : ''}\n`
    content += `开始时间: ${run.startedAt}\n`
    content += `更新时间: ${run.updatedAt}\n`
    if (run.message) content += `消息: ${run.message}\n`
    content += `\n`
  })

  return content
}

/**
 * 导出单个任务及其运行记录为CSV（带BOM；概览与运行记录两段）
 */
export function exportMissionDetailToCsv(data: MissionDetailExport): string {
  const escapeCsv = (value: string | number) => `"${String(value).replace(/"/g, '""').replace(/\n/g, ' ')}"`
  let content = `\uFEFF`

  content += `${['任务概览'].map(escapeCsv).join(',')}\n`
  const overview: Array<[string, string | number]> = [
    ['任务标题', data.mission.title],
    ['Mission ID', data.mission.missionId],
    ['任务状态', data.mission.statusLabel],
    ['运行次数', data.mission.runCount],
    ['任务描述', data.mission.description],
    ['创建时间', data.mission.createdAt],
    ['更新时间', data.mission.updatedAt]
  ]
  overview.forEach(([key, value]) => { content += `${[key, value].map(escapeCsv).join(',')}\n` })

  content += `\n${['运行记录'].map(escapeCsv).join(',')}\n`
  const header = ['运行 ID', '状态', '阶段', '已完成步骤', '总步骤', '失败步骤', '开始时间', '更新时间', '消息']
  content += `${header.map(escapeCsv).join(',')}\n`
  data.runs.forEach((run) => {
    const row = [run.runId, run.statusLabel, run.phaseLabel, run.completedSteps, run.totalSteps, run.failedSteps, run.startedAt, run.updatedAt, run.message]
    content += `${row.map(escapeCsv).join(',')}\n`
  })

  return content
}

/**
 * 导出单个任务及其运行记录为Markdown
 */
export function exportMissionDetailToMarkdown(data: MissionDetailExport): string {
  const escapeCell = (value: string | number) => String(value).replace(/\|/g, '\\|').replace(/\n/g, ' ')
  let content = `# 任务数据导出：${data.mission.title}\n\n`
  content += `**Mission ID**: ${data.mission.missionId}\n\n`
  content += `**任务状态**: ${data.mission.statusLabel}\n\n`
  content += `**运行次数**: ${data.mission.runCount}\n\n`
  if (data.mission.description) content += `**任务描述**: ${data.mission.description}\n\n`
  content += `**导出时间**: ${data.exportedAt}\n\n`

  content += `## 运行记录（${data.totalRuns}）\n\n`
  if (!data.runs.length) {
    content += `该任务暂无运行记录。\n`
    return content
  }
  content += `| 运行 ID | 状态 | 阶段 | 步骤 | 开始时间 | 更新时间 | 消息 |\n`
  content += `| --- | --- | --- | --- | --- | --- | --- |\n`
  data.runs.forEach((run) => {
    const steps = `${run.completedSteps}/${run.totalSteps}${run.failedSteps ? `（失败 ${run.failedSteps}）` : ''}`
    const cells = [run.runId, run.statusLabel, run.phaseLabel, steps, run.startedAt, run.updatedAt, run.message]
    content += `| ${cells.map(escapeCell).join(' | ')} |\n`
  })

  return content
}

/**
 * 下载文件
 */
export function downloadFile(content: string, filename: string, mimeType: string = 'text/plain') {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

