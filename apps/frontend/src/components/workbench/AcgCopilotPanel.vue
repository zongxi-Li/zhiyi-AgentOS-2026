<template>
  <section class="acg-copilot" aria-label="ACG Copilot 演示面板">
    <header class="acg-copilot__header">
      <div class="acg-copilot__identity">
        <span class="acg-copilot__mark" aria-hidden="true"><el-icon><Cpu /></el-icon></span>
        <div>
          <div class="acg-copilot__eyebrow">ACG COPILOT</div>
          <strong>用模型操作当前图</strong>
        </div>
      </div>
      <div class="acg-copilot__header-actions">
        <span class="acg-copilot__mode"><i aria-hidden="true"></i>预览模式</span>
        <button type="button" title="新建会话" aria-label="新建会话" @click="resetSession">
          <el-icon><Plus /></el-icon>
        </button>
        <button type="button" title="更多操作" aria-label="更多操作" :aria-expanded="moreOpen" @click="moreOpen = !moreOpen">
          <el-icon><MoreFilled /></el-icon>
        </button>
        <div v-if="moreOpen" class="acg-copilot__more-menu" role="menu">
          <button type="button" role="menuitem" @click="resetSession">清空演示会话</button>
          <button type="button" role="menuitem" @click="contextOpen = true; moreOpen = false">查看当前上下文</button>
        </div>
      </div>
    </header>

    <div class="acg-copilot__context" :class="{ 'is-open': contextOpen }">
      <button class="acg-copilot__context-toggle" type="button" :aria-expanded="contextOpen" @click="contextOpen = !contextOpen">
        <span class="acg-copilot__context-left">
          <el-icon><Share /></el-icon>
          <span class="acg-copilot__context-title">{{ targetTitle }}</span>
          <span class="acg-copilot__context-state">{{ runStateLabel }}</span>
        </span>
        <span class="acg-copilot__context-chevron" :class="{ rotated: contextOpen }" aria-hidden="true">⌄</span>
      </button>
      <div v-if="contextOpen" class="acg-copilot__context-details">
        <span><b>{{ nodeCountLabel }}</b> 节点</span>
        <span><b>{{ edgeCountLabel }}</b> 关系</span>
        <span v-if="runId" class="acg-copilot__context-run" :title="runId">{{ shortRunId }}</span>
        <span v-else>尚未启动 Run</span>
      </div>
    </div>

    <nav class="acg-copilot__tabs" role="tablist" aria-label="Copilot 视图">
      <button type="button" role="tab" :aria-selected="activeTab === 'chat'" :class="{ active: activeTab === 'chat' }" @click="activeTab = 'chat'">
        <el-icon><ChatDotRound /></el-icon>
        对话
      </button>
      <button type="button" role="tab" :aria-selected="activeTab === 'plan'" :class="{ active: activeTab === 'plan' }" @click="activeTab = 'plan'">
        <el-icon><Share /></el-icon>
        执行预览
        <span v-if="planItems.length" class="acg-copilot__tab-count">{{ planItems.length }}</span>
      </button>
    </nav>

    <div v-if="activeTab === 'chat'" ref="messageList" class="acg-copilot__messages" aria-live="polite">
      <article v-for="message in messages" :key="message.id" class="acg-copilot__message" :class="`is-${message.role}`">
        <div v-if="message.role === 'assistant'" class="acg-copilot__avatar" aria-hidden="true"><el-icon><Cpu /></el-icon></div>
        <div class="acg-copilot__message-body">
          <div class="acg-copilot__message-meta">
            <span>{{ message.role === 'assistant' ? 'ACG Copilot' : '你' }}</span>
            <small>{{ message.meta }}</small>
          </div>
          <p>{{ message.content }}</p>
          <div v-if="message.actions?.length" class="acg-copilot__message-actions">
            <button v-for="action in message.actions" :key="action" type="button" @click="useSuggestion(action)">{{ action }}</button>
          </div>
        </div>
      </article>
      <article v-if="isThinking" class="acg-copilot__message is-assistant is-thinking">
        <div class="acg-copilot__avatar" aria-hidden="true"><el-icon><Cpu /></el-icon></div>
        <div class="acg-copilot__message-body">
          <div class="acg-copilot__message-meta"><span>ACG Copilot</span><small>正在整理上下文</small></div>
          <div class="acg-copilot__thinking"><i></i><i></i><i></i></div>
        </div>
      </article>
    </div>

    <div v-else class="acg-copilot__plan-view">
      <div class="acg-copilot__plan-intro">
        <span class="acg-copilot__plan-mark"><el-icon><Share /></el-icon></span>
        <div>
          <strong>下一次操作预览</strong>
          <p>模型会先提出变更，再等待你的确认。</p>
        </div>
      </div>
      <div class="acg-copilot__plan-list">
        <div v-for="(item, index) in planItems" :key="item.title" class="acg-copilot__plan-item">
          <span class="acg-copilot__plan-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="acg-copilot__plan-dot" :class="`is-${item.state}`" aria-hidden="true"></span>
          <div>
            <strong>{{ item.title }}</strong>
            <small>{{ item.detail }}</small>
          </div>
          <span class="acg-copilot__plan-state">{{ item.label }}</span>
        </div>
      </div>
      <div class="acg-copilot__plan-footer">
        <span><i aria-hidden="true"></i>只读预览，不会修改当前图</span>
        <button type="button" @click="activeTab = 'chat'">返回对话</button>
      </div>
    </div>

    <div class="acg-copilot__suggestions" aria-label="建议操作">
      <button v-for="suggestion in suggestions" :key="suggestion" type="button" @click="useSuggestion(suggestion)">
        {{ suggestion }}
      </button>
    </div>

    <form class="acg-copilot__composer" @submit.prevent="sendMessage">
      <textarea
        v-model="draft"
        rows="1"
        placeholder="让模型检查、解释或准备一次 ACG 操作…"
        aria-label="输入 ACG 操作"
        @keydown.enter.exact.prevent="sendMessage"
        @keydown.enter.shift.exact.stop
      ></textarea>
      <div class="acg-copilot__composer-footer">
        <span class="acg-copilot__composer-hint"><el-icon><Monitor /></el-icon> {{ modelLabel }}</span>
        <div class="acg-copilot__composer-actions">
          <button type="button" title="展开上下文" aria-label="展开上下文" @click="contextOpen = !contextOpen"><el-icon><Plus /></el-icon></button>
          <button class="acg-copilot__send" type="submit" :disabled="!draft.trim() || isThinking" aria-label="发送">
            <el-icon v-if="!isThinking"><ArrowUp /></el-icon>
            <el-icon v-else class="is-loading"><Loading /></el-icon>
          </button>
        </div>
      </div>
    </form>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ArrowUp, ChatDotRound, Cpu, Loading, Monitor, MoreFilled, Plus, Share } from '@element-plus/icons-vue'
