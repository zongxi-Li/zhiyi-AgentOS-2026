<template>
  <component
    v-if="contribution"
    :is="contribution.component"
    v-bind="{ ...componentProps, ...$attrs }"
  />
</template>

<script setup lang="ts">
import type { Component } from 'vue'

defineOptions({ inheritAttrs: false })

defineProps<{
  contribution: { component: Component } | null
  componentProps?: Record<string, unknown>
}>()
</script>
