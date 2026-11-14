<template>
  <div v-if="block.kind === 'text'" class="chat-text-step">
    <div class="message-text markdown-body" v-html="html" />
    <small v-if="block.state === 'interrupted'" class="chat-text-step__notice">此段输出已中断</small>
  </div>
  <p v-else-if="block.kind === 'status'" class="chat-recovery" role="status">{{ block.text }}</p>
  <details v-else-if="block.kind === 'reasoning' && block.text" class="chat-step chat-step--reasoning">
    <summary>{{ block.state === 'streaming' ? '正在思考' : block.state === 'interrupted' ? '思考已中断' : '思考记录' }}</summary>
    <pre>{{ block.text }}</pre>
    <small v-if="block.truncated">展示记录已达到长度上限，后续片段已截断</small>
  </details>
  <details v-else-if="block.kind === 'tool'" class="chat-step" :open="item?.approval?.status === 'pending'">
    <summary><span class="chat-step__signal" :class="{ active: running }" />{{ label }}<span v-if="item?.durationMs" class="chat-step__duration">{{ Math.max(0.1, item.durationMs / 1000).toFixed(1) }} 秒</span></summary>
    <ConversationWorkFeed v-if="item" :items="[item]" />
    <p v-else>正在准备操作</p>
  </details>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TranscriptBlock } from '../../../backend/src/shared/chat-stream/index.mjs'
import type { ExecutionSummaryItem } from '@/stores/chat'
import { renderMarkdown } from '@/utils/markdown'
import ConversationWorkFeed from './ConversationWorkFeed.vue'

const props = defineProps<{ block: TranscriptBlock; item?: ExecutionSummaryItem }>()
const item = computed(() => props.item)
const html = computed(() => props.block.kind === 'text' ? renderMarkdown(props.block.text || '') : '')
const running = computed(() => ['streaming', 'running', 'approval_required'].includes(props.block.state))
const label = computed(() => {
  const names: Record<string, string> = { read_file: '读取文件', list_files: '浏览目录', write_file: '写入文件',
    patch_file: '修改文件', run_command: '执行命令', terminal: '执行命令', get_command_output: '读取任务输出', cancel_command: '停止后台命令' }
  const name = names[props.block.toolName || ''] || '工具操作'
  const status: Record<string, string> = { running: '正在', completed: '已完成', failed: '失败：',
    cancelled: '已取消', interrupted: '已中断', background: '已转后台：', approval_required: '等待确认：' }
  const exit = item.value?.terminal?.exitCode
  return `${status[props.block.state] || ''}${name}${exit && props.block.state === 'completed' ? `（退出码 ${exit}）` : ''}`
})
</script>

<style scoped>
.chat-step { margin: 16px 0; color: var(--text-secondary); font-size: 13px; }
.chat-text-step__notice { color: var(--text-secondary); font-size: 11px; }
.chat-recovery { margin: 12px 0; color: var(--text-secondary); font-size: 12px; }
.chat-step summary { display: flex; align-items: center; gap: 8px; width: fit-content; cursor: pointer; list-style: none; }
.chat-step summary::before { content: '›'; font-size: 17px; transition: transform 140ms; }
.chat-step[open] > summary::before { transform: rotate(90deg); }
.chat-step[open] > summary { margin-bottom: 10px; }
.chat-step pre { max-height: 240px; overflow: auto; white-space: pre-wrap; line-height: 1.6; margin-left: 16px; }
.chat-step__duration { color: var(--text-disabled); font-size: 11px; }
.chat-step__signal { width: 6px; height: 6px; border-radius: 50%; background: var(--text-disabled); }
.chat-step__signal.active { background: var(--primary-color); animation: breathe 1.2s ease-in-out infinite; }
@keyframes breathe { 50% { opacity: .35; } }
</style>