import type { GraphProjection, WorkspaceEntry, WorkspaceGraphNode } from '@/services/api/agentos'
import type { RuntimeObservation } from '@/workbench/runtime/observation'

type MessageRole = 'assistant' | 'user'
type DemoMessage = { id: string; role: MessageRole; content: string; meta: string; actions?: string[] }
type PlanItem = { title: string; detail: string; state: 'ready' | 'pending' | 'done'; label: string }

const props = withDefaults(defineProps<{
  entry?: WorkspaceEntry | null
  graphNode?: WorkspaceGraphNode | null
  graphNodes?: WorkspaceGraphNode[]
  graph?: GraphProjection | null
  runId?: string | null
  runStatus?: string | null
  runtimeObservation?: RuntimeObservation | null
  historical?: boolean
}>(), {
  entry: null,
  graphNode: null,
  graphNodes: () => [],
  graph: null,
  runId: null,
  runStatus: null,
  runtimeObservation: null,
  historical: false
})

const contextOpen = ref(true)
const activeTab = ref<'chat' | 'plan'>('chat')
const draft = ref('')
const isThinking = ref(false)
const moreOpen = ref(false)
const messageList = ref<HTMLElement | null>(null)
const suggestions = ['检查当前图', '解释失败节点', '准备执行计划']
const modelLabel = 'GPT-5.6 Sol · 中等'
const planItems: PlanItem[] = [
  { title: '读取当前 ACG 图', detail: '确认节点、关系和运行上下文', state: 'done', label: '已读取' },
  { title: '定位关键节点', detail: '根据状态与依赖关系整理候选项', state: 'ready', label: '待确认' },
  { title: '生成下一步建议', detail: '只生成计划，不直接修改运行图', state: 'pending', label: '预览中' }
]

