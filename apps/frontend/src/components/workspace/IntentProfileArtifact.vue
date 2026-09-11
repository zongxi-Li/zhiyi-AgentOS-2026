<template>
  <article class="intent-profile-artifact" aria-label="任务意图画像" data-testid="intent-profile-artifact">
    <header class="intent-profile-artifact__header">
      <div>
        <div class="intent-profile-artifact__eyebrow">PLANNING OUTPUT</div>
        <h2>任务意图画像</h2>
        <p>把 Mission 目标整理为可执行的约束、能力与交付物范围。</p>
      </div>
      <span class="intent-profile-artifact__status">
        <span class="intent-profile-artifact__status-dot" aria-hidden="true"></span>
        {{ statusLabel }}
      </span>
    </header>

    <section class="intent-profile-artifact__objective" aria-labelledby="intent-profile-objective-title">
      <div class="intent-profile-artifact__section-label" id="intent-profile-objective-title">OBJECTIVE</div>
      <p>{{ missionGoal }}</p>
    </section>

    <section class="intent-profile-artifact__facts" aria-labelledby="intent-profile-facts-title">
      <div class="intent-profile-artifact__section-heading">
        <div class="intent-profile-artifact__section-label" id="intent-profile-facts-title">STRUCTURED FACTS</div>
        <span>已从运行事件确认</span>
      </div>
      <div class="intent-profile-artifact__metrics">
        <div v-for="metric in metrics" :key="metric.key" class="intent-profile-artifact__metric">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <small>{{ metric.description }}</small>
        </div>
      </div>
    </section>

    <section class="intent-profile-artifact__downstream" aria-labelledby="intent-profile-downstream-title">
      <div class="intent-profile-artifact__section-label" id="intent-profile-downstream-title">DOWNSTREAM USE</div>
      <div class="intent-profile-artifact__pipeline">
        <span>Task Plan</span>
        <span class="intent-profile-artifact__arrow" aria-hidden="true">→</span>
        <span>ACG</span>
        <span class="intent-profile-artifact__arrow" aria-hidden="true">→</span>
        <span>Execution</span>
      </div>
      <p>画像结果会作为任务规划、图谱编译和后续执行的输入。</p>
    </section>

    <footer class="intent-profile-artifact__footer">
      <span>RUN {{ runId || '—' }}</span>
      <span>·</span>
      <span>{{ symbol.status === 'completed' ? 'profile.resolved' : 'profile.pending' }}</span>
    </footer>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RunDocumentSymbol } from '@/workbench/runtime/runDocument'

const props = defineProps<{
  symbol: RunDocumentSymbol
  missionGoal: string
  runId: string | null
  profile?: Record<string, any> | null
}>()

const valueFor = (key: string) => {
  const value = props.symbol.metrics?.[key] ?? props.profile?.[key]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

const metrics = computed(() => [
  { key: 'constraintCount', label: '约束', value: valueFor('constraintCount'), description: '需要持续满足的条件' },
  { key: 'requiredCapabilityCount', label: '所需能力', value: valueFor('requiredCapabilityCount'), description: '规划阶段识别的能力' },
  { key: 'expectedArtifactCount', label: '预期产物', value: valueFor('expectedArtifactCount'), description: '后续需要交付的结果' }
])

const statusLabel = computed(() => props.symbol.status === 'completed' ? '已解析' : props.symbol.status === 'failed' ? '解析失败' : '解析中')
</script>

<style scoped>
.intent-profile-artifact { min-height: 100%; padding: 24px 20px 28px; color: var(--wb-text); }
.intent-profile-artifact__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding-bottom: 22px; border-bottom: 1px solid var(--wb-border-soft); }
.intent-profile-artifact__eyebrow, .intent-profile-artifact__section-label { color: var(--wb-accent); font: 11px var(--font-mono, monospace); letter-spacing: .1em; }
.intent-profile-artifact h2 { margin: 7px 0 5px; font-size: 20px; line-height: 1.3; }
.intent-profile-artifact p { margin: 0; color: var(--wb-text-secondary); font-size: 13px; line-height: 1.6; }
.intent-profile-artifact__status { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 7px; padding: 5px 9px; border: 1px solid color-mix(in srgb, var(--wb-success) 35%, var(--wb-border)); border-radius: var(--wb-radius-sm); color: var(--wb-success); font: 11px var(--font-mono, monospace); }
.intent-profile-artifact__status-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.intent-profile-artifact__objective { margin-top: 22px; padding: 15px 16px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); background: var(--wb-surface-inset); }
.intent-profile-artifact__objective p { margin-top: 9px; color: var(--wb-text); font-size: 14px; line-height: 1.65; }
.intent-profile-artifact__facts { margin-top: 24px; }
.intent-profile-artifact__section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.intent-profile-artifact__section-heading > span { color: var(--wb-text-muted); font: 11px var(--font-mono, monospace); }
.intent-profile-artifact__metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 10px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); overflow: hidden; }
.intent-profile-artifact__metric { min-width: 0; padding: 14px 12px; background: var(--wb-surface-2); }
.intent-profile-artifact__metric + .intent-profile-artifact__metric { border-left: 1px solid var(--wb-border-soft); }
.intent-profile-artifact__metric span, .intent-profile-artifact__metric small { display: block; color: var(--wb-text-muted); font-size: 12px; }
.intent-profile-artifact__metric strong { display: block; margin: 7px 0 4px; color: var(--wb-text); font-size: 22px; line-height: 1; }
.intent-profile-artifact__metric small { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.intent-profile-artifact__downstream { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--wb-border-soft); }
.intent-profile-artifact__pipeline { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; margin: 12px 0 8px; }
.intent-profile-artifact__pipeline span:not(.intent-profile-artifact__arrow) { padding: 5px 8px; border: 1px solid color-mix(in srgb, var(--wb-accent) 28%, var(--wb-border)); border-radius: var(--wb-radius-sm); color: var(--wb-text-secondary); background: var(--wb-accent-soft); font-size: 12px; }
.intent-profile-artifact__arrow { color: var(--wb-text-muted); font: 13px var(--font-mono, monospace); }
.intent-profile-artifact__footer { display: flex; gap: 7px; margin-top: 26px; color: var(--wb-text-muted); font: 11px var(--font-mono, monospace); }
@media (max-width: 760px) {
  .intent-profile-artifact__metrics { grid-template-columns: 1fr; }
  .intent-profile-artifact__metric + .intent-profile-artifact__metric { border-top: 1px solid var(--wb-border-soft); border-left: 0; }
}
</style>
