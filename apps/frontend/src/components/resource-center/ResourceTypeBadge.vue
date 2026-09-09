<template>
  <span class="resource-type-badge" :style="badgeStyle">{{ meta.label }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { resourceTypeMeta } from '@/utils/resourceFormat'

const props = defineProps<{ type: string | null | undefined }>()

const meta = computed(() => resourceTypeMeta(props.type))
const badgeStyle = computed(() => ({
  color: meta.value.tone,
  background: `color-mix(in srgb, ${meta.value.tone} 12%, transparent)`
}))
</script>

<style scoped>
.resource-type-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  font-style: normal;
  font-size: 9px;
  line-height: 1.5;
  white-space: nowrap;
}
</style>
