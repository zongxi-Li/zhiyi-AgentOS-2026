<template>
  <div class="companion-dialogue" data-testid="companion-dialogue">
    <div ref="messagesEl" class="companion-messages" data-testid="companion-messages" role="log" aria-live="polite" aria-label="对话字幕">
      <p v-if="!messages.length" class="companion-empty">说话或叫我的名字，回复也会显示在这里。</p>
      <div v-for="message in messages" :key="message.id" class="companion-msg" :class="`companion-msg--${message.role}`">{{ message.content }}</div>
    </div>
    <p v-if="pending" role="status" class="companion-empty">回复中…</p>

    <div v-if="card" class="companion-card" data-testid="companion-card">
      <span class="companion-card-title">任务意图卡</span>
      <span class="companion-card-body">{{ card.title }}</span>
      <span class="companion-card-note">{{ card.note }}</span>
      <button type="button" data-testid="companion-card-close" @click="emit('dismiss-card')">知道了</button>
    </div>

    <CompanionVoiceBar
      :phase="phase"
      :interim="interim"
      :hint="hint"
      :muted="muted"
      :level="level"
      @toggle="emit('toggle-voice')"
      @toggle-mute="emit('toggle-mute')"
    />
    <button type="button" class="companion-text-toggle" data-testid="companion-text-toggle" :aria-expanded="textOpen" @click="textOpen = !textOpen">{{ textOpen ? '收起文字输入' : '无法语音？改用文字' }}</button>
    <form v-if="textOpen" class="companion-text-form" @submit.prevent="submit">
      <input v-model="draft" data-testid="companion-input" aria-label="文字对话" placeholder="输入想说的话" maxlength="2000" />
      <button type="submit" :disabled="pending || !draft.trim()">发送</button>
    </form>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import CompanionVoiceBar from './CompanionVoiceBar.vue'
import type { VoicePhase } from '@/features/companion/voice'
import type { CompanionMessage, TaskIntentCard } from '@/features/companion/types'

const props = withDefaults(defineProps<{
  messages: CompanionMessage[]
  pending: boolean
  card: TaskIntentCard | null
  phase: VoicePhase
  hint: string
  interim?: string
  muted?: boolean
  level?: number
}>(), { interim: '', muted: false, level: 0.35 })

const emit = defineEmits<{
  (event: 'dismiss-card'): void
  (event: 'toggle-voice'): void
  (event: 'toggle-mute'): void
  (event: 'submit', text: string): void
}>()
const messagesEl = ref<HTMLElement | null>(null)
const textOpen = ref(false)
const draft = ref('')
const submit = () => {
  if (props.pending || !draft.value.trim()) return
  emit('submit', draft.value.trim())
  draft.value = ''
}
watch(() => props.messages[props.messages.length - 1]?.id, async () => {
  await nextTick()
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}, { immediate: true, flush: 'post' })
</script>

<style scoped>
.companion-dialogue { display: flex; flex-direction: column; gap: 8px; }
.companion-text-toggle { align-self: flex-start; font: inherit; font-size: 11px; color: var(--text-secondary); background: transparent; border: 0; cursor: pointer; }
.companion-text-form { display: flex; gap: 5px; }
.companion-text-form input { min-width: 0; flex: 1; }
.companion-text-form input, .companion-text-form button { font: inherit; font-size: 12px; padding: 6px; border-radius: 6px; color: var(--text-primary); background: var(--bg-input, var(--bg-card)); border: 1px solid var(--border-color-base); }
.companion-card button {
  font: inherit; font-size: 12px; padding: 4px 8px; cursor: pointer;
  color: var(--text-regular, var(--text-primary)); background: var(--bg-panel, var(--bg-card));
  border: 1px solid var(--border-color-base, rgba(128, 128, 128, 0.3)); border-radius: 6px;
  transition: background-color 180ms ease, transform 140ms ease;
}
.companion-messages {
  /* 随视口收缩，避免长对话把整块浮层顶出屏幕；下限保证仍可读。 */
  max-height: clamp(72px, 18vh, 190px); overflow-y: auto; display: flex; flex-direction: column; gap: 6px;
  padding: 8px; background: var(--bg-input, var(--bg-app)); border-radius: 8px;
}
.companion-empty { margin: 0; font-size: 12px; color: var(--text-muted, var(--text-secondary)); line-height: 1.6; }
.companion-msg { font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.companion-msg--user { align-self: flex-end; max-width: 86%; padding: 6px 9px; border-radius: 8px; background: var(--accent-fade, var(--primary-fade)); }
.companion-msg--companion { align-self: flex-start; max-width: 92%; color: var(--text-regular, var(--text-primary)); }
.companion-card { display: flex; flex-direction: column; gap: 4px; padding: 8px; border: 1px solid var(--border-color-base, rgba(128, 128, 128, 0.3)); border-radius: 8px; }
.companion-card-title { font-size: 12px; font-weight: 500; }
.companion-card-body { font-size: 13px; }
.companion-card-note { font-size: 11px; color: var(--text-muted, var(--text-secondary)); line-height: 1.5; }
.companion-card button { align-self: flex-start; }
@media (prefers-reduced-motion: reduce) { .companion-card button { transition: none; } }
</style>
