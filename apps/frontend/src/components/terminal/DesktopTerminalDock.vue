<template>
  <section v-show="terminalVisible" class="desktop-terminal" :style="{ height: `${height}px` }" aria-label="内置终端">
    <div class="desktop-terminal__resize" role="separator" aria-label="调整终端高度" aria-orientation="horizontal"
      :aria-valuemin="160" :aria-valuemax="maxHeight()" :aria-valuenow="height" tabindex="0"
      @pointerdown="beginResize" @keydown="resizeKey" @dblclick="setHeight(280)"></div>
    <header class="desktop-terminal__header">
      <span class="desktop-terminal__heading">终端</span>
      <nav class="desktop-terminal__tabs" role="tablist" aria-label="终端会话">
        <div v-for="(session, index) in sessions" :key="session.id" class="desktop-terminal__tab" :class="{ active: terminalActiveId === session.id }">
          <button role="tab" :aria-selected="terminalActiveId === session.id" :title="session.cwd" @click="activate(session.id)">
            <span class="desktop-terminal__shell-icon" aria-hidden="true">›_</span>
            {{ session.profileName }}<span v-if="index > 0" class="desktop-terminal__number">{{ index + 1 }}</span>
            <span v-if="session.state === 'exited'" class="desktop-terminal__exit-dot" aria-label="已退出"></span>
          </button>
          <button class="desktop-terminal__tab-close" :aria-label="`关闭终端 ${index + 1}`" title="终止并关闭此终端" @click="closeSession(session.id)">×</button>
        </div>
      </nav>
      <div class="desktop-terminal__actions">
        <select v-model="profileId" aria-label="选择终端 Shell" :disabled="busy || !profiles.length">
          <option v-for="profile in profiles" :key="profile.id" :value="profile.id">{{ profile.name }}</option>
        </select>
        <button :disabled="busy || !profiles.length" aria-label="新建终端" title="新建终端" @click="newTerminal()">＋</button>
        <button :disabled="busy || !profiles.length" aria-label="选择目录并新建终端" title="选择目录并新建终端" @click="chooseDirectory">▱</button>
        <button :disabled="!terminalActiveId" aria-label="清空终端显示" title="清空显示（保留 Shell 会话）" @click="terminal?.clear()">⌫</button>
        <button aria-label="关闭终端面板" title="收起面板，终端继续运行 · Ctrl+`" @click="terminalVisible = false">×</button>
      </div>
    </header>
    <div v-if="error" class="desktop-terminal__error" role="alert">
      <span>{{ error }}</span><button :disabled="busy" @click="refresh">重试</button>
    </div>
    <div ref="container" class="desktop-terminal__canvas" :class="{ 'is-empty': !terminalActiveId }"></div>
    <div v-if="!terminalActiveId && !error" class="desktop-terminal__empty">
      <span aria-hidden="true">›_</span>
      <strong>{{ busy ? '正在连接本地终端…' : '在工作区中开始一个终端会话' }}</strong>
      <button v-if="!busy && profiles.length" @click="newTerminal()">新建终端</button>
    </div>
    <footer class="desktop-terminal__status">
      <span class="desktop-terminal__status-dot" :class="{ running: activeSession?.state === 'running' }"></span>
      <span>{{ activeSession?.state === 'exited' ? `已退出 · ${activeSession.exitCode}` : activeSession ? '本机终端' : '本地会话' }}</span>
      <span class="desktop-terminal__cwd" :title="`启动目录：${activeSession?.cwd || ''}`">{{ activeSession?.cwd || '当前工作区' }}</span>
      <span class="desktop-terminal__shortcut">Ctrl+`</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Terminal } from '@xterm/xterm'
import type { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { getElectronBridge, type TerminalBridge, type TerminalProfile, type TerminalSession } from '@/platform/electron/bridge'
import { apiUrl } from '@/platform'
import { terminalVisible, terminalActiveId, toggleDesktopTerminal } from '@/composables/useDesktopTerminal'

const container = ref<HTMLElement | null>(null)
const sessions = ref<TerminalSession[]>([])
const profiles = ref<TerminalProfile[]>([])
const profileId = ref('')
const busy = ref(false)
const error = ref('')
const height = ref(280)
const activeSession = computed(() => sessions.value.find(session => session.id === terminalActiveId.value))
let terminal: Terminal | null = null
let fit: FitAddon | null = null
let renderedId: string | null = null
let generation = 0
let cursor = 0
let timer: ReturnType<typeof setTimeout> | undefined
let observer: ResizeObserver | undefined
let frame = 0
const inputQueues = new Map<string, Promise<void>>()
let finishResize: (() => void) | undefined

function bridge(): TerminalBridge {
  const value = getElectronBridge()?.terminal
  if (!value) throw new Error('终端桥接尚未加载，请通过桌面图标重新打开知弈')
  return value
}
function fail(cause: unknown) { error.value = cause instanceof Error ? cause.message.replace(/^Error invoking remote method '[^']+': Error: /, '') : '终端操作失败' }
function maxHeight() { return Math.max(160, Math.min(720, Math.floor(window.innerHeight * 0.7))) }
function setHeight(value: number) {
  height.value = Math.max(160, Math.min(maxHeight(), value))
  try { localStorage.setItem('zhiyi.terminal.height', String(height.value)) } catch { /* Optional layout persistence. */ }
}
function beginResize(event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  finishResize?.()
  const start = event.clientY, original = height.value
  const previous = document.body.style.cursor
  document.body.style.cursor = 'row-resize'
  const move = (current: PointerEvent) => setHeight(original + start - current.clientY)
  finishResize = () => {
    window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', finish)
    document.body.style.cursor = previous; finishResize = undefined
  }
  const finish = () => finishResize?.()
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', finish, { once: true })
}
function resizeKey(event: KeyboardEvent) {
  if (!['ArrowUp', 'ArrowDown', 'Home'].includes(event.key)) return
  event.preventDefault(); setHeight(event.key === 'Home' ? 280 : height.value + (event.key === 'ArrowUp' ? 20 : -20))
}
function shortcut(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && !event.altKey && event.code === 'Backquote' && !event.isComposing) {
    event.preventDefault(); toggleDesktopTerminal()
  }
}
function fitTerminal() {
  cancelAnimationFrame(frame)
  frame = requestAnimationFrame(() => {
    if (!terminalVisible.value || !terminal || !fit || !renderedId || !container.value?.clientWidth) return
    fit.fit()
    const session = sessions.value.find(item => item.id === renderedId)
    if (session?.state === 'running' && (session.cols !== terminal.cols || session.rows !== terminal.rows)) {
      session.cols = terminal.cols; session.rows = terminal.rows
      const id = session.id
      void bridge().resize(id, terminal.cols, terminal.rows).catch(cause => { if (renderedId === id && !busy.value) fail(cause) })
    }
  })
}
async function poll(currentGeneration: number, id: string) {
  if (currentGeneration !== generation || !terminalVisible.value || renderedId !== id) return
  try {
    const result = await bridge().read(id, cursor)
    if (currentGeneration !== generation || renderedId !== id || !terminal) return
    if (result.truncated) terminal.write('\r\n\x1b[33m[较早的输出已截断]\x1b[0m\r\n')
    for (const chunk of result.chunks) terminal.write(chunk.data)
    cursor = result.cursor
    sessions.value = sessions.value.map(session => session.id === id ? result.session : session)
    if (result.session.state === 'running' && terminalVisible.value) timer = setTimeout(() => void poll(currentGeneration, id), 180)
  } catch (cause) { if (currentGeneration === generation) fail(cause) }
}
async function renderSession(id: string | null) {
  const currentGeneration = ++generation
  clearTimeout(timer)
  if (!terminalVisible.value) return
  await nextTick()
  if (currentGeneration !== generation || !container.value) return
  if (!id) { terminal?.dispose(); terminal = null; fit = null; renderedId = null; cursor = 0; container.value.replaceChildren(); return }
  if (renderedId !== id || !terminal) {
    terminal?.dispose(); terminal = null; fit = null; renderedId = null; cursor = 0
    const [{ Terminal: TerminalClass }, { FitAddon: FitClass }] = await Promise.all([import('@xterm/xterm'), import('@xterm/addon-fit')])
    if (currentGeneration !== generation || !container.value) return
    container.value.replaceChildren()
    const instance = new TerminalClass({ cursorBlink: true, fontSize: 13, lineHeight: 1.22, scrollback: 5000,
      fontFamily: 'Cascadia Code, Consolas, Microsoft YaHei, monospace', allowProposedApi: false,
      theme: { background: '#18181b', foreground: '#d4d4d8', cursor: '#e4e4e7', selectionBackground: '#39414f',
        black: '#27272a', red: '#f87171', green: '#86c793', yellow: '#d7ba7d', blue: '#7aa2d7', magenta: '#c4a2dc', cyan: '#7cc8cf', white: '#d4d4d8' } })
    const addon = new FitClass(); instance.loadAddon(addon); instance.open(container.value)
    instance.onData(data => {
      if (terminal !== instance || renderedId !== id) return
      const queued = inputQueues.get(id) || Promise.resolve()
      inputQueues.set(id, queued.then(async () => {
        if (sessions.value.some(session => session.id === id)) await bridge().write(id, data)
      }).catch(cause => { if (renderedId === id && !busy.value) fail(cause) }))
    })
    instance.attachCustomKeyEventHandler(event => !((event.ctrlKey || event.metaKey) && event.code === 'Backquote'))
    terminal = instance; fit = addon; renderedId = id
  }
  terminal.focus(); fitTerminal(); void poll(currentGeneration, id)
}
function activate(id: string) { terminalActiveId.value = id; terminal?.focus() }
async function selectedDirectory(): Promise<string | undefined> {
  try {
    const token = localStorage.getItem('token')
    if (token) {
      const response = await fetch(apiUrl('/api/agentos/v2/workspaces/current'), {
        headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(2000)
      })
      if (response.ok) { const data = await response.json(); if (data.workspaceRoot) return data.workspaceRoot }
    }
    return (await getElectronBridge()?.workspace?.current())?.root
  } catch { return undefined }
}
async function newTerminal(directory?: string) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const session = await bridge().create({ profileId: profileId.value || undefined, cwd: directory || await selectedDirectory(), cols: 100, rows: 20 })
    sessions.value.push(session); terminalActiveId.value = session.id
  } catch (cause) { fail(cause) } finally { busy.value = false }
}
async function chooseDirectory() {
  try { const selected = await getElectronBridge()?.dialog.openDirectory(); if (selected) await newTerminal(selected) } catch (cause) { fail(cause) }
}
async function closeSession(id: string) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  if (terminalActiveId.value === id) { ++generation; clearTimeout(timer) }
  try {
    await bridge().close(id)
    inputQueues.delete(id)
    sessions.value = sessions.value.filter(session => session.id !== id)
    if (terminalActiveId.value === id) {
      terminalActiveId.value = sessions.value[sessions.value.length - 1]?.id || null
      if (!terminalActiveId.value) { ++generation; clearTimeout(timer); terminal?.dispose(); terminal = null; fit = null; renderedId = null }
    }
  } catch (cause) { fail(cause) } finally { busy.value = false }
}
async function refresh() {
  if (busy.value) return
  busy.value = true; error.value = ''
  ++generation; clearTimeout(timer)
  terminal?.dispose(); terminal = null; fit = null; renderedId = null; cursor = 0
  try {
    const [available, existing] = await Promise.all([bridge().profiles(), bridge().list()])
    profiles.value = available.profiles; sessions.value = existing.sessions
    if (!profiles.value.some(profile => profile.id === profileId.value)) profileId.value = profiles.value[0]?.id || ''
    if (!sessions.value.some(session => session.id === terminalActiveId.value)) terminalActiveId.value = sessions.value[0]?.id || null
  } catch (cause) { fail(cause) } finally { busy.value = false }
  if (!error.value && !sessions.value.length && profiles.value.length) await newTerminal()
  else if (!error.value) await renderSession(terminalActiveId.value)
}
watch(terminalActiveId, id => { if (terminalVisible.value) void renderSession(id) })
watch(terminalVisible, visible => {
  if (visible) void refresh()
  else { ++generation; clearTimeout(timer) }
})
onMounted(() => {
  try { const saved = Number(localStorage.getItem('zhiyi.terminal.height')); if (saved >= 160) setHeight(saved) } catch { /* Default height. */ }
  window.addEventListener('keydown', shortcut)
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(fitTerminal)
    if (container.value) observer.observe(container.value)
  }
  if (terminalVisible.value) void refresh()
})
onBeforeUnmount(() => {
  ++generation; clearTimeout(timer); cancelAnimationFrame(frame); finishResize?.(); observer?.disconnect()
  terminal?.dispose(); window.removeEventListener('keydown', shortcut)
})
</script>

<style scoped>
.desktop-terminal { position:relative; flex:0 0 auto; min-height:160px; min-width:0; display:flex; flex-direction:column; overflow:visible; background:#18181b; color:#d4d4d8; border-top:1px solid var(--wb-border,#36363c); font-family:var(--font-sans,system-ui,sans-serif); }
.desktop-terminal__resize { position:absolute; top:-4px; left:0; right:0; height:7px; cursor:row-resize; z-index:5; touch-action:none; }
.desktop-terminal__resize:hover,.desktop-terminal__resize:focus-visible { background:var(--wb-accent,#6591b8); outline:none; }
.desktop-terminal__header { display:flex; flex:0 0 35px; min-width:0; align-items:center; gap:6px; border-bottom:1px solid #2b2b31; padding:0 9px 0 14px; }
.desktop-terminal__heading { flex-shrink:0; font-size:11px; font-weight:600; color:#a1a1aa; letter-spacing:.04em; margin-right:8px; }
.desktop-terminal__tabs { display:flex; align-items:stretch; gap:2px; min-width:0; flex:1; overflow-x:auto; scrollbar-width:thin; }
.desktop-terminal__tab { display:flex; align-items:center; border-bottom:1px solid transparent; opacity:.7; flex-shrink:0; }
.desktop-terminal__tab.active { border-color:#a1a1aa; opacity:1; background:#242428; }
.desktop-terminal button { color:inherit; border:0; background:transparent; cursor:pointer; font:inherit; }
.desktop-terminal button:disabled { opacity:.35; cursor:default; }
.desktop-terminal button:focus-visible,.desktop-terminal select:focus-visible { outline:1px solid #7aa2d7; outline-offset:-2px; }
.desktop-terminal__tab > button:first-child { display:flex; align-items:center; gap:7px; height:32px; padding:0 9px; font-size:11px; white-space:nowrap; }
.desktop-terminal__shell-icon { color:#aaaab4; font:13px Consolas,monospace; }
.desktop-terminal__number { color:#8b8b96; font-size:10px; }
.desktop-terminal__tab-close { font-size:16px!important; width:22px; height:24px; margin-right:3px; opacity:.5; }
.desktop-terminal__tab-close:hover,.desktop-terminal__actions button:hover { background:#36363e; opacity:1; }
.desktop-terminal__actions { display:flex; align-items:center; gap:2px; flex-shrink:0; }
.desktop-terminal__actions select { background:#202024; color:#b8b8c1; border:1px solid #36363e; border-radius:3px; font:10px system-ui,sans-serif; padding:3px 4px; max-width:135px; margin-right:4px; }
.desktop-terminal__actions button { width:25px; height:25px; border-radius:3px; font-size:17px; }
.desktop-terminal__canvas { flex:1; min-height:0; min-width:0; padding:7px 8px 0 14px; overflow:hidden; }
.desktop-terminal__canvas :deep(.xterm) { height:100%; }
.desktop-terminal__canvas :deep(.xterm-viewport) { scrollbar-width:thin; }
.desktop-terminal__status { display:flex; align-items:center; gap:6px; height:22px; flex:0 0 22px; padding:0 12px; color:#80808b; font:10px system-ui,sans-serif; }
.desktop-terminal__status-dot,.desktop-terminal__exit-dot { width:5px; height:5px; border-radius:50%; background:#71717a; flex-shrink:0; }
.desktop-terminal__status-dot.running { background:#86b395; }
.desktop-terminal__cwd { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-left:5px; }
.desktop-terminal__shortcut { margin-left:auto; font:10px Consolas,monospace; }
.desktop-terminal__error { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:7px 14px; background:#3c2c26; color:#e3b29e; font-size:11px; }
.desktop-terminal__error button { text-decoration:underline; white-space:nowrap; }
.desktop-terminal__empty { position:absolute; inset:48px 10px 28px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:9px; color:#777782; font-size:12px; pointer-events:none; }
.desktop-terminal__empty > span { font:24px Consolas,monospace; color:#52525b; }
.desktop-terminal__empty strong { font-weight:400; }
.desktop-terminal__empty button { pointer-events:auto; border:1px solid #45454e; border-radius:3px; padding:5px 11px; color:#c4c4cb; }
@media(max-width:760px) { .desktop-terminal__actions select { max-width:95px; } .desktop-terminal__heading { display:none; } .desktop-terminal__header { padding-left:6px; } }
</style>
