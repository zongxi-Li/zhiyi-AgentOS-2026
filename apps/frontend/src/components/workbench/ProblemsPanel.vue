<template>
  <section class="problems-panel" aria-label="Problems">
    <header class="problems-panel__intro">
      <strong>Problems</strong>
      <span class="problems-panel__intro-side">
        <span>{{ diagnostics.length }} problems · source projection</span>
        <button class="problems-panel__close" type="button" title="关闭运行面板" aria-label="关闭运行面板" @click="emit('close')">
          <el-icon aria-hidden="true"><Close /></el-icon>
        </button>
      </span>
    </header>
    <div v-if="!diagnostics.length" class="problems-panel__empty">
      <span class="problems-panel__empty-mark" aria-hidden="true">✓</span>
      <strong>没有问题</strong>
      <span>当前 Mission Projection 未报告诊断问题。</span>
    </div>
    <div v-else class="problems-panel__list">
      <article v-for="diagnostic in diagnostics" :key="`${diagnostic.code}-${diagnostic.message}`" class="problems-panel__item">
        <span class="problems-panel__severity" :class="`is-${diagnostic.severity}`" aria-hidden="true">!</span>
        <div>
          <strong>{{ diagnostic.code }}</strong>
          <p>{{ diagnostic.message }}</p>
          <small v-if="'source' in diagnostic">{{ diagnostic.source }}<span v-if="diagnostic.targetStepId"> · {{ diagnostic.targetStepId }}</span></small>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { Close } from '@element-plus/icons-vue'
import type { WorkspaceDiagnostic } from '@/services/api/agentos'
import type { RuntimeProblem } from '@/workbench/runtime/observation'

defineProps<{
  diagnostics: readonly (WorkspaceDiagnostic | RuntimeProblem)[]
}>()

// 与 Trace/Events 等运行面板一致：头部自带「关闭运行面板」，收起逻辑由底栏 setCollapsed 承接。
const emit = defineEmits<{ close: [] }>()
</script>

<style scoped>
.problems-panel { min-height: 100%; color: var(--wb-text-secondary); background: var(--wb-surface-1); }
.problems-panel__intro { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; min-height: 33px; box-sizing: border-box; padding: 8px 14px; }
.problems-panel__intro strong { color: var(--wb-text); font: 10px var(--font-mono, monospace); letter-spacing: .08em; text-transform: uppercase; }
.problems-panel__intro-side { display: inline-flex; align-items: center; gap: 8px; align-self: center; }
.problems-panel__intro-side span { color: var(--wb-text-muted); font-size: 10px; }
.problems-panel__close { display: inline-grid; place-items: center; width: 22px; height: 22px; padding: 0; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--wb-text-muted); font-size: 13px; line-height: 1; cursor: pointer; transition: background-color 140ms var(--ease-out, ease), color 140ms var(--ease-out, ease); }
.problems-panel__close:hover, .problems-panel__close:focus-visible { background: var(--wb-hover); color: var(--wb-accent); outline: none; }
.problems-panel__empty { display: grid; justify-items: center; gap: 5px; padding: 24px 16px; color: var(--wb-text-muted); font-size: 11px; text-align: center; }
.problems-panel__empty strong { color: var(--wb-text); font-size: 12px; }
.problems-panel__empty-mark { display: inline-grid; place-items: center; width: 21px; height: 21px; border: 1px solid color-mix(in srgb, var(--wb-success) 40%, var(--wb-border)); border-radius: 50%; color: var(--wb-success); font-size: 12px; }
.problems-panel__list { display: grid; align-content: start; }
.problems-panel__item { display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: 8px; padding: 9px 14px; border-bottom: 1px solid color-mix(in srgb, var(--wb-border) 72%, transparent); }
.problems-panel__severity { display: inline-grid; place-items: center; width: 17px; height: 17px; border-radius: 50%; color: var(--wb-surface-1); background: var(--wb-warning); font: 11px var(--font-mono, monospace); font-weight: 700; }
.problems-panel__severity.is-info { background: var(--wb-accent); }
.problems-panel__severity.is-error { background: var(--wb-danger); }
.problems-panel__item strong { color: var(--wb-text); font: 10px var(--font-mono, monospace); }
.problems-panel__item p { margin: 4px 0 0; color: var(--wb-text-secondary); font-size: 11px; line-height: 1.45; overflow-wrap: anywhere; }
.problems-panel__item small { display: block; margin-top: 4px; color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
</style>
