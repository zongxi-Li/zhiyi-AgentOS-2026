<template>
  <div
    ref="root"
    class="agent-constellation"
    :class="{ 'is-controls-open': controlsExpanded, 'is-hovered': isHovered, 'is-pressed': isPressed }"
    data-testid="glass-constellation"
    :data-voice-state="voiceState"
    :style="avatarStyle"
    role="group"
    aria-label="知弈 Agent 角色控制"
    @pointerenter="handlePointerEnter"
    @pointermove="handlePointerMove"
    @pointerleave="handlePointerLeave"
    @keydown.esc="controlsExpanded = false"
  >
    <div class="agent-stage" :class="[`agent-stage--${action}`, `agent-stage--${shape.id}`, { 'agent-stage--listening': isListening, 'agent-stage--awake': isAwake }]">
      <div class="agent-stage__halo" aria-hidden="true"></div>
      <div class="agent-stage__orbit-light" aria-hidden="true"></div>

      <button
        class="agent-avatar-trigger"
        data-testid="agent-avatar-trigger"
        type="button"
        :aria-expanded="controlsExpanded"
        aria-controls="agent-control-dock"
        :aria-label="controlsExpanded ? '收起 Agent 控制台' : '打开 Agent 控制台'"
        @click="toggleControls"
        @pointerdown="isPressed = true"
        @pointerup="isPressed = false"
        @pointercancel="isPressed = false"
      >
        <svg
          class="agent-avatar"
          data-testid="agent-avatar"
          viewBox="-15 -15 259 259"
          role="img"
          :aria-label="`知弈 Agent，${color.label}${shape.label}，当前${actionLabel}`"
        >
          <defs>
            <linearGradient :id="gradientIds.body" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="var(--agent-light)" />
            <stop offset="0.38" stop-color="var(--agent-main)" />
            <stop offset="0.7" stop-color="color-mix(in srgb, var(--agent-main) 72%, var(--agent-deep))" />
            <stop offset="1" stop-color="var(--agent-deep)" />
            </linearGradient>
            <radialGradient :id="gradientIds.gloss" cx="28%" cy="18%" r="82%">
              <stop offset="0" stop-color="#ffffff" stop-opacity="0.94" />
              <stop offset="0.18" stop-color="#ffffff" stop-opacity="0.3" />
              <stop offset="0.48" stop-color="var(--agent-glow)" stop-opacity="0.08" />
              <stop offset="1" stop-color="#ffffff" stop-opacity="0" />
            </radialGradient>
            <linearGradient :id="gradientIds.rim" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stop-color="#ffffff" stop-opacity="0.96" />
              <stop offset="0.36" stop-color="var(--agent-glow)" stop-opacity="0.72" />
              <stop offset="1" stop-color="var(--agent-deep)" stop-opacity="0.28" />
            </linearGradient>
            <filter :id="gradientIds.volume" x="-30%" y="-30%" width="160%" height="180%" color-interpolation-filters="sRGB">
              <feGaussianBlur in="SourceAlpha" stdDeviation="6" result="blur" />
              <feOffset dy="5" result="offsetBlur" />
              <feFlood flood-color="#122868" flood-opacity="0.3" result="shade" />
              <feComposite in="shade" in2="offsetBlur" operator="in" result="shadow" />
              <feComposite in="SourceGraphic" in2="shadow" operator="over" />
            </filter>
          </defs>

          <ellipse class="agent-avatar__shadow" cx="0" cy="104" rx="62" ry="10" :transform="customTransform" />
          <g v-if="shapeBeforePath" class="agent-avatar__shape-layer agent-avatar__shape-layer--leaving" :transform="shapeBeforeTransform">
            <path class="agent-avatar__body agent-avatar__body--leaving" :d="shapeBeforePath" :fill="`url(#${gradientIds.body})`" />
          </g>
          <g class="agent-avatar__shape-layer" :transform="shape.transform">
            <path class="agent-avatar__body" :class="{ 'is-changing': shapePulse }" :d="shape.path" :fill="`url(#${gradientIds.body})`" :filter="`url(#${gradientIds.volume})`" />
            <path class="agent-avatar__gloss" :d="shape.path" :fill="`url(#${gradientIds.gloss})`" />
            <g :transform="shape.id === 'blob' ? customTransform : undefined">
              <ellipse class="agent-avatar__specular" cx="-42" cy="-55" rx="20" ry="9" transform="rotate(-28 -42 -55)" />
            </g>
          </g>

          <g class="agent-avatar__face-shell">
            <g class="agent-avatar__face" :style="gazeStyle">
              <template v-if="shape.id === 'blob'">
                <g :transform="referenceTransform">
                  <path class="agent-avatar__eye agent-avatar__reference-eye" :d="referenceEyePaths.left" />
                  <path class="agent-avatar__eye agent-avatar__reference-eye" :d="referenceEyePaths.right" />
                  <circle class="agent-avatar__eye-glint" cx="139" cy="66" r="4" />
                  <circle class="agent-avatar__eye-glint" cx="182" cy="59" r="4" />
                </g>
              </template>
              <template v-else>
                <ellipse class="agent-avatar__eye" cx="-38" cy="0" rx="15" ry="24" :transform="customTransform" />
                <ellipse class="agent-avatar__eye" cx="38" cy="0" rx="15" ry="24" :transform="customTransform" />
                <circle class="agent-avatar__eye-glint" cx="-34" cy="-7" r="4" :transform="customTransform" />
                <circle class="agent-avatar__eye-glint" cx="42" cy="-7" r="4" :transform="customTransform" />
              </template>
            </g>
          </g>
          <g :transform="customTransform">
            <circle class="agent-avatar__spark" cx="-76" cy="-70" r="4" />
            <g transform="translate(75 -58) scale(7)">
              <path class="agent-avatar__spark agent-avatar__star" :d="referenceStarPath" />
            </g>
          </g>
        </svg>
      </button>

      <div class="agent-stage__prompt" aria-hidden="true">{{ controlsExpanded ? '控制台已展开' : '点击唤醒控制台' }}</div>
      <div class="agent-stage__status" aria-live="polite">
        <span class="agent-stage__status-dot"></span>
        <span>{{ actionLabel }}</span>
      </div>
    </div>

    <div id="agent-control-dock" data-testid="agent-controls" class="agent-controls" :class="{ 'is-open': controlsExpanded }" :aria-hidden="!controlsExpanded" aria-label="Agent 动效控制" @click.stop>
      <div class="agent-controls__line">
        <span class="agent-controls__label">SHAPE</span>
        <button
          v-for="item in shapes"
          :key="item.id"
          class="agent-control agent-control--shape"
          data-testid="agent-shape-option"
          type="button"
          :aria-label="`切换为${item.label}`"
          :aria-pressed="shape.id === item.id"
          @click="setShape(item.id)"
        >
          <span class="agent-control__shape-mark" :class="`agent-control__shape-mark--${item.id}`"></span>
          <span>{{ item.label }}</span>
        </button>
      </div>

      <div class="agent-controls__line agent-controls__line--actions">
        <span class="agent-controls__label">MOOD</span>
        <button
          v-for="item in actions"
          :key="item.id"
          class="agent-control"
          data-testid="agent-action-option"
          type="button"
          :aria-pressed="action === item.id"
          @click="triggerAction(item.id)"
        >{{ item.label }}</button>
        <button
          class="agent-control agent-control--voice"
          data-testid="agent-voice-toggle"
          type="button"
          :class="{ 'is-listening': isListening }"
          :aria-pressed="isListening"
          :aria-label="isListening ? '停止语音交互' : '开始语音交互'"
          @click="toggleVoice"
        >
          <Microphone aria-hidden="true" />
          <span>{{ isListening ? (isAwake ? '已唤醒' : '守候中') : '语音' }}</span>
        </button>
      </div>

      <div class="agent-controls__line agent-controls__line--colors">
        <span class="agent-controls__label">COLOR</span>
        <button
          v-for="item in palettes"
          :key="item.id"
          class="agent-color"
          data-testid="agent-color-option"
          type="button"
          :style="{ '--swatch': item.main }"
          :aria-label="`切换为${item.label}`"
          :aria-pressed="color.id === item.id"
          @click="setColor(item.id)"
        ></button>
        <span class="agent-controls__hint">{{ voiceStatus }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, getCurrentInstance, onBeforeUnmount, reactive, ref } from 'vue'
