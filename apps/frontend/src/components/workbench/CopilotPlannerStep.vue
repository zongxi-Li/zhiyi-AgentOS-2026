<template>
  <details class="planner-step" :open="expanded" @toggle="onToggle">
    <summary>
      <Connection class="planner-step__icon" aria-hidden="true" />
      <span class="planner-step__title">{{ execution ? '思考过程' : `规划器 · ${planningStageLabel(stage)}` }}</span>
      <small v-if="elapsedMs != null">{{ (elapsedMs / 1000).toFixed(1) }} 秒</small>
      <span class="planner-step__state" :class="`is-${state}`">{{ stateLabel }}</span>
      <ArrowRight class="planner-step__chevron" aria-hidden="true" />
    </summary>
    <div class="planner-step__anchor">
      <div ref="body" class="planner-step__body" @wheel="pauseFollow" @pointerdown="pauseFollow" @keydown="pauseFollow" @touchstart.passive="pauseFollow" @scroll="onScroll">
        <div ref="content" class="planner-step__content">
          <div class="planner-step__reasoning" :aria-label="execution ? '执行节点思考过程' : '规划器思考过程'">
            <template v-if="checklist">
              <section v-for="group in checklist.groups" :key="group.title" class="planner-step__checklist">
                <h4>{{ group.title }}</h4>
                <ul>
                  <li v-for="item in group.items" :key="item.index">
                    <small v-if="item.status !== '已确认'" class="planner-step__exception">{{ item.status }}</small>
                    <div v-html="renderCopilotMarkdown(item.text)" />
                  </li>
                </ul>
              </section>
              <details class="planner-step__raw">
                <summary>展开全部 {{ checklist.count }} 项</summary>
                <ChatTranscriptBlock :block="block" :render-text="renderCopilotMarkdown" />
              </details>
            </template>
            <ChatTranscriptBlock v-else-if="reasoning" :block="block" :render-text="renderCopilotMarkdown" />
            <ChatTranscriptBlock v-else :block="{ id: `${id}:waiting`, kind: 'status', state, text: state === 'streaming' ? (execution ? '正在等待模型返回思考内容…' : '模型尚未返回思考过程，正在等待…') : '本轮模型未返回思考过程。' }" />
            <small v-if="reasoningTruncated" class="planner-step__note">思考内容较长，此处保留最新片段。</small>
          </div>
          <details v-if="text" class="planner-step__draft"><summary>查看规划草稿</summary><ChatTranscriptBlock :block="draftBlock" :render-text="renderCopilotMarkdown" /></details>
          <small v-if="!execution" class="planner-step__note">{{ state === 'retrying' ? '本轮请求已重试，已收到的思考记录保留在这里。' : '正式计划以待确认的初步规划为准。' }}</small>
        </div>
      </div>
      <button v-if="showResume" class="planner-step__resume" type="button" @click="resumeFollow">回到底部 · 继续跟随</button>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowRight, Connection } from '@element-plus/icons-vue'
import ChatTranscriptBlock from '@/components/ChatTranscriptBlock.vue'
import type { TranscriptBlock } from '../../../../backend/src/shared/chat-stream/index.mjs'
import { planningStageLabel } from './copilotConversation'
import { renderCopilotMarkdown } from './copilotMarkdown'

