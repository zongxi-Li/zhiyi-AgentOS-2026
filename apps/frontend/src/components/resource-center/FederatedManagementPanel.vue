<template>
  <section class="federated-management-panel" data-testid="federated-management-panel" aria-label="联邦管理">
    <FederatedLearningPanel />
  </section>
</template>

<script setup lang="ts">
import FederatedLearningPanel from '@/components/federated/FederatedLearningPanel.vue'
</script>

<style scoped>
.federated-management-panel { min-width: 0; }
.federated-management-panel :deep(.federated-panel) { width: 100%; }
</style>
