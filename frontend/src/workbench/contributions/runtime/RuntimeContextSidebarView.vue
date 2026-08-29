<template>
  <div class="sidebar-view-stack">
    <InspectorSection v-if="hasStepSnapshot" title="步骤上下文" badge="projection">
      <InspectorPropertyList :rows="[
        { label: 'objective', value: context.entry?.objective },
        { label: 'dependencies', value: dependencyKeys.length }
      ]" />
      <div v-if="dependencyKeys.length" class="dependency-list">
        <code v-for="dependency in dependencyKeys" :key="dependency">{{ dependency }}</code>
      </div>
    </InspectorSection>

    <InspectorSection title="上下文数据" badge="未观测">
      <p class="sidebar-empty">未观测到 Context Pack、Memory 或 token context。</p>
    </InspectorSection>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import InspectorPropertyList from '@/components/workbench/InspectorPropertyList.vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'
import type { WorkbenchInspectorContext } from '@/workbench/types'

const props = defineProps<{ context: WorkbenchInspectorContext }>()
const dependencyKeys = computed(() => props.context.entry?.dependencyKeys || [])
const hasStepSnapshot = computed(() => Boolean(props.context.entry?.objective || dependencyKeys.value.length))
</script>

<style scoped>
.sidebar-view-stack { display: contents; }
.dependency-list { display: grid; gap: 5px; margin-top: 10px; }
.dependency-list code { overflow-wrap: anywhere; color: var(--wb-text); font: 10px/1.4 var(--font-mono, monospace); }
.sidebar-empty { margin: 0; color: var(--wb-text-muted); font-size: 11px; line-height: 1.6; }
</style>
