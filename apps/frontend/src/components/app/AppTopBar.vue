<template>
  <header
    class="app-topbar"
    :class="{ 'is-desktop-shell': desktopShell, 'is-rail-collapsed': props.navigationState === 'collapsed' }"
    v-bind="dragRegionProps"
    aria-label="应用工作栏"
  >
    <div class="app-topbar__brand-zone">
      <button
        class="app-topbar__brand"
        :class="{ 'is-collapsed': props.navigationState === 'collapsed', 'is-drawer': props.navigationState === 'drawer' }"
        type="button"
        :aria-label="navigationActionLabel"
        :title="navigationActionLabel"
        @click="emit('menu')"
      >
        <span class="app-topbar__logo" aria-hidden="true">
          <img src="/logo.webp" alt="" />
        </span>
      </button>
    </div>

    <nav class="app-topbar__menu-links" aria-label="工作台菜单">
      <button type="button" @click="emit('navigate', '/agentos/acg')">项目</button>
      <button type="button" @click="emit('navigate', '/history?tab=acg')">运行</button>
      <button type="button" @click="emit('navigate', '/agentos/resources')">资源</button>
    </nav>

    <div class="app-topbar__command" v-bind="dragRegionProps">
      <div class="app-topbar__history" role="group" aria-label="历史导航">
        <button
          type="button"
          class="app-topbar__history-button"
          :disabled="!canGoBack"
          aria-label="上一步"
          title="上一步"
          @click="goBack"
        >
          <el-icon aria-hidden="true"><ArrowLeft /></el-icon>
        </button>
        <button
          type="button"
          class="app-topbar__history-button"
          :disabled="!canGoForward"
          aria-label="下一步"
          title="下一步"
          @click="goForward"
        >
          <el-icon aria-hidden="true"><ArrowRight /></el-icon>
        </button>
      </div>
      <div
        class="app-command-center"
        :class="{ 'is-focused': commandFocused }"
        role="search"
        aria-label="应用导航"
      >
        <el-icon class="app-command-center__icon" aria-hidden="true"><Search /></el-icon>
        <input
          ref="commandInput"
          v-model="query"
          type="search"
          autocomplete="off"
          placeholder="搜索任务、步骤、运行或命令"
          aria-label="搜索任务、步骤、运行或命令"
          aria-keyshortcuts="Control+K Meta+K"
          aria-autocomplete="list"
          aria-controls="app-command-menu"
          :aria-expanded="commandFocused"
          @focus="openCommandMenu"
          @blur="commandFocused = false"
          @keydown="handleCommandKeydown"
          @keydown.esc="clearCommand"
        />
        <kbd aria-hidden="true">{{ commandShortcutLabel }}</kbd>
        <div
          v-if="commandFocused"
          id="app-command-menu"
          class="app-command-menu"
          role="listbox"
          aria-label="导航结果"
        >
          <button
            v-for="(command, index) in filteredCommands"
            :id="`app-command-option-${command.id}`"
            :key="command.id"
            class="app-command-option"
            :class="{ 'is-active': index === selectedCommandIndex }"
            type="button"
            role="option"
            :aria-selected="index === selectedCommandIndex"
            @mousedown.prevent
            @click="selectCommand(command)"
          >
            <span class="app-command-option__label">{{ command.label }}</span>
            <span class="app-command-option__description">{{ command.description }}</span>
          </button>
          <p v-if="!filteredCommands.length" class="app-command-empty">没有匹配的导航项</p>
          <div v-else class="app-command-menu__footer">
            <span>{{ query.trim() ? '匹配导航' : '快速导航' }}</span>
            <span class="app-command-menu__keys" aria-hidden="true">
              <kbd>↑</kbd><kbd>↓</kbd><span>选择</span>
              <kbd>Enter</kbd><span>打开</span>
              <kbd>Esc</kbd><span>关闭</span>
            </span>
          </div>
        </div>
      </div>
    </div>

    <DesktopWindowControls v-if="desktopShell" />
  </header>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowLeft,
  ArrowRight,
  Search
} from '@element-plus/icons-vue'
import DesktopWindowControls from '@window-controls'
import { isDesktop, platform } from '@/platform'

// Desktop 构建下本栏即窗口标题栏（decorations:false）：
// 空白区域承担拖拽与双击最大化，右侧挂窗口控制；
// Web 构建通过 @window-controls 别名拿到空占位，不含任何 Tauri API。
const desktopShell = isDesktop()
const dragRegionProps = platform.dragRegionProps

const props = withDefaults(defineProps<{
  navigationState?: 'expanded' | 'collapsed' | 'drawer'
}>(), {
  navigationState: 'expanded'
})