import { Microphone } from '@element-plus/icons-vue'

type ShapeId = 'blob' | 'orb' | 'capsule' | 'prism'
type ActionId = 'idle' | 'curious' | 'thinking' | 'celebrate' | 'spin' | 'bounce' | 'sway' | 'surprise' | 'playful'
type Shape = { id: ShapeId; label: string; path: string; transform?: string }
type Palette = { id: string; label: string; main: string; deep: string; light: string; glow: string; keys: string[] }

const referenceTransform = undefined
const customTransform = 'translate(114.2705 114.228)'
const referenceBlobPath = 'M228.541 114.228C228.541 130.133 225.184 145.994 218.738 160.534C212.674 174.217 203.904 186.669 193.065 196.988C155.933 232.34 99.497 238.596 55.5255 212.24C45.097 205.99 35.6851 198.072 27.7451 188.866C19.1926 178.953 12.3686 167.569 7.65781 155.351C2.60712 142.264 0 128.257 0 114.228C0 98.3219 3.35751 82.4611 9.80315 67.9215C15.8672 54.2382 24.6377 41.7862 35.4767 31.4668C72.6081 -3.88483 129.044 -10.1413 173.016 16.2153C183.444 22.4653 192.856 30.3829 200.796 39.5896C209.349 49.5018 216.173 60.8859 220.883 73.1037C225.934 86.1906 228.541 100.198 228.541 114.228Z'
const referenceEyePaths = {
  left: 'M130.36 45.98L132.71 46.19L134.98 46.81L137.11 47.83L138.97 49.28L140.47 51.09L141.68 53.12L142.73 55.23L143.76 57.36L144.78 59.49L145.79 61.62L146.79 63.76L147.76 65.91L148.71 68.07L149.63 70.25L150.52 72.43L151.37 74.63L151.99 76.91L152.1 79.26L151.64 81.57L150.59 83.68L149.04 85.45L147.1 86.78L144.9 87.62L142.56 87.93L140.22 87.71L137.98 86.99L135.93 85.82L134.17 84.24L132.78 82.34L131.69 80.25L130.77 78.08L129.87 75.89L128.94 73.72L128 71.56L127.03 69.4L126.05 67.26L125.05 65.12L124.03 62.99L122.93 60.9L121.87 58.79L121.03 56.59L120.72 54.26L121.1 51.93L122.15 49.83L123.75 48.1L125.76 46.89L128.01 46.19Z',
  right: 'M176.61 37.08L178.72 37.59L180.7 38.48L182.52 39.65L184.2 41.03L185.71 42.59L187.03 44.31L188.2 46.14L189.26 48.03L190.27 49.96L191.26 51.89L192.23 53.84L193.16 55.8L194.05 57.78L194.92 59.77L195.74 61.78L196.53 63.8L197.27 65.84L197.97 67.9L198.47 70.01L198.63 72.18L198.4 74.33L197.58 76.33L195.95 77.72L193.83 78.08L191.71 77.65L189.76 76.69L188.03 75.38L186.53 73.82L185.28 72.05L184.25 70.13L183.4 68.14L182.63 66.11L181.87 64.07L181.07 62.05L180.25 60.04L179.39 58.05L178.49 56.07L177.57 54.1L176.61 52.15L175.62 50.22L174.59 48.31L173.53 46.41L172.54 44.48L171.86 42.42L171.76 40.26L172.62 38.3L174.45 37.19Z'
}
const referenceStarPath = 'M0.000 -1.000L0.247 -0.340L0.951 -0.309L0.399 0.130L0.588 0.809L0.000 0.420L-0.588 0.809L-0.399 0.130L-0.951 -0.309L-0.247 -0.340Z'

