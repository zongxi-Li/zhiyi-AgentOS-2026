<template>
  <ol class="lifecycle-progress" aria-label="任务主流程">
    <li v-for="stage in lifecycleMainStages" :key="stage.phase" :aria-current="currentStage === stage.phase ? 'step' : undefined">
      <span class="lifecycle-progress__mark" aria-hidden="true" />
      <span>{{ stage.label }}</span>
    </li>
  </ol>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { lifecycleMainStages, lifecycleMainStage, type LifecyclePhase } from '@/features/workspace/runLifecycle'
const props = defineProps<{ phase: LifecyclePhase }>()
const currentStage = computed(() => lifecycleMainStage[props.phase])
</script>

<style scoped>
.lifecycle-progress { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 4px; margin: 0 0 14px; padding: 0; list-style: none; }
.lifecycle-progress li { position: relative; display: flex; flex-direction: column; align-items: center; gap: 7px; min-width: 0; color: var(--wb-text-muted); font-size: 10px; line-height: 1.5; white-space: nowrap; }
.lifecycle-progress li::before { position: absolute; top: 4px; left: calc(-50% - 2px); width: calc(100% + 4px); height: 1px; background: var(--wb-border-soft); content: ''; }
.lifecycle-progress li:first-child::before { display: none; }
.lifecycle-progress__mark { z-index: 1; box-sizing: border-box; width: 9px; height: 9px; border: 1px solid var(--wb-text-muted); border-radius: 50%; background: var(--wb-surface-1); }
.lifecycle-progress li[aria-current="step"] { color: var(--wb-accent); font-weight: 650; }
.lifecycle-progress li[aria-current="step"] .lifecycle-progress__mark { border-color: var(--wb-accent); background: var(--wb-accent); }
</style>