const initialMessages = (): DemoMessage[] => [
  {
    id: 'intro',
    role: 'assistant',
    content: '我可以帮你检查当前 ACG、解释节点状态，并准备下一步可确认的操作。',
    meta: '现在 · 演示对话',
    actions: suggestions
  },
  {
    id: 'sample-user',
    role: 'user',
    content: '先看看当前图，告诉我下一步应该处理什么。',
    meta: '刚刚'
  },
  {
    id: 'sample-assistant',
    role: 'assistant',
    content: '收到。我会先读取结构和运行上下文，再把建议拆成可检查的步骤；真正执行前会等你确认。',
    meta: '刚刚 · 只读预览'
  }
]
const messages = ref<DemoMessage[]>(initialMessages())

const targetTitle = computed(() => props.graphNode?.name || props.entry?.name || 'graph.acg')
const nodeCountLabel = computed(() => props.graph?.nodes?.length ?? (props.graphNodes.length || '—'))
const edgeCountLabel = computed(() => props.graph?.edges?.length ?? '—')
const shortRunId = computed(() => {
  if (!props.runId) return ''
  return props.runId.length > 18 ? `${props.runId.slice(0, 10)}…${props.runId.slice(-5)}` : props.runId
})
const runStateLabel = computed(() => {
  if (props.historical) return '历史只读'
  if (!props.runStatus) return '等待 Run'
  const labels: Record<string, string> = {
    pending: '等待中', planning: '规划中', running: '运行中', executing: '执行中',
    succeeded: '已完成', completed: '已完成', failed: '失败', cancelled: '已取消'
  }
  return labels[props.runStatus] || props.runStatus
})

const scrollMessages = () => {
  void nextTick(() => {
    const element = messageList.value
    if (element) element.scrollTop = element.scrollHeight
  })
}

const useSuggestion = (suggestion: string) => {
  if (suggestion === '查看执行预览') {
    activeTab.value = 'plan'
    return
  }
  draft.value = suggestion
  activeTab.value = 'chat'
  scrollMessages()
}

const resetSession = () => {
  messages.value = initialMessages()
  draft.value = ''
  isThinking.value = false
  moreOpen.value = false
  activeTab.value = 'chat'
  scrollMessages()
}

const sendMessage = () => {
  const text = draft.value.trim()
  if (!text || isThinking.value) return
  messages.value.push({ id: `user-${Date.now()}`, role: 'user', content: text, meta: '刚刚' })
  draft.value = ''
  isThinking.value = true
  scrollMessages()
  window.setTimeout(() => {
    messages.value.push({
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content: `已记录“${text}”。这是展示用的只读预览，下一步会先生成变更计划，再交由你确认。`,
      meta: '刚刚 · 演示回复',
      actions: ['查看执行预览', '继续说明']
    })
    isThinking.value = false
    scrollMessages()
  }, 620)
}
</script>

<style scoped>
.acg-copilot {
  --copilot-border: var(--wb-border-soft);
  --copilot-inset: var(--wb-surface-inset);
  display: flex;
  min-width: 0;
  min-height: 420px;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--copilot-border);
  border-radius: 9px;
  background: var(--wb-surface-pane);
  color: var(--wb-text);
  box-shadow: 0 8px 20px color-mix(in srgb, #000 18%, transparent);
}

.acg-copilot__header {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 52px;
  padding: 8px 10px 8px 12px;
  border-bottom: 1px solid var(--copilot-border);
  background: color-mix(in srgb, var(--wb-surface-pane) 86%, var(--wb-surface-inset));
}

.acg-copilot__identity,
.acg-copilot__header-actions,
.acg-copilot__context-left,
.acg-copilot__composer-footer,
.acg-copilot__composer-actions,
.acg-copilot__message-meta,
.acg-copilot__plan-intro,
.acg-copilot__plan-footer {
  display: flex;
  align-items: center;
}