const shapes: readonly Shape[] = [
  { id: 'blob', label: '流体', path: referenceBlobPath, transform: referenceTransform },
  { id: 'orb', label: '圆团', path: 'M 0 -94 C 53 -94 94 -53 94 0 C 94 53 53 94 0 94 C -53 94 -94 53 -94 0 C -94 -53 -53 -94 0 -94 Z', transform: customTransform },
  { id: 'capsule', label: '胶囊', path: 'M 0 -102 C 49 -102 75 -65 75 0 C 75 65 49 102 0 102 C -49 102 -75 65 -75 0 C -75 -65 -49 -102 0 -102 Z', transform: customTransform },
  { id: 'prism', label: '棱面', path: 'M 0 -106 L 76 -45 L 83 34 L 0 103 L -83 34 L -76 -45 Z', transform: customTransform }
]

const actions: readonly { id: Exclude<ActionId, 'idle'>; label: string }[] = [
  { id: 'curious', label: '好奇' },
  { id: 'thinking', label: '思考' },
  { id: 'celebrate', label: '庆祝' },
  { id: 'spin', label: '旋转' },
  { id: 'bounce', label: '弹跳' },
  { id: 'sway', label: '摇摆' },
  { id: 'surprise', label: '惊讶' },
  { id: 'playful', label: '俏皮' }
]

const palettes: readonly Palette[] = [
  { id: 'cyan', label: '澄蓝', main: '#1CC3B0', deep: '#007769', light: '#D5FFFA', glow: '#54F8E5', keys: ['蓝', '青', 'cyan', 'blue'] },
  { id: 'violet', label: '紫晶', main: '#A97EFE', deep: '#5C39A1', light: '#F1E8FF', glow: '#CDB6FF', keys: ['紫', '紫色', 'violet', 'purple'] },
  { id: 'mint', label: '薄荷', main: '#00C972', deep: '#008048', light: '#D9FFED', glow: '#7BFFC7', keys: ['绿', '薄荷', 'mint', 'green'] },
  { id: 'coral', label: '珊瑚', main: '#FF5EB1', deep: '#A21E62', light: '#FFF0F8', glow: '#FF9BCF', keys: ['红', '粉', '珊瑚', 'coral', 'pink'] }
]

const root = ref<HTMLElement | null>(null)
const currentShape = ref<ShapeId>('blob')
const currentColor = ref('cyan')
const action = ref<ActionId>('idle')
const shapePulse = ref(false)
const shapeBeforePath = ref<string | null>(null)
const shapeBeforeTransform = ref<string | undefined>(undefined)
const controlsExpanded = ref(false)
const isHovered = ref(false)
const isPressed = ref(false)
const isListening = ref(false)
const isAwake = ref(false)
const transcript = ref('')
const gaze = reactive({ x: 0, y: 0, tiltX: 0, tiltY: 0 })
let actionTimer: number | undefined
let shapeTimer: number | undefined
let voiceRestartTimer: number | undefined

const componentUid = getCurrentInstance()?.uid ?? 'main'
const gradientIds = {
  body: `agent-body-gradient-${componentUid}`,
  gloss: `agent-gloss-gradient-${componentUid}`,
  rim: `agent-rim-gradient-${componentUid}`,
  volume: `agent-volume-filter-${componentUid}`
}

interface SpeechResultEvent { resultIndex?: number; results: ArrayLike<ArrayLike<{ transcript: string; isFinal?: boolean }>> }
interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: SpeechResultEvent) => void) | null
  onerror: (() => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
}
type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

