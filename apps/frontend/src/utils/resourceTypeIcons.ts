import { Box, Connection, Cpu, DataLine, MagicStick, Monitor, Tools, User } from '@element-plus/icons-vue'
import type { Component } from 'vue'

/** 资源类型到图标的映射，概览行/详情/注册表单共用，保持单一来源。 */
export const RESOURCE_TYPE_ICONS: Record<string, Component> = {
  agent: User,
  skill: MagicStick,
  mcp: Connection,
  tool: Tools,
  model: Box,
  worker: Monitor,
  embedding: DataLine
}

/** 资源类型图标，未知类型回退为通用 CPU 图标。 */
export const resourceTypeIcon = (value?: string | null): Component => RESOURCE_TYPE_ICONS[value || ''] || Cpu