const emit = defineEmits<{
  menu: []
  home: []
  navigate: [path: string]
}>()

const query = ref('')
const commandFocused = ref(false)
const commandInput = ref<HTMLInputElement | null>(null)
const selectedCommandIndex = ref(0)
const commandShortcutLabel = typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.platform)
  ? '⌘ K'
  : 'Ctrl K'

type CommandItem = {
  id: string
  label: string
  description: string
  path: string
  keywords: string
}

const commands: CommandItem[] = [
  { id: 'projects', label: '项目', description: '查看 Agent 项目与任务', path: '/agentos/acg', keywords: '项目 任务 mission agent acg' },
  { id: 'new-mission', label: '新建任务', description: '创建一个新的 Mission', path: '/agentos/missions/new', keywords: '新建 任务 mission create' },
  { id: 'runs', label: '运行', description: '查看运行记录与执行状态', path: '/history?tab=acg', keywords: '运行 历史 记录 run history' },
  { id: 'resources', label: '资源中心', description: '管理模型、角色与知识资源', path: '/agentos/resources', keywords: '资源 模型 角色 知识 resource' },
  { id: 'memory', label: '运行记忆', description: '查看执行过程中的运行记忆', path: '/agentos/memory', keywords: '记忆 memory 执行' },
  { id: 'chat', label: '对话', description: '打开 Chat 工作台', path: '/chat', keywords: '对话 chat 聊天' },
  { id: 'settings', label: '设置', description: '管理应用设置', path: '/settings', keywords: '设置 配置 settings' }
]

const filteredCommands = computed(() => {
  const terms = query.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return commands

  return commands.filter(command => {
    const searchable = `${command.label} ${command.description} ${command.keywords}`.toLocaleLowerCase()
    return terms.every(term => searchable.includes(term))
  })
})

const selectedCommand = computed(() => filteredCommands.value[selectedCommandIndex.value])
const navigationActionLabel = computed(() => {
  if (props.navigationState === 'drawer') return '打开导航'
  return props.navigationState === 'collapsed' ? '展开导航' : '收起导航'
})

const clearCommand = () => {
  query.value = ''
  commandFocused.value = false
  commandInput.value?.blur()
}

const focusCommand = () => {
  selectedCommandIndex.value = 0
  commandInput.value?.focus()
  commandInput.value?.select()
}

const openCommandMenu = () => {
  commandFocused.value = true
  selectedCommandIndex.value = 0
}

const selectCommand = (command: CommandItem) => {
  query.value = ''
  commandFocused.value = false
  commandInput.value?.blur()
  emit('navigate', command.path)
}

const handleCommandKeydown = (event: KeyboardEvent) => {
  if (!filteredCommands.value.length) return

  if (event.key === 'ArrowDown') {
    event.preventDefault()
    selectedCommandIndex.value = (selectedCommandIndex.value + 1) % filteredCommands.value.length
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    selectedCommandIndex.value = (selectedCommandIndex.value - 1 + filteredCommands.value.length) % filteredCommands.value.length
  } else if (event.key === 'Enter' && selectedCommand.value) {
    event.preventDefault()
    selectCommand(selectedCommand.value)
  }
}

const handleGlobalKeydown = (event: KeyboardEvent) => {
  if (event.repeat || event.altKey || !(event.ctrlKey || event.metaKey)) return
  if (event.key.toLowerCase() !== 'k') return

  event.preventDefault()
  if (commandFocused.value) {
    clearCommand()
  } else {
    focusCommand()
  }
}

watch(query, () => {
  selectedCommandIndex.value = 0
})

// 历史导航：vue-router 不暴露 canGoBack/canGoForward，用写入 history.state 的
// position 对账——current 为当前栈位，furthest 记录本次会话到过的最深处。
const router = useRouter()
const currentPosition = ref(0)
const furthestPosition = ref(0)

const syncHistoryPosition = () => {
  const state = router.options.history.state as { position?: number } | null
  const position = Number(state?.position ?? 0)
  currentPosition.value = position
  furthestPosition.value = Math.max(furthestPosition.value, position)
}

const canGoBack = computed(() => currentPosition.value > 0)
const canGoForward = computed(() => currentPosition.value < furthestPosition.value)
const goBack = () => router.back()
const goForward = () => router.forward()

const stopTrackingHistory = router.afterEach(syncHistoryPosition)
onMounted(() => {
  syncHistoryPosition()
  window.addEventListener('keydown', handleGlobalKeydown, { capture: true })
})
onBeforeUnmount(() => {
  stopTrackingHistory()
  window.removeEventListener('keydown', handleGlobalKeydown, { capture: true })
})
</script>