const shape = computed(() => shapes.find(item => item.id === currentShape.value) || shapes[0])
const color = computed(() => palettes.find(item => item.id === currentColor.value) || palettes[0])
const actionLabel = computed(() => ({
  idle: '待机', curious: '好奇探索', thinking: '思考中', celebrate: '庆祝', spin: '旋转中',
  bounce: '弹跳中', sway: '摇摆中', surprise: '惊讶', playful: '俏皮'
})[action.value])
const voiceStatus = computed(() => {
  if (isListening.value && !isAwake.value) return '语音守候中 · 说 “Justin” 唤醒对话'
  if (isListening.value && isAwake.value) return 'Justin 已唤醒 · 请说出颜色、形状或动作'
  if (transcript.value) return `识别：${transcript.value}`
  return '点击语音，或说 “Justin” 开始对话'
})
const voiceState = computed(() => isAwake.value ? 'awake' : isListening.value ? 'waiting' : 'idle')
const avatarStyle = computed(() => ({
  '--agent-main': color.value.main,
  '--agent-deep': color.value.deep,
  '--agent-light': color.value.light,
  '--agent-glow': color.value.glow,
  '--agent-tilt-x': `${gaze.tiltX}deg`,
  '--agent-tilt-y': `${gaze.tiltY}deg`
}) as Record<string, string>)
const gazeStyle = computed(() => ({ transform: `translate(${gaze.x}px, ${gaze.y}px)` }))

const toggleControls = () => {
  controlsExpanded.value = !controlsExpanded.value
  if (controlsExpanded.value) triggerAction('curious')
}

const triggerAction = (nextAction: ActionId) => {
  window.clearTimeout(actionTimer)
  action.value = nextAction
  if (nextAction !== 'idle' && nextAction !== 'thinking') {
    const duration = nextAction === 'spin' ? 1250 : nextAction === 'celebrate' ? 1750 : nextAction === 'bounce' ? 1300 : nextAction === 'sway' ? 1450 : nextAction === 'surprise' ? 1050 : 1650
    actionTimer = window.setTimeout(() => { action.value = 'idle' }, duration)
  }
}

const setShape = (nextShape: ShapeId) => {
  if (nextShape === currentShape.value) return
  shapeBeforePath.value = shape.value.path
  shapeBeforeTransform.value = shape.value.transform
  currentShape.value = nextShape
  shapePulse.value = true
  window.clearTimeout(shapeTimer)
  shapeTimer = window.setTimeout(() => {
    shapePulse.value = false
    shapeBeforePath.value = null
    shapeBeforeTransform.value = undefined
  }, 420)
  triggerAction('curious')
}

const setColor = (nextColor: string) => {
  if (palettes.some(item => item.id === nextColor)) currentColor.value = nextColor
}

const handlePointerMove = (event: PointerEvent) => {
  if (!root.value) return
  const rect = root.value.getBoundingClientRect()
  gaze.x = Math.max(-10, Math.min(10, ((event.clientX - rect.left) / rect.width - 0.5) * 18))
  gaze.y = Math.max(-8, Math.min(8, ((event.clientY - rect.top) / rect.height - 0.5) * 12))
  gaze.tiltX = Math.max(-3.2, Math.min(3.2, gaze.x * 0.24))
  gaze.tiltY = Math.max(-2.4, Math.min(2.4, gaze.y * -0.22))
}

const handlePointerEnter = () => { isHovered.value = true }
const handlePointerLeave = () => {
  isHovered.value = false
  gaze.x = 0
  gaze.y = 0
  gaze.tiltX = 0
  gaze.tiltY = 0
  isPressed.value = false
}

const recognitionConstructor = () => {
  const speechWindow = window as Window & { SpeechRecognition?: SpeechRecognitionConstructor; webkitSpeechRecognition?: SpeechRecognitionConstructor }
  return speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition
}

const applyVoiceCommand = (rawCommand: string) => {
  const command = rawCommand.toLowerCase()
  const nextPalette = palettes.find(item => item.keys.some(key => command.includes(key)))
  if (nextPalette) setColor(nextPalette.id)

  const nextShape = shapes.find(item =>
    (item.id === 'blob' && /流体|团|blob/.test(command)) ||
    (item.id === 'orb' && /圆|球|orb/.test(command)) ||
    (item.id === 'capsule' && /胶囊|长条|capsule/.test(command)) ||
    (item.id === 'prism' && /棱|方|prism/.test(command))
  )
  if (nextShape) setShape(nextShape.id)

  if (/思考|thinking/.test(command)) triggerAction('thinking')
  else if (/庆祝|开心|celebrate/.test(command)) triggerAction('celebrate')
  else if (/旋转|转一圈|spin/.test(command)) triggerAction('spin')
  else if (/弹跳|跳起来|蹦|bounce|jump/.test(command)) triggerAction('bounce')
  else if (/摇摆|摇一摇|晃|sway|wiggle/.test(command)) triggerAction('sway')
  else if (/惊讶|惊喜|瞪大|surprise|wow/.test(command)) triggerAction('surprise')
  else if (/俏皮|调皮|可爱|playful|wink/.test(command)) triggerAction('playful')
  else if (/好奇|探索|curious/.test(command)) triggerAction('curious')
  else if (/待机|停止|idle/.test(command)) triggerAction('idle')
  else if (nextPalette || nextShape) triggerAction('curious')
}

const wakeWordPattern = /justin|贾斯汀/i
const handleVoiceTranscript = (rawTranscript: string) => {
  const command = rawTranscript.trim()
  if (!command) return

  if (!isAwake.value) {
    const wakeMatch = command.match(wakeWordPattern)
    if (!wakeMatch) {
      transcript.value = command
      return
    }

    isAwake.value = true
    triggerAction('curious')
    const afterWakeWord = command.slice((wakeMatch.index ?? 0) + wakeMatch[0].length).replace(/^[\s,，。.!！?？]+/, '')
    transcript.value = afterWakeWord ? `Justin · ${afterWakeWord}` : 'Justin 已唤醒'
    if (afterWakeWord) applyVoiceCommand(afterWakeWord)
    return
  }

  transcript.value = command
  applyVoiceCommand(command)
}