const props = withDefaults(defineProps<{ id: string; stage?: string | null; text: string; state: string; elapsedMs?: number | null; reasoning?: string; reasoningTruncated?: boolean; execution?: boolean }>(), { reasoning: '', reasoningTruncated: false, execution: false })
const body = ref<HTMLElement | null>(null)
const content = ref<HTMLElement | null>(null)
let manuallyToggled = false
const following = ref(true)
let frameId = 0
let pendingEcho = false
const block = computed<TranscriptBlock>(() => ({ id: `${props.id}:reasoning`, kind: 'text', state: props.state === 'retrying' ? 'interrupted' : props.state, text: props.reasoning }))
const draftBlock = computed<TranscriptBlock>(() => ({ id: props.id, kind: 'text', state: props.state, text: props.text }))
const checklist = computed(() => {
  if (props.state !== 'completed' || props.reasoningTruncated) return null
  const lines = props.reasoning.trim().split(/\r?\n/).map(line => line.trim()).filter(Boolean)
  if (lines.length < 4) return null
  type Item = { text: string; index: number; status: string; priority: number }
  const groups = [
    { title: '目录与结构', pattern: /目录|根层|根路径|构建产物|构建\/依赖产物|源码实际|源码位于/, items: [] as Item[] },
    { title: '前端与接口', pattern: /前端|接口边界/, items: [] as Item[] },
    { title: '后端与运行', pattern: /后端|backend|Node|数据库|迁移|\bCI\b|端口|超时/, items: [] as Item[] },
    { title: '其他检查', pattern: /./, items: [] as Item[] },
  ]
  let confirmed = 0
  for (const [index, line] of lines.entries()) {
    const match = line.match(/^(?:(?:[-*+] |\d+[.)] )\s*)?([^#>|].*?)\s*[（(](已确认|待核实|失败)(?:[，,][^）)]*)?[）)]$/)
    if (!match || line.startsWith('```') || line.startsWith('~~~')) return null
    const text = match[1].replace(/(?<![`\w/])(?:[\w.-]+\/)+[\w.-]*/g, '`$&`')
    const status = match[2]
    if (status === '已确认') confirmed++
    const group = groups.find(group => group.pattern.test(text))
    const priority = status !== '已确认' ? 2 : Number(/缺少|为空|仅有|位于/.test(text))
    group?.items.push({ text, index, status, priority })
  }
  return { confirmed, count: lines.length, groups: groups.filter(group => group.items.length).map(group => ({
    title: group.title,
    items: group.items.sort((a, b) => b.priority - a.priority).slice(0, 3),
  })) }
})
const expanded = ref(props.state === 'streaming' || props.state === 'interrupted' || Boolean(checklist.value))
const stateLabel = computed(() => {
  const checks = checklist.value
  if (checks) return `${checks.confirmed === checks.count ? checks.count : `${checks.confirmed}/${checks.count}`} 项已确认`
  if (props.execution && props.state === 'streaming') return props.reasoning ? '正在思考' : '等待返回'
  return ({ streaming: '正在生成', completed: '已返回', interrupted: '已中断', retrying: '已重试' } as Record<string, string>)[props.state] || '生成记录'
})
const showResume = computed(() => expanded.value && !following.value && props.state === 'streaming')
function onToggle(event: Event) {
  const open = (event.target as HTMLDetailsElement).open
  if (open !== expanded.value) { manuallyToggled = true; expanded.value = open }
}
watch(() => props.state, state => {
  if (!manuallyToggled) expanded.value = state === 'streaming' || state === 'interrupted' || Boolean(checklist.value)
})
watch(checklist, (value, previous) => {
  if (value && !previous && body.value) body.value.scrollTop = 0
}, { flush: 'post' })
function canFollow() {
  return props.state === 'streaming' && expanded.value && following.value && !document.hidden && !!body.value
}
function pinToTail() {
  const element = body.value
  if (!element || !canFollow()) return
  pendingEcho = true
  element.scrollTop = element.scrollHeight
}
function pauseFollow() { following.value = false; pendingEcho = false; cancelPin() }
function onScroll() {
  const element = body.value
  if (!element) return
  const atEnd = element.scrollHeight - element.scrollTop - element.clientHeight < 24
  if (!atEnd) { following.value = false; pendingEcho = false; return }
  // Each programmatic pin consumes exactly one at-end echo; any other at-end
  // scroll is a human dragging back, which resumes following.
  if (pendingEcho) { pendingEcho = false; return }
  following.value = true
}
function resumeFollow() { following.value = true; pinToTail() }
function cancelPin() {
  if (frameId) { cancelAnimationFrame(frameId); frameId = 0 }
}
function schedulePin() {
  if (!canFollow()) { cancelPin(); return }
  if (!frameId) frameId = requestAnimationFrame(() => { frameId = 0; pinToTail() })
}
// Content updates share one frame. Observe its natural height so late wrapping
// or highlighting still follows the tail without reading layout on idle frames.
watch([() => props.reasoning, () => props.text, () => props.reasoningTruncated,
  () => props.state, expanded, following, body], schedulePin, { flush: 'post' })
watch(content, (element, _, onCleanup) => {
  if (!element || typeof ResizeObserver === 'undefined') return
  const observer = new ResizeObserver(schedulePin)
  observer.observe(element)
  onCleanup(() => observer.disconnect())
}, { flush: 'post' })
onMounted(() => document.addEventListener('visibilitychange', schedulePin))
onBeforeUnmount(() => { cancelPin(); document.removeEventListener('visibilitychange', schedulePin) })
</script>

<style scoped>
.planner-step { min-width: 0; margin: 0 0 16px; color: var(--wb-text-secondary); }
summary { display: flex; align-items: center; gap: 8px; min-height: 30px; cursor: pointer; list-style: none; color: var(--wb-text-muted); font-size: 12px; }
summary::-webkit-details-marker { display: none; }
summary:hover { color: var(--wb-text); }
summary:focus-visible { outline: 1px solid var(--wb-accent); outline-offset: 3px; border-radius: 4px; }
.planner-step__icon, .planner-step__chevron { width: 13px; height: 13px; flex-shrink: 0; }
.planner-step__chevron { width: 10px; height: 10px; transition: transform 140ms; }
[open] > summary .planner-step__chevron { transform: rotate(90deg); }
.planner-step__title { min-width: 0; overflow-wrap: anywhere; }
summary small, .planner-step__state { flex-shrink: 0; font-size: 10px; }
.planner-step__state { margin-left: auto; }
.is-streaming { color: var(--wb-accent); }
.is-interrupted, .is-retrying { color: var(--wb-danger); }
.planner-step__anchor { position: relative; }
.planner-step__body { max-height: 320px; overflow: auto; overscroll-behavior: contain; margin: 10px 0 0; padding: 0 10px 0 0; overflow-wrap: anywhere; }
.planner-step__resume { position: absolute; right: 18px; bottom: 12px; padding: 5px 11px; border: 1px solid var(--wb-border); border-radius: 999px; background: var(--wb-surface-1); color: var(--wb-accent); font-size: 11px; cursor: pointer; box-shadow: 0 4px 14px rgba(0, 0, 0, .28); }
.planner-step__resume:hover, .planner-step__resume:focus-visible { border-color: color-mix(in srgb, var(--wb-accent) 55%, var(--wb-border)); color: var(--wb-text); }
.planner-step__body :deep(.message-text) { color: var(--wb-text-secondary); font-size: var(--cp-prose-size, 14px); line-height: var(--cp-prose-line-height, 1.75); }
.planner-step__body :deep(.markdown-body) { white-space: normal; }
.planner-step__body :deep(.markdown-body p) { margin: 0 0 .45em; }
.planner-step__body :deep(.markdown-body li) { margin: .15em 0; }
.planner-step__checklist { margin-block: 0 12px; font-size: 14px; line-height: 1.45; }
.planner-step__checklist h4 { margin: 0 0 3px; font-size: inherit; font-weight: 600; color: var(--wb-text); }
.planner-step__checklist ul { margin: 0; padding-inline-start: 18px; }
.planner-step__checklist li + li { margin-top: 3px; }
.planner-step__checklist :deep(p) { margin: 0; }
.planner-step__checklist :deep(code) { font-size: .92em; }
.planner-step__exception { display: inline-block; margin-inline-end: 6px; color: var(--wb-danger); }
.planner-step__exception + div { display: inline; }
.planner-step__exception + div :deep(p) { display: inline; }
.planner-step__raw > summary { min-height: 24px; color: var(--wb-accent); }
.planner-step__body :deep(pre) { max-width: 100%; overflow: auto; }
.planner-step__body :deep(.chat-recovery), .planner-step__note { color: var(--wb-text-muted); font-size: 11px; }
.planner-step__note { display: block; margin-top: 12px; }
.planner-step__draft { margin: 12px 0; }
.planner-step__draft > summary { font-size: 11px; }
.planner-step__draft :deep(.markdown-body) { line-height: 1.65; }
/* Projected draft fields are not prose paragraphs. Let adjacent fields share
   a line while retaining real Markdown headings, lists and code blocks. */
.planner-step__draft :deep(.markdown-body > p) { display: inline; margin: 0; }
.planner-step__draft :deep(.markdown-body > p:not(:last-child))::after { content: ' · '; color: var(--wb-text-muted); }
@media (prefers-reduced-motion: reduce) { .planner-step__chevron { transition: none; } }
</style>