<style scoped>
.app-topbar {
  position: relative;
  z-index: 20;
  flex: 0 0 36px;
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 36px;
  padding: 0 8px;
  color: var(--app-topbar-text);
  background: var(--app-topbar-bg);
  border-bottom: 0;
}

/* 角落细化：紧凑图标栏那一列上方不画下缘线，线从图标栏右缘（COLLAPSED_SIDEBAR_WIDTH=48，App.vue）开始，对齐 VS Code 标题栏。 */
.app-topbar.is-rail-collapsed {
  border-bottom-color: transparent;
}
.app-topbar.is-rail-collapsed::after {
  content: '';
  position: absolute;
  left: 48px;
  right: 0;
  bottom: 0;
  height: 1px;
  background: transparent;
}

/* Desktop 无边框窗口：关闭按钮必须贴住窗口右缘（Fitts's Law）。 */
.app-topbar.is-desktop-shell {
  padding-right: 0;
}

.app-topbar__brand-zone,
.app-topbar__menu-links,
.app-topbar__brand {
  display: flex;
  align-items: center;
}

.app-topbar__brand-zone {
  min-width: 0;
}

.app-topbar__brand {
  color: inherit;
  border: 0;
  background: transparent;
  cursor: pointer;
  transition: background-color 160ms ease, color 160ms ease, opacity 160ms ease;
}

.app-topbar__brand {
  position: relative;
  flex: 0 0 28px;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 2px;
  border-radius: 8px;
  text-align: left;
}

.app-topbar__brand:hover {
  background: var(--app-topbar-hover);
}

.app-topbar__brand:focus-visible,
.app-command-center:focus-within {
  outline: 2px solid var(--app-topbar-focus-ring);
  outline-offset: 1px;
}