const stopVoice = () => {
  window.clearTimeout(voiceRestartTimer)
  recognition?.stop()
  recognition = null
  isListening.value = false
  isAwake.value = false
  if (action.value === 'curious') action.value = 'idle'
}

let recognition: SpeechRecognitionLike | null = null
const startVoice = () => {
  const Constructor = recognitionConstructor()
  if (!Constructor) {
    transcript.value = '当前浏览器不支持语音识别'
    return
  }

  recognition = new Constructor()
  recognition.lang = 'zh-CN'
  recognition.continuous = true
  recognition.interimResults = true
  recognition.onresult = (event) => {
    const result = event.results[event.resultIndex ?? 0]?.[0]
    if (!result || result.isFinal === false) return
    handleVoiceTranscript(result.transcript)
  }
  recognition.onerror = () => { transcript.value = '没有听清，请再试一次' }
  recognition.onend = () => {
    if (!isListening.value || !recognition) return
    window.clearTimeout(voiceRestartTimer)
    voiceRestartTimer = window.setTimeout(() => {
      if (!isListening.value || !recognition) return
      try { recognition.start() } catch { transcript.value = '语音权限尚未开启' }
    }, 280)
  }
  try {
    recognition.start()
    isListening.value = true
    isAwake.value = false
    triggerAction('curious')
  } catch {
    transcript.value = '语音权限尚未开启'
    stopVoice()
  }
}

const toggleVoice = () => { if (isListening.value) stopVoice(); else startVoice() }

onBeforeUnmount(() => {
  window.clearTimeout(actionTimer)
  window.clearTimeout(shapeTimer)
  window.clearTimeout(voiceRestartTimer)
  stopVoice()
})
</script>

