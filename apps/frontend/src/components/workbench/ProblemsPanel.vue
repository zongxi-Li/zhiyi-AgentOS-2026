<template>
  <section class="problems-panel" aria-label="Problems">
    <header class="problems-panel__intro">
      <strong>Problems</strong>
      <span class="problems-panel__intro-side">
        <span>{{ rows.length }} problems<template v-if="toolResult"> · {{ toolResult.engine }}</template></span>
        <button
          class="problems-panel__run"
          type="button"
          :disabled="running || !root"
          :title="root ? '用项目自己的工具链检查一次' : '正在定位工作区'"
          @click="runChecks"
        >{{ running ? '检查中…' : '运行检查' }}</button>
        <button class="problems-panel__close" type="button" title="关闭运行面板" aria-label="关闭运行面板" @click="emit('close')">
          <el-icon aria-hidden="true"><Close /></el-icon>
        </button>
      </span>
    </header>

    <p v-if="error" class="problems-panel__error" role="alert">{{ error }}</p>

    <div v-if="!rows.length" class="problems-panel__empty">
      <span class="problems-panel__empty-mark" aria-hidden="true">✓</span>
      <strong>没有发现问题</strong>
      <span>{{ toolResult ? `${toolResult.message || '检查完成'}，未报告问题。` : 'Mission Projection 未报告诊断问题；可运行一次静态检查。' }}</span>
    </div>

    <div v-else class="problems-panel__list">
      <article v-for="row in rows" :key="row.key" class="problems-panel__item">
        <span class="problems-panel__severity" :class="`is-${row.severity}`" aria-hidden="true">!</span>
        <div>
          <button
            v-if="row.path"
            class="problems-panel__location"
            type="button"
            :title="`打开 ${row.path}:${row.line}`"
            @click="openProblem(row)"
          >{{ row.path }}<span v-if="row.line">:{{ row.line }}<span v-if="row.column">:{{ row.column }}</span></span></button>
          <strong>{{ row.code }}</strong>
          <p>{{ row.message }}</p>
          <small v-if="row.source">{{ row.source }}</small>
        </div>
      </article>
    </div>

    <footer v-if="toolResult" class="problems-panel__meta">
      {{ toolResult.message || '检查完成' }} · {{ toolResult.durationMs }}ms<span v-if="toolResult.truncated">（已截断）</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { agentosApi, type WorkspaceDiagnostic } from '@/services/api/agentos'
import { workspaceDiagnostics } from '@/workbench/core/diagnostics'
import { getElectronBridge } from '@/platform/electron/bridge'
import { requestReveal } from '@/workbench/core/reveal'
import type { RuntimeProblem } from '@/workbench/runtime/observation'

interface ProblemRow {
  key: string
  severity: 'error' | 'warning' | 'info'
  code: string
  message: string
  source?: string
  path?: string
  line?: number
  column?: number
}

const props = defineProps<{
  diagnostics: readonly (WorkspaceDiagnostic | RuntimeProblem)[]
  missionId?: string
}>()

// 与 Trace/Events 等运行面板一致：头部自带「关闭运行面板」，收起逻辑由底栏 setCollapsed 承接。
const emit = defineEmits<{ close: []; 'open-file': [request: Record<string, unknown>] }>()

const running = computed(() => workspaceDiagnostics.running.value)
const localError = ref('')
const error = computed(() => localError.value || workspaceDiagnostics.error.value)
const toolResult = computed(() => workspaceDiagnostics.result.value)
const root = ref('')
const workspaceId = ref<string | null>(null)

const projectionRows = computed<ProblemRow[]>(() => props.diagnostics.map((diagnostic, index) => ({
  key: `projection-${index}-${diagnostic.code}`,
  severity: diagnostic.severity,
  code: diagnostic.code,
  message: diagnostic.message,
  source: (diagnostic as { source?: string }).source
})))

const toolRows = computed<ProblemRow[]>(() => (toolResult.value?.diagnostics || []).map((item, index) => ({
  key: `tool-${index}-${item.path}-${item.line}-${item.code}`,
  severity: item.severity,
  code: item.code,
  message: item.message,
  source: `${item.source} · ${item.path}`,
  path: item.path,
  line: item.line,
  column: item.column
})))

const rows = computed(() => [...toolRows.value, ...projectionRows.value])

const messageOf = (cause: any) => cause?.message || '检查失败'