.acg-copilot__identity { min-width: 0; gap: 8px; }
.acg-copilot__mark {
  display: inline-flex;
  width: 27px;
  height: 27px;
  align-items: center;
  justify-content: center;
  flex: 0 0 27px;
  border: 1px solid color-mix(in srgb, var(--wb-accent) 34%, var(--copilot-border));
  border-radius: 7px;
  color: var(--wb-accent);
  background: var(--wb-accent-soft);
  font-size: 14px;
}
.acg-copilot__identity > div { min-width: 0; }
.acg-copilot__eyebrow { color: var(--wb-accent); font: 9px/1 var(--font-mono, monospace); letter-spacing: .12em; }
.acg-copilot__identity strong { display: block; margin-top: 4px; overflow: hidden; font-size: 12px; font-weight: 680; text-overflow: ellipsis; white-space: nowrap; }
.acg-copilot__header-actions { gap: 3px; }
.acg-copilot__header-actions > button,
.acg-copilot__composer-actions > button {
  display: inline-grid;
  width: 25px;
  height: 25px;
  place-items: center;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 5px;
  color: var(--wb-text-muted);
  background: transparent;
  cursor: pointer;
  transition: color 140ms var(--ease-out), background-color 140ms var(--ease-out), border-color 140ms var(--ease-out);
}
.acg-copilot__header-actions > button:hover,
.acg-copilot__header-actions > button:focus-visible,
.acg-copilot__composer-actions > button:hover,
.acg-copilot__composer-actions > button:focus-visible { border-color: var(--copilot-border); color: var(--wb-text); background: var(--wb-hover); outline: none; }
.acg-copilot__mode { display: inline-flex; align-items: center; gap: 5px; margin-right: 2px; color: var(--wb-text-muted); font-size: 9px; white-space: nowrap; }
.acg-copilot__mode i,
.acg-copilot__plan-footer i { width: 5px; height: 5px; border-radius: 50%; background: var(--wb-success); box-shadow: 0 0 0 3px color-mix(in srgb, var(--wb-success) 12%, transparent); }
.acg-copilot__more-menu { position: absolute; top: 43px; right: 8px; z-index: 20; display: grid; width: 142px; padding: 4px; border: 1px solid var(--copilot-border); border-radius: 6px; background: var(--wb-surface-section); box-shadow: var(--shadow-md); }
.acg-copilot__more-menu button { min-height: 27px; padding: 0 8px; border: 0; border-radius: 4px; color: var(--wb-text-secondary); background: transparent; cursor: pointer; font: 9px var(--font-sans, sans-serif); text-align: left; }
.acg-copilot__more-menu button:hover { color: var(--wb-text); background: var(--wb-hover); }

.acg-copilot__context { border-bottom: 1px solid var(--copilot-border); background: var(--copilot-inset); }
.acg-copilot__context-toggle { width: 100%; min-height: 32px; display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 0 11px; border: 0; color: var(--wb-text-secondary); background: transparent; text-align: left; cursor: pointer; }
.acg-copilot__context-toggle:hover { color: var(--wb-text); background: var(--wb-hover); }
.acg-copilot__context-left { min-width: 0; gap: 6px; }
.acg-copilot__context-left > .el-icon { flex: 0 0 auto; color: var(--wb-accent); font-size: 12px; }
.acg-copilot__context-title { min-width: 0; overflow: hidden; color: var(--wb-text); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.acg-copilot__context-state { flex: 0 0 auto; padding: 2px 5px; border: 1px solid var(--copilot-border); border-radius: 4px; color: var(--wb-text-muted); font-size: 9px; }
.acg-copilot__context-chevron { color: var(--wb-text-muted); font-size: 14px; line-height: 1; transform: translateY(-2px); transition: transform 140ms var(--ease-out); }
.acg-copilot__context-chevron.rotated { transform: rotate(180deg) translateY(2px); }
.acg-copilot__context-details { display: flex; align-items: center; gap: 10px; padding: 0 11px 7px 29px; color: var(--wb-text-muted); font-size: 9px; }
.acg-copilot__context-details b { color: var(--wb-text-secondary); font-weight: 650; }
.acg-copilot__context-run { min-width: 0; overflow: hidden; margin-left: auto; font-family: var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }

.acg-copilot__tabs { display: flex; gap: 2px; min-height: 32px; padding: 4px 7px 3px; border-bottom: 1px solid var(--copilot-border); background: var(--wb-surface-pane); }
.acg-copilot__tabs button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; min-width: 0; min-height: 25px; flex: 1 1 0; padding: 0 7px; border: 1px solid transparent; border-radius: 5px; color: var(--wb-text-muted); background: transparent; cursor: pointer; font: 10px var(--font-sans, sans-serif); transition: color 140ms var(--ease-out), background-color 140ms var(--ease-out), border-color 140ms var(--ease-out); }
.acg-copilot__tabs button:hover { color: var(--wb-text-secondary); background: var(--wb-hover); }
.acg-copilot__tabs button.active { border-color: color-mix(in srgb, var(--wb-accent) 30%, var(--copilot-border)); color: var(--wb-accent); background: var(--wb-accent-soft); font-weight: 650; }
.acg-copilot__tabs button:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: -1px; }
.acg-copilot__tabs .el-icon { font-size: 11px; }
.acg-copilot__tab-count { min-width: 15px; padding: 1px 4px; border-radius: 999px; color: var(--wb-accent); background: color-mix(in srgb, var(--wb-accent) 13%, transparent); font-size: 8px; }