<style scoped lang="scss">
.agent-constellation { position: relative; width: min(46vw, 680px); height: min(50vw, 720px); min-width: 420px; min-height: 470px; margin-left: auto; transform: translateX(clamp(0px, 1.8vw, 28px)); isolation: isolate; color: #426286; }
.agent-stage { position: absolute; inset: 0; display: grid; place-items: center; }
.agent-stage::before { content: ''; position: absolute; width: 58%; height: 15%; bottom: 13%; border-radius: 50%; background: radial-gradient(ellipse, color-mix(in srgb, var(--agent-deep) 22%, transparent), transparent 72%); filter: blur(20px); opacity: .72; }
.agent-stage__halo { position: absolute; inset: 11%; border-radius: 50%; background: radial-gradient(circle, color-mix(in srgb, var(--agent-glow) 42%, transparent), color-mix(in srgb, var(--agent-main) 14%, transparent) 38%, transparent 72%); filter: blur(32px); animation: agent-halo 5s ease-in-out infinite; }
.agent-stage__orbit-light { position: absolute; top: 14%; right: 17%; width: 9px; height: 9px; border: 1px solid rgba(255,255,255,.8); border-radius: 50%; background: var(--agent-glow); box-shadow: 0 0 16px 3px color-mix(in srgb, var(--agent-glow) 66%, transparent); animation: orbit-light 4.8s ease-in-out infinite; }
.agent-avatar-trigger { position: relative; z-index: 2; width: 74%; height: 74%; padding: 0; border: 0; border-radius: 50%; background: transparent; cursor: pointer; transition: transform 360ms cubic-bezier(.2, .8, .2, 1), filter 360ms ease; }
.agent-avatar-trigger:hover { transform: translateY(-4px) scale(1.018); filter: drop-shadow(0 30px 26px color-mix(in srgb, var(--agent-deep) 30%, transparent)); }
.agent-avatar-trigger:active, .agent-constellation.is-pressed .agent-avatar-trigger { transform: translateY(1px) scale(.975); }
.agent-avatar-trigger:focus-visible { outline: 3px solid color-mix(in srgb, var(--agent-main) 62%, white); outline-offset: 8px; }
.agent-avatar { width: 100%; height: 100%; overflow: visible; transform: perspective(720px) rotateX(var(--agent-tilt-y)) rotateY(var(--agent-tilt-x)); transition: transform 500ms cubic-bezier(.2, .8, .2, 1); filter: drop-shadow(0 28px 28px color-mix(in srgb, var(--agent-deep) 22%, transparent)); }
.agent-avatar__shadow { fill: color-mix(in srgb, var(--agent-deep) 26%, transparent); filter: blur(8px); opacity: .55; }
.agent-avatar__body, .agent-avatar__gloss { transform-box: fill-box; transform-origin: center; animation: agent-breathe 5.4s cubic-bezier(.45, .05, .55, .95) infinite; }
.agent-avatar__body { stroke: none; }
.agent-avatar__body--leaving { animation: agent-shape-leave 420ms cubic-bezier(.2, .8, .2, 1) forwards; }
.agent-avatar__body.is-changing { animation: agent-shape-change 420ms cubic-bezier(.2, .8, .2, 1); }
.agent-avatar__gloss { opacity: .48; mix-blend-mode: screen; pointer-events: none; }
.agent-avatar__specular { fill: rgba(255,255,255,.48); filter: blur(4px); opacity: .62; pointer-events: none; }
.agent-avatar__face-shell { transform-box: fill-box; transform-origin: center; animation: face-idle-drift 5.4s cubic-bezier(.45, .05, .55, .95) infinite; }
.agent-avatar__face { transform-box: fill-box; transform-origin: center; transition: transform 180ms ease-out; }
.agent-avatar__eye { fill: #f8fdff; stroke: color-mix(in srgb, var(--agent-deep) 45%, #172956); stroke-width: 2; transform-box: fill-box; transform-origin: center; animation: eye-idle 5.8s ease-in-out infinite; }
.agent-avatar__eye:nth-child(2) { animation-delay: -2.9s; }
.agent-avatar__eye-glint { fill: color-mix(in srgb, var(--agent-main) 55%, white); }
.agent-avatar__spark { fill: var(--agent-glow); filter: drop-shadow(0 0 8px var(--agent-glow)); animation: spark-pulse 2.6s ease-in-out infinite; }
.agent-avatar__spark--secondary { animation-delay: -1.1s; }
.agent-stage__prompt { position: absolute; top: 12%; z-index: 3; padding: 6px 10px; border: 1px solid rgba(255,255,255,.5); border-radius: 999px; color: color-mix(in srgb, var(--agent-deep) 66%, #587698); background: rgba(255,255,255,.26); opacity: 0; transform: translateY(5px); transition: opacity 240ms ease, transform 240ms ease; backdrop-filter: blur(10px); font-size: 10px; letter-spacing: .06em; pointer-events: none; }
.agent-constellation.is-hovered .agent-stage__prompt, .agent-constellation.is-controls-open .agent-stage__prompt { opacity: 1; transform: translateY(0); }
.agent-stage__status { position: absolute; bottom: 19%; z-index: 3; display: inline-flex; align-items: center; gap: 7px; padding: 7px 12px; border: 1px solid color-mix(in srgb, var(--agent-main) 22%, white); border-radius: 999px; color: #5d7ba1; background: rgba(255, 255, 255, .42); box-shadow: 0 8px 20px rgba(75, 129, 181, .08), inset 0 1px 0 rgba(255,255,255,.7); backdrop-filter: blur(12px); font-size: 10px; letter-spacing: .08em; }
.agent-stage__status-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--agent-main); box-shadow: 0 0 10px var(--agent-glow); }
.agent-stage--thinking .agent-avatar__body { animation: agent-thinking 2.4s ease-in-out infinite; }
.agent-stage--thinking .agent-avatar__face-shell { animation: face-thinking 2.4s ease-in-out infinite; }
.agent-stage--thinking .agent-avatar__eye { animation: eye-thinking 2.4s ease-in-out infinite; }
.agent-stage--celebrate .agent-avatar__body { animation: agent-celebrate 1.75s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--celebrate .agent-avatar__face-shell { animation: face-celebrate 1.75s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--celebrate .agent-avatar__eye { animation: eye-happy 1.75s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--spin .agent-avatar__body, .agent-stage--spin .agent-avatar__gloss { animation: agent-spin 1.25s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--bounce .agent-avatar__body { animation: agent-bounce 1.3s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--bounce .agent-avatar__face-shell { animation: face-bounce 1.3s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--sway .agent-avatar__body { animation: agent-sway 1.45s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--sway .agent-avatar__face-shell { animation: face-sway 1.45s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--surprise .agent-avatar__body { animation: agent-surprise 1.05s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--surprise .agent-avatar__face-shell { animation: face-surprise 1.05s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--surprise .agent-avatar__eye { animation: eye-surprise 1.05s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--playful .agent-avatar__body { animation: agent-playful 1.65s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--playful .agent-avatar__face-shell { animation: face-playful 1.65s cubic-bezier(.2, .8, .2, 1); }
.agent-stage--playful .agent-avatar__eye:first-child { animation: playful-wink 1.65s ease-in-out; }
.agent-stage--awake .agent-stage__status { border-color: color-mix(in srgb, var(--agent-main) 58%, white); color: color-mix(in srgb, var(--agent-deep) 86%, #173963); box-shadow: 0 0 0 5px color-mix(in srgb, var(--agent-glow) 12%, transparent), 0 10px 24px rgba(75, 129, 181, .14), inset 0 1px 0 rgba(255,255,255,.8); }
.agent-stage--awake .agent-stage__status-dot { animation: awake-pulse 1s ease-in-out infinite; }
.agent-stage--listening .agent-avatar__eye { animation: eye-listening 1.15s ease-in-out infinite; }
.agent-stage--listening .agent-stage__rings span:nth-child(2) { animation-delay: 180ms; }
.agent-stage--listening .agent-stage__rings span:nth-child(3) { animation-delay: 360ms; }
.agent-controls { position: absolute; top: 84%; left: 50%; z-index: 4; width: min(100%, 540px); box-sizing: border-box; display: grid; gap: 8px; padding: 12px 14px; border: 1px solid rgba(255,255,255,.72); border-radius: 18px; background: linear-gradient(145deg, rgba(255,255,255,.58), rgba(223,240,255,.34)); box-shadow: 0 24px 48px rgba(73,125,207,.16), inset 0 1px 0 rgba(255,255,255,.94), inset 0 -1px 0 rgba(125,177,220,.12); opacity: 0; visibility: hidden; pointer-events: none; transform: translate(-50%, 14px) scale(.94); transition: opacity 300ms ease, transform 360ms cubic-bezier(.2, .8, .2, 1), visibility 300ms ease; backdrop-filter: blur(18px) saturate(125%); }
.agent-controls::before { content: ''; position: absolute; top: -7px; left: 50%; width: 13px; height: 13px; border-top: 1px solid rgba(255,255,255,.72); border-left: 1px solid rgba(255,255,255,.72); background: rgba(244,250,255,.7); transform: translateX(-50%) rotate(45deg); backdrop-filter: blur(12px); }
.agent-controls.is-open { opacity: 1; visibility: visible; pointer-events: auto; transform: translate(-50%, 0) scale(1); }
.agent-controls__line { display: flex; align-items: center; justify-content: center; gap: 6px; min-height: 28px; }
.agent-controls__line--actions { justify-content: flex-start; flex-wrap: wrap; }
.agent-controls__line--colors { justify-content: flex-start; }
.agent-controls__label { min-width: 45px; color: #82a0c1; font: 9px var(--font-mono, monospace); letter-spacing: .16em; }
.agent-control { min-height: 30px; padding: 0 10px; border: 1px solid rgba(115,165,205,.2); border-radius: 999px; color: #5f7da1; background: rgba(255,255,255,.38); cursor: pointer; font: inherit; font-size: 10px; transition: border-color 180ms ease, color 180ms ease, background-color 180ms ease, transform 180ms ease; }
.agent-control:hover, .agent-control[aria-pressed='true'] { border-color: color-mix(in srgb, var(--agent-main) 55%, white); color: color-mix(in srgb, var(--agent-deep) 80%, #173963); background: color-mix(in srgb, var(--agent-light) 60%, white); transform: translateY(-1px); }
.agent-control:active { transform: translateY(0); }
.agent-control--shape { display: inline-flex; align-items: center; gap: 6px; }
.agent-control__shape-mark { width: 10px; height: 10px; display: block; border: 1px solid currentColor; border-radius: 50%; }
.agent-control__shape-mark--blob { border-radius: 45% 55% 52% 48%; }
.agent-control__shape-mark--capsule { height: 13px; border-radius: 999px; }
.agent-control__shape-mark--prism { border-radius: 2px; transform: rotate(45deg) scale(.72); }
.agent-control--voice { display: inline-flex; align-items: center; gap: 5px; margin-left: auto; }
.agent-control--voice svg { width: 13px; height: 13px; }
.agent-control--voice.is-listening { border-color: var(--agent-main); color: var(--agent-deep); background: color-mix(in srgb, var(--agent-light) 70%, white); box-shadow: 0 0 0 4px color-mix(in srgb, var(--agent-glow) 18%, transparent); }
.agent-color { width: 17px; height: 17px; padding: 0; border: 2px solid rgba(255,255,255,.82); border-radius: 50%; background: var(--swatch); box-shadow: 0 2px 6px rgba(60, 111, 166, .18); cursor: pointer; transition: transform 180ms ease, outline-color 180ms ease; }
.agent-color:hover, .agent-color[aria-pressed='true'] { outline: 2px solid color-mix(in srgb, var(--swatch) 55%, white); outline-offset: 2px; transform: scale(1.12); }
.agent-controls__hint { min-width: 0; margin-left: auto; overflow: hidden; color: #88a1bd; font-size: 9px; line-height: 1.3; text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.agent-control:focus-visible, .agent-color:focus-visible { outline: 3px solid color-mix(in srgb, var(--agent-main) 48%, white); outline-offset: 3px; }
@keyframes agent-breathe { 0%, 100% { transform: translate3d(0, 0, 0) rotate(-.8deg) scale(1, 1); } 22% { transform: translate3d(6px, -7px, 0) rotate(1deg) scale(1.02, .985); } 48% { transform: translate3d(-3px, -15px, 0) rotate(-1.4deg) scale(1.045, .965); } 72% { transform: translate3d(-7px, -5px, 0) rotate(.7deg) scale(1.018, .99); } }
@keyframes face-idle-drift { 0%, 100% { transform: translate3d(0, 0, 0) rotate(0); } 24% { transform: translate3d(3px, -4px, 0) rotate(1.4deg); } 50% { transform: translate3d(-4px, -8px, 0) rotate(-1.8deg); } 76% { transform: translate3d(-2px, -2px, 0) rotate(.9deg); } }
@keyframes eye-idle { 0%, 40%, 100% { transform: scaleY(1); } 46% { transform: scaleY(.94); } 49% { transform: scaleY(.1); } 52% { transform: scaleY(1); } 76% { transform: scaleY(1); } 79% { transform: scaleY(.12); } 82% { transform: scaleY(1); } }
@keyframes eye-thinking { 0%, 100% { transform: scaleY(.9); } 50% { transform: scaleY(.68); } }
@keyframes eye-happy { 0%, 100% { transform: scaleY(1); } 28% { transform: scaleY(.72); } 58% { transform: scaleY(.82); } }
@keyframes eye-surprise { 0% { transform: scale(1); } 24% { transform: scale(1.24, 1.18); } 56% { transform: scale(1.1); } 100% { transform: scale(1); } }
@keyframes eye-listening { 0%, 100% { transform: scaleY(1); } 50% { transform: scaleY(.82); } }
@keyframes agent-thinking { 0%, 100% { transform: translate(-8px, 2px) rotate(-3deg); } 50% { transform: translate(16px, -12px) rotate(5deg); } }
@keyframes face-thinking { 0%, 100% { transform: translate(-4px, 3px) rotate(-4deg); } 50% { transform: translate(8px, -7px) rotate(6deg); } }
@keyframes agent-celebrate { 0% { transform: translateY(0) scale(1); } 24% { transform: translateY(-42px) scale(1.18, .84); } 54% { transform: translateY(4px) scale(.91, 1.12); } 76% { transform: translateY(-15px) scale(1.06, .96); } 100% { transform: translateY(0) scale(1); } }
@keyframes face-celebrate { 0%, 100% { transform: translateY(0) scale(1); } 24% { transform: translateY(-9px) scale(1.1); } 54% { transform: translateY(4px) scale(.94, 1.08); } 76% { transform: translateY(-3px) scale(1.04); } }
@keyframes agent-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
@keyframes agent-bounce { 0% { transform: translateY(0) scale(1); } 20% { transform: translateY(-54px) scale(1.14, .82); } 44% { transform: translateY(5px) scale(.9, 1.14); } 65% { transform: translateY(-25px) scale(1.07, .94); } 84% { transform: translateY(2px) scale(.96, 1.06); } 100% { transform: translateY(0) scale(1); } }
@keyframes face-bounce { 0%, 100% { transform: translateY(0); } 20% { transform: translateY(-13px) scale(1.09); } 44% { transform: translateY(4px) scale(.94, 1.08); } 65% { transform: translateY(-5px) scale(1.04); } }
@keyframes agent-sway { 0%, 100% { transform: rotate(0) translateX(0); } 22% { transform: rotate(-12deg) translateX(-12px); } 52% { transform: rotate(11deg) translateX(14px); } 78% { transform: rotate(-6deg) translateX(-7px); } }
@keyframes face-sway { 0%, 100% { transform: rotate(0); } 22% { transform: rotate(-8deg) translateX(-4px); } 52% { transform: rotate(8deg) translateX(5px); } 78% { transform: rotate(-4deg); } }
@keyframes agent-surprise { 0% { transform: scale(.82) translateY(8px); } 24% { transform: scale(1.2, .88) translateY(-12px); } 48% { transform: scale(.94, 1.08) translateY(3px); } 72% { transform: scale(1.05, .97); } 100% { transform: scale(1); } }
@keyframes face-surprise { 0% { transform: scale(.86); } 24% { transform: scale(1.2); } 48% { transform: scale(.96); } 72% { transform: scale(1.06); } 100% { transform: scale(1); } }
@keyframes agent-playful { 0%, 100% { transform: rotate(0) translateY(0); } 22% { transform: rotate(8deg) translateY(-12px); } 50% { transform: rotate(-8deg) translateY(2px); } 76% { transform: rotate(4deg) translateY(-5px); } }
@keyframes face-playful { 0%, 100% { transform: rotate(0); } 22% { transform: rotate(10deg) translate(6px, -5px); } 50% { transform: rotate(-9deg) translate(-5px, 2px); } 76% { transform: rotate(5deg) translate(3px, -2px); } }
@keyframes playful-wink { 0%, 25%, 100% { transform: scaleY(1); } 37% { transform: scaleY(.08); } 50% { transform: scaleY(1); } }
@keyframes agent-shape-change { 0% { opacity: .35; transform: scale(.88) rotate(-5deg); } 65% { opacity: 1; transform: scale(1.035) rotate(2deg); } 100% { transform: scale(1) rotate(0); } }
@keyframes agent-shape-leave { 0% { opacity: .7; transform: scale(1); } 100% { opacity: 0; transform: scale(1.12) rotate(5deg); } }
@keyframes agent-halo { 0%, 100% { opacity: .62; transform: scale(.96); } 50% { opacity: .9; transform: scale(1.04); } }
@keyframes spark-pulse { 0%, 100% { opacity: .45; transform: scale(.8); } 50% { opacity: 1; transform: scale(1.3); } }
@keyframes orbit-light { 0%, 100% { transform: translate(0, 0) scale(.85); opacity: .55; } 50% { transform: translate(-12px, 9px) scale(1.18); opacity: 1; } }
@keyframes awake-pulse { 0%, 100% { transform: scale(.8); box-shadow: 0 0 8px var(--agent-glow); } 50% { transform: scale(1.35); box-shadow: 0 0 16px var(--agent-glow); } }
@media (max-width: 760px) {
  .agent-constellation { width: min(100%, 560px); min-width: 0; height: min(118vw, 650px); min-height: 430px; margin-left: 0; transform: none; }
  .agent-avatar-trigger { width: 68%; height: 68%; }
  .agent-controls { top: 76%; width: min(100%, 520px); }
  .agent-controls { padding: 10px; }
  .agent-controls__line { flex-wrap: wrap; }
  .agent-controls__label { min-width: 42px; }
  .agent-controls__hint { flex-basis: 100%; margin: 2px 0 0 42px; text-align: left; }
}
@media (prefers-reduced-motion: reduce) {
  .agent-stage__halo, .agent-avatar__body, .agent-avatar__gloss, .agent-avatar__face-shell, .agent-avatar__eye, .agent-avatar__spark, .agent-stage__orbit-light { animation: none; }
  .agent-avatar__face-shell, .agent-avatar__face, .agent-avatar, .agent-avatar-trigger, .agent-controls, .agent-stage__prompt { transition: none; }
}
</style>
