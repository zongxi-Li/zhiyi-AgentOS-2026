// 折叠连续重复的时间线块（工具轮询、思考记录分段），并提供与 ChatTranscriptBlock 一致的条目标签。
import type { ExecutionSummaryItem } from '@/stores/chat'
import type { TranscriptBlock } from '../../../backend/src/shared/chat-stream/index.mjs'

export interface TranscriptFoldGroup {
  kind: 'fold-group'
  key: string
  blocks: TranscriptBlock[]
}

export type TranscriptEntry = TranscriptBlock | TranscriptFoldGroup

// 进行中/等待确认的条目必须独立可见，不参与折叠。
const ACTIVE_STATES = new Set(['running', 'streaming', 'approval_required'])

export function foldRepeatedTranscriptBlocks(blocks: TranscriptBlock[]): TranscriptEntry[] {
  const entries: TranscriptEntry[] = []
  let index = 0
  while (index < blocks.length) {
    const block = blocks[index]!
    if (isFoldable(block)) {
      let end = index + 1
      while (end < blocks.length && sameFoldGroup(blocks[end]!, block)) end += 1
      if (end - index >= 2) {
        entries.push({ kind: 'fold-group', key: `fold:${block.id}`, blocks: blocks.slice(index, end) })
        index = end
        continue
      }
    }
    entries.push(block)
    index += 1
  }
  return entries
}

function isFoldable(block: TranscriptBlock): boolean {
  if (ACTIVE_STATES.has(block.state)) return false
  if (block.kind === 'tool') return true
  return block.kind === 'reasoning' && Boolean(block.text)
}

function sameFoldGroup(a: TranscriptBlock, b: TranscriptBlock): boolean {
  if (!isFoldable(a) || a.kind !== b.kind || a.state !== b.state) return false
  return a.kind !== 'tool' || a.toolName === b.toolName
}

const TOOL_NAMES: Record<string, string> = { read_file: '读取文件', list_files: '浏览目录', write_file: '写入文件',
  patch_file: '修改文件', run_command: '执行命令', terminal: '执行命令', get_command_output: '读取任务输出', cancel_command: '停止后台命令' }
const TOOL_STATES: Record<string, string> = { running: '正在', completed: '已完成', failed: '失败：',
  cancelled: '已取消', interrupted: '已中断', background: '已转后台：', approval_required: '等待确认：' }

export function transcriptBlockLabel(block: TranscriptBlock, item?: ExecutionSummaryItem): string {
  const name = TOOL_NAMES[block.toolName || ''] || '工具操作'
  const exit = item?.terminal?.exitCode
  return `${TOOL_STATES[block.state] || ''}${name}${exit && block.state === 'completed' ? `（退出码 ${exit}）` : ''}`
}

export function transcriptFoldGroupLabel(group: TranscriptFoldGroup): string {
  const first = group.blocks[0]
  if (first.kind === 'reasoning') return first.state === 'interrupted' ? '思考已中断' : '思考记录'
  return transcriptBlockLabel(first)
}