.acg-copilot__messages { display: flex; min-height: 120px; flex: 1 1 auto; flex-direction: column; gap: 13px; padding: 13px 11px 9px; overflow: auto; scrollbar-gutter: stable; }
.acg-copilot__message { display: flex; align-items: flex-start; gap: 7px; min-width: 0; }
.acg-copilot__message.is-user { justify-content: flex-end; }
.acg-copilot__avatar { display: inline-flex; width: 20px; height: 20px; flex: 0 0 20px; align-items: center; justify-content: center; border: 1px solid color-mix(in srgb, var(--wb-accent) 28%, var(--copilot-border)); border-radius: 5px; color: var(--wb-accent); background: var(--wb-accent-soft); font-size: 10px; }
.acg-copilot__message-body { min-width: 0; max-width: 88%; }
.acg-copilot__message.is-user .acg-copilot__message-body { max-width: 84%; padding: 7px 9px; border: 1px solid color-mix(in srgb, var(--wb-accent) 20%, var(--copilot-border)); border-radius: 8px 3px 8px 8px; background: color-mix(in srgb, var(--wb-accent) 9%, var(--wb-surface-section)); }
.acg-copilot__message-meta { gap: 7px; min-width: 0; margin-bottom: 3px; color: var(--wb-text-secondary); font-size: 9px; }
.acg-copilot__message-meta small { overflow: hidden; color: var(--wb-text-muted); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.acg-copilot__message p { margin: 0; color: var(--wb-text-secondary); font-size: 10px; line-height: 1.55; text-wrap: pretty; }
.acg-copilot__message.is-user p { color: var(--wb-text); }
.acg-copilot__message-actions { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
.acg-copilot__message-actions button { min-height: 23px; padding: 0 7px; border: 1px solid color-mix(in srgb, var(--wb-accent) 30%, var(--copilot-border)); border-radius: 5px; color: var(--wb-accent); background: var(--wb-accent-soft); cursor: pointer; font: 9px var(--font-sans, sans-serif); }
.acg-copilot__message-actions button:hover { border-color: var(--wb-accent); background: color-mix(in srgb, var(--wb-accent) 17%, transparent); }
.acg-copilot__thinking { display: flex; gap: 4px; padding: 6px 0 2px; }
.acg-copilot__thinking i { width: 4px; height: 4px; border-radius: 50%; background: var(--wb-accent); animation: acg-copilot-bounce 1s infinite ease-in-out; }
.acg-copilot__thinking i:nth-child(2) { animation-delay: .12s; }
.acg-copilot__thinking i:nth-child(3) { animation-delay: .24s; }

.acg-copilot__plan-view { display: flex; min-height: 230px; flex: 1 1 auto; flex-direction: column; padding: 12px 11px 9px; overflow: auto; }
.acg-copilot__plan-intro { gap: 8px; padding: 8px; border: 1px solid var(--copilot-border); border-radius: 7px; background: var(--copilot-inset); }
.acg-copilot__plan-mark { display: inline-flex; width: 26px; height: 26px; flex: 0 0 26px; align-items: center; justify-content: center; border-radius: 6px; color: var(--wb-accent); background: var(--wb-accent-soft); font-size: 12px; }
.acg-copilot__plan-intro strong { display: block; color: var(--wb-text); font-size: 10px; }
.acg-copilot__plan-intro p { margin: 2px 0 0; color: var(--wb-text-muted); font-size: 9px; line-height: 1.45; }
.acg-copilot__plan-list { display: grid; gap: 0; margin-top: 11px; }
.acg-copilot__plan-item { display: grid; grid-template-columns: 19px 7px minmax(0, 1fr) auto; align-items: center; gap: 6px; min-height: 48px; border-bottom: 1px solid color-mix(in srgb, var(--copilot-border) 72%, transparent); }
.acg-copilot__plan-index { color: var(--wb-text-muted); font: 9px var(--font-mono, monospace); }
.acg-copilot__plan-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--wb-text-muted); }
.acg-copilot__plan-dot.is-done { background: var(--wb-success); }
.acg-copilot__plan-dot.is-ready { background: var(--wb-accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--wb-accent) 12%, transparent); }
.acg-copilot__plan-item strong { display: block; overflow: hidden; color: var(--wb-text-secondary); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.acg-copilot__plan-item small { display: block; overflow: hidden; margin-top: 2px; color: var(--wb-text-muted); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.acg-copilot__plan-state { color: var(--wb-text-muted); font-size: 8px; white-space: nowrap; }
.acg-copilot__plan-item:nth-child(2) .acg-copilot__plan-state { color: var(--wb-accent); }
.acg-copilot__plan-footer { justify-content: space-between; gap: 8px; margin-top: auto; padding-top: 11px; color: var(--wb-text-muted); font-size: 8px; }
.acg-copilot__plan-footer > span { display: inline-flex; align-items: center; gap: 5px; }
.acg-copilot__plan-footer button { padding: 0; border: 0; color: var(--wb-accent); background: transparent; cursor: pointer; font: inherit; }

.acg-copilot__suggestions { display: flex; gap: 5px; min-height: 30px; align-items: center; padding: 4px 9px; overflow-x: auto; border-top: 1px solid var(--copilot-border); scrollbar-width: none; }
.acg-copilot__suggestions::-webkit-scrollbar { display: none; }
.acg-copilot__suggestions button { flex: 0 0 auto; min-height: 21px; padding: 0 7px; border: 1px solid var(--copilot-border); border-radius: 5px; color: var(--wb-text-muted); background: transparent; cursor: pointer; font: 8px var(--font-sans, sans-serif); white-space: nowrap; }
.acg-copilot__suggestions button:hover { border-color: color-mix(in srgb, var(--wb-accent) 42%, var(--copilot-border)); color: var(--wb-accent); background: var(--wb-accent-soft); }
.acg-copilot__composer { display: flex; flex-direction: column; min-height: 74px; margin: 0 8px 8px; padding: 7px 8px 5px; border: 1px solid color-mix(in srgb, var(--wb-accent) 23%, var(--copilot-border)); border-radius: 8px; background: var(--copilot-inset); box-shadow: inset 0 1px 0 color-mix(in srgb, #fff 3%, transparent); }
.acg-copilot__composer:focus-within { border-color: color-mix(in srgb, var(--wb-accent) 62%, var(--copilot-border)); box-shadow: 0 0 0 2px color-mix(in srgb, var(--wb-accent) 10%, transparent); }
.acg-copilot__composer textarea { min-height: 30px; flex: 1 1 auto; width: 100%; resize: none; padding: 1px 0 3px; border: 0; outline: 0; color: var(--wb-text); background: transparent; font: 10px/1.45 var(--font-sans, sans-serif); }
.acg-copilot__composer textarea::placeholder { color: var(--wb-text-muted); }
.acg-copilot__composer-footer { justify-content: space-between; gap: 7px; }
.acg-copilot__composer-hint { display: inline-flex; align-items: center; gap: 4px; min-width: 0; overflow: hidden; color: var(--wb-text-muted); font: 8px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.acg-copilot__composer-hint .el-icon { font-size: 10px; }
.acg-copilot__composer-actions { gap: 2px; }
.acg-copilot__send { color: var(--wb-accent) !important; background: var(--wb-accent-soft) !important; }
.acg-copilot__send:disabled { cursor: not-allowed; opacity: .4; }

@keyframes acg-copilot-bounce { 0%, 60%, 100% { opacity: .35; transform: translateY(0); } 30% { opacity: 1; transform: translateY(-3px); } }
@media (prefers-reduced-motion: reduce) { .acg-copilot__thinking i { animation: none; } }
@media (max-width: 340px) { .acg-copilot__mode { display: none; } .acg-copilot__context-details { gap: 6px; padding-left: 11px; } }
</style>