.app-topbar__logo {
  position: relative;
  display: grid;
  flex: 0 0 24px;
  place-items: center;
  width: 24px;
  height: 24px;
  overflow: visible;
  background: var(--app-topbar-logo-bg);
  border: 1px solid var(--app-topbar-border);
  border-radius: 7px;
  box-shadow: 0 1px 2px color-mix(in srgb, var(--app-topbar-text) 8%, transparent), 0 0 0 1px color-mix(in srgb, var(--app-topbar-text) 18%, transparent) inset;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.app-topbar__logo img {
  width: 18px;
  height: 18px;
  object-fit: contain;
}

.app-topbar__brand:hover .app-topbar__logo,
.app-topbar__brand:focus-visible .app-topbar__logo {
  border-color: var(--app-topbar-focus-border);
  box-shadow: 0 2px 5px color-mix(in srgb, var(--app-topbar-text) 12%, transparent), 0 0 0 1px color-mix(in srgb, var(--app-topbar-text) 22%, transparent) inset;
  transform: translateY(-1px);
}

.app-topbar__menu-links {
  gap: 1px;
  min-width: 0;
}

.app-topbar__menu-links button {
  height: 28px;
  padding: 0 8px;
  color: var(--app-topbar-muted);
  font: inherit;
  font-family: var(--font-serif);
  font-size: 13px;
  font-weight: 520;
  letter-spacing: 0;
  border: 0;
  border-radius: 5px;
  background: transparent;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.app-topbar__menu-links button:hover,
.app-topbar__menu-links button:focus-visible {
  color: var(--app-topbar-text);
  background: var(--app-topbar-hover);
}

.app-topbar__menu-links button:active {
  transform: scale(0.98);
}

.app-topbar__menu-links button:focus-visible {
  outline: 2px solid var(--app-topbar-focus-ring);
  outline-offset: 1px;
}

.app-topbar__command {
  min-width: 0;
}

.app-topbar__command {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.app-topbar__history {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 2px;
}

.app-topbar__history-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  color: var(--app-topbar-muted);
  font-size: 15px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.app-topbar__history-button:hover:not(:disabled),
.app-topbar__history-button:focus-visible:not(:disabled) {
  color: var(--app-topbar-text);
  background: var(--app-topbar-hover);
}

.app-topbar__history-button:focus-visible {
  outline: 2px solid var(--app-topbar-focus-ring);
  outline-offset: 1px;
}

.app-topbar__history-button:active:not(:disabled) {
  transform: scale(0.96);
}

.app-topbar__history-button:disabled {
  opacity: 0.38;
  cursor: default;
}

.app-command-center {
  position: relative;
  display: flex;
  align-items: center;
  width: clamp(200px, 24vw, 360px);
  height: 26px;
  flex: 0 1 auto;
  min-width: 0;
  padding: 0 8px;
  color: var(--app-topbar-text);
  background: var(--app-topbar-input-bg);
  border: 1px solid var(--app-topbar-input-border);
  border-radius: 9px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.22);
  transition: border-color 160ms ease, background-color 160ms ease, box-shadow 160ms ease;
}

.app-command-center:hover,
.app-command-center.is-focused {
  background: var(--app-topbar-input-bg-hover);
  border-color: var(--app-topbar-focus-border);
}

.app-command-center.is-focused {
  box-shadow: 0 2px 6px color-mix(in srgb, var(--app-topbar-text) 8%, transparent), 0 0 0 3px var(--app-topbar-focus-ring), 0 0 0 1px color-mix(in srgb, var(--app-topbar-text) 16%, transparent) inset;
}

.app-command-center__icon {
  flex: 0 0 auto;
  margin-right: 6px;
  font-size: 14px;
}

.app-command-center input {
  min-width: 0;
  flex: 1;
  height: 100%;
  color: var(--app-topbar-text);
  font: inherit;
  font-size: 13px;
  background: transparent;
  border: 0;
  outline: 0;
}

.app-command-center input::placeholder {
  color: var(--app-topbar-muted);
  opacity: 0.84;
}

.app-command-center kbd {
  flex: 0 0 auto;
  min-width: 28px;
  padding: 2px 5px;
  color: var(--app-topbar-muted);
  font-family: var(--font-mono);
  font-size: 9px;
  line-height: 1.2;
  text-align: center;
  background: var(--app-topbar-kbd-bg);
  border: 1px solid var(--app-topbar-border);
  border-radius: 6px;
  box-shadow: 0 1px 1px color-mix(in srgb, var(--app-topbar-text) 5%, transparent);
}

.app-command-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: -1px;
  left: -1px;
  z-index: 50;
  display: grid;
  gap: 2px;
  max-height: min(360px, calc(100vh - 64px));
  overflow-y: auto;
  padding: 5px;
  color: var(--app-topbar-text);
  background: var(--app-topbar-input-bg-hover);
  border: 1px solid var(--app-topbar-input-border);
  border-radius: 8px;
  box-shadow: 0 12px 28px color-mix(in srgb, var(--app-topbar-text) 18%, transparent);
}

.app-command-option {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  min-width: 0;
  min-height: 34px;
  padding: 6px 8px;
  color: inherit;
  text-align: left;
  border: 0;
  border-radius: 5px;
  background: transparent;
  cursor: pointer;
}

.app-command-option:hover,
.app-command-option:focus-visible,
.app-command-option.is-active {
  background: var(--app-topbar-active);
}

.app-command-option:focus-visible {
  outline: 2px solid var(--app-topbar-focus-ring);
  outline-offset: -2px;
}

.app-command-option__label {
  overflow: hidden;
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-command-option__description {
  overflow: hidden;
  color: var(--app-topbar-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-command-empty {
  margin: 0;
  padding: 11px 8px;
  color: var(--app-topbar-muted);
  font-size: 11px;
  text-align: center;
}

.app-command-menu__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 4px 3px 0;
  padding: 7px 5px 2px;
  color: var(--app-topbar-muted);
  font-size: 10px;
  border-top: 1px solid var(--app-topbar-border);
}

.app-command-menu__keys {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.app-command-menu__keys kbd {
  min-width: 17px;
  padding: 2px 4px;
  color: var(--app-topbar-text);
  font-family: var(--font-mono);
  font-size: 9px;
  line-height: 1.1;
  text-align: center;
  background: var(--app-topbar-kbd-bg);
  border: 1px solid var(--app-topbar-border);
  border-radius: 3px;
}

@media (max-width: 1180px) {
  .app-topbar {
    grid-template-columns: auto minmax(0, 1fr) auto;
    gap: 8px;
  }

  .app-topbar__menu-links {
    display: none;
  }
}

@media (max-width: 860px) {
  .app-topbar {
    grid-template-columns: auto minmax(160px, 1fr) auto;
  }

  .app-command-center {
    width: min(calc(100vw - 210px), 320px);
  }
}

@media (max-width: 560px) {
  .app-topbar {
    padding: 0 7px;
  }

  .app-command-center {
    width: calc(100vw - 205px);
  }

  .app-command-center kbd {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .app-topbar__brand,
  .app-topbar__history-button,
  .app-command-center {
    transition: none;
  }
}

/* Screenshot refinement: keep the top chrome quiet and precise. */
.app-topbar__menu-links button {
  height: 26px;
  border-radius: 6px;
}

.app-command-center.is-focused {
  box-shadow: 0 0 0 3px var(--app-topbar-focus-ring), 0 2px 8px rgba(0, 0, 0, 0.26);
}
</style>
