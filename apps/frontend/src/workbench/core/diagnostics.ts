/**
 * 工作区诊断的共享状态：Problems 面板、状态栏角标、以及保存后的自动检查读同一份结果。
 * 单例 + Vue 响应式，保证面板和角标永远一致。
 */
import { computed, ref } from 'vue'
import { runWorkspaceDiagnostics, type WorkspaceDiagnosticsResult } from '@/services/workspaceDiagnostics'

const result = ref<WorkspaceDiagnosticsResult | null>(null)
const running = ref(false)
const error = ref('')
const currentRoot = ref('')

let generation = 0
let timer: number | undefined

const clearTimer = (): void => {
  if (timer !== undefined) {
    window.clearTimeout(timer)
    timer = undefined
  }
}

async function run(target = currentRoot.value): Promise<void> {
  if (!target) return
  const token = ++generation
  currentRoot.value = target
  running.value = true
  error.value = ''
  try {
    const next = await runWorkspaceDiagnostics(target)
    if (token !== generation) return
    result.value = next
  } catch (cause: any) {
    if (token !== generation) return
    error.value = cause?.message || '检查失败'
  } finally {
    if (token === generation) running.value = false
  }
}

/** 保存后自动检查：防抖；上一次已确认「没有可用检查器」的根目录不重复探测。 */
function schedule(target: string, delay = 1500): void {
  if (!target) return
  if (currentRoot.value === target && result.value?.engine === 'none') return
  clearTimer()
  timer = window.setTimeout(() => {
    timer = undefined
    void run(target)
  }, delay)
}

function clear(): void {
  clearTimer()
  generation += 1
  result.value = null
  error.value = ''
  running.value = false
}

function reset(): void {
  clear()
  currentRoot.value = ''
}

export const workspaceDiagnostics = {
  result: computed(() => result.value),
  running: computed(() => running.value),
  error: computed(() => error.value),
  root: computed(() => currentRoot.value),
  count: computed(() => result.value?.diagnostics.length ?? 0),
  run,
  schedule,
  clear,
  reset
}
