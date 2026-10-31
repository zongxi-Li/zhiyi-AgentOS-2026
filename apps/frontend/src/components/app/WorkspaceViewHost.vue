<template>
  <KeepAlive :max="1">
    <CachedWorkspaceView v-if="isChat" :key="chatKey" :view="view" :view-route="viewRoute" />
  </KeepAlive>
  <KeepAlive :max="1">
    <CachedWorkspaceView v-if="isMission" :key="`mission:${viewRoute.params.missionId}`" :view="view" :view-route="viewRoute" />
  </KeepAlive>
  <Transition name="shell-route">
    <component v-if="!isChat && !isMission" :is="view" :key="viewRoute.path" />
  </Transition>
</template>

<script setup lang="ts">
import { computed, ref, watch, type VNode } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import CachedWorkspaceView from './CachedWorkspaceView'

const props = defineProps<{ view: VNode; viewRoute: RouteLocationNormalizedLoaded }>()
const chat = useChatStore()
const isChat = computed(() => props.viewRoute.path === '/chat')
const isMission = computed(() => /^\/agentos\/missions\/[^/]+\/workspace$/.test(props.viewRoute.path))
let blankSequence = 0
const chatKey = ref('')
watch(() => props.viewRoute, (route, previous) => {
  if (route.path !== '/chat') return
  const context = typeof route.query.contextId === 'string' ? route.query.contextId : ''
  const draft = localStorage.getItem('chat.workflow_draft_conversation_id') || 'empty'
  if (route.query.newConversation === '1' && previous?.query.newConversation !== '1') {
    // ChatView alone creates the new Draft. A new cache slot consumes its intent
    // once; consuming the marker or receiving the first context never remounts it.
    chatKey.value = `chat:${draft}:new:${++blankSequence}`
  } else if (!chatKey.value || (context && context !== chat.contextId)) {
    chatKey.value = `chat:${context || chat.contextId || draft}`
  }
}, { immediate: true, flush: 'sync' })
</script>