async function resolveRoot(): Promise<void> {
  try {
    const folder = await getElectronBridge()?.workspace?.current?.()
    if (folder) {
      root.value = folder.root
      workspaceId.value = folder.id
      return
    }
    if (props.missionId) {
      const listing = await agentosApi.listWorkspaceFiles(props.missionId, '.')
      root.value = listing.workspaceRoot
    }
  } catch (cause) {
    localError.value = messageOf(cause)
  }
}

async function runChecks(): Promise<void> {
  if (!root.value || running.value) return
  await workspaceDiagnostics.run(root.value)
}

function openProblem(row: ProblemRow): void {
  if (!row.path || !row.line) return
  requestReveal(row.path, row.line)
  emit('open-file', {
    missionId: props.missionId || '',
    workspaceRoot: root.value,
    relativePath: row.path,
    name: row.path.split('/').pop() || row.path,
    ...(workspaceId.value ? { desktopWorkspaceId: workspaceId.value } : {})
  })
}

onMounted(async () => {
  await resolveRoot()
  // 换工作区后旧结果不再适用，避免把上一个目录的问题显示出来。
  if (root.value && workspaceDiagnostics.root.value && workspaceDiagnostics.root.value !== root.value) {
    workspaceDiagnostics.clear()
  }
})
</script>

<style scoped>
.problems-panel { min-height: 100%; color: var(--wb-text-secondary); background: var(--wb-surface-1); }
.problems-panel__intro { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; min-height: 33px; box-sizing: border-box; padding: 8px 14px; }
.problems-panel__intro strong { color: var(--wb-text); font: 10px var(--font-mono, monospace); letter-spacing: .08em; text-transform: uppercase; }
.problems-panel__intro-side { display: inline-flex; align-items: center; gap: 8px; align-self: center; }
.problems-panel__intro-side span { color: var(--wb-text-muted); font-size: 10px; }
.problems-panel__run { padding: 2px 8px; border: 1px solid var(--wb-border-strong); border-radius: 4px; background: var(--wb-surface-0, transparent); color: var(--wb-text-secondary); font-size: 10.5px; cursor: pointer; }
.problems-panel__run:hover:not(:disabled), .problems-panel__run:focus-visible { color: var(--wb-text); background: var(--wb-hover); outline: none; }
.problems-panel__run:disabled { opacity: .5; cursor: default; }
.problems-panel__close { display: inline-grid; place-items: center; width: 22px; height: 22px; padding: 0; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--wb-text-muted); font-size: 13px; line-height: 1; cursor: pointer; transition: background-color 140ms var(--ease-out, ease), color 140ms var(--ease-out, ease); }
.problems-panel__close:hover, .problems-panel__close:focus-visible { background: var(--wb-hover); color: var(--wb-accent); outline: none; }
.problems-panel__error { margin: 0; padding: 6px 14px; color: var(--wb-danger); font-size: 11px; }
.problems-panel__empty { display: grid; justify-items: center; gap: 5px; padding: 24px 16px; color: var(--wb-text-muted); font-size: 11px; text-align: center; }
.problems-panel__empty strong { color: var(--wb-text); font-size: 12px; }
.problems-panel__empty-mark { display: inline-grid; place-items: center; width: 21px; height: 21px; border: 1px solid color-mix(in srgb, var(--wb-success) 40%, var(--wb-border)); border-radius: 50%; color: var(--wb-success); font-size: 12px; }
.problems-panel__list { display: grid; align-content: start; }
.problems-panel__item { display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: 8px; padding: 9px 14px; border-bottom: 1px solid color-mix(in srgb, var(--wb-border) 72%, transparent); }
.problems-panel__severity { display: inline-grid; place-items: center; width: 17px; height: 17px; border-radius: 50%; color: var(--wb-surface-1); background: var(--wb-warning); font: 11px var(--font-mono, monospace); font-weight: 700; }
.problems-panel__severity.is-info { background: var(--wb-accent); }
.problems-panel__severity.is-error { background: var(--wb-danger); }
.problems-panel__location { display: block; padding: 0; border: 0; background: transparent; color: var(--wb-accent); font: 10.5px var(--font-mono, monospace); text-align: left; cursor: pointer; }
.problems-panel__location:hover, .problems-panel__location:focus-visible { text-decoration: underline; outline: none; }
.problems-panel__item strong { color: var(--wb-text); font: 10px var(--font-mono, monospace); }
.problems-panel__item p { margin: 4px 0 0; color: var(--wb-text-secondary); font-size: 11px; line-height: 1.45; overflow-wrap: anywhere; }
.problems-panel__item small { display: block; margin-top: 4px; color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
.problems-panel__meta { padding: 6px 14px; border-top: 1px solid var(--wb-border); color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
</style>
