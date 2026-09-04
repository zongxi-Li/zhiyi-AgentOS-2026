<template>
  <header
    class="app-topbar"
    :class="{ 'is-desktop-shell': desktopShell }"
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
          <img src="/logo.png" alt="" />
        </span>
      </button>
    </div>

    <nav class="app-topbar__menu-links" aria-label="工作台菜单">
      <button type="button" @click="emit('navigate', '/agentos/acg')">项目</button>
      <button type="button" @click="emit('navigate', '/agentos-console')">运行</button>
      <button type="button" @click="emit('navigate', '/agentos/resources')">资源</button>
    </nav>

    <div class="app-topbar__command" v-bind="dragRegionProps">
      <label class="app-command-center" :class="{ 'is-focused': commandFocused }">
        <el-icon class="app-command-center__icon" aria-hidden="true"><Search /></el-icon>
        <input
          v-model="query"
          type="search"
          autocomplete="off"
          placeholder="搜索任务、步骤、运行或命令"
          aria-label="搜索任务、步骤、运行或命令"
          @focus="commandFocused = true"
          @blur="commandFocused = false"
          @keydown.esc="clearCommand"
        />
        <kbd aria-hidden="true">⌘ K</kbd>
      </label>
    </div>

    <DesktopWindowControls v-if="desktopShell" />
  </header>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
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
const navigationActionLabel = computed(() => {
  if (props.navigationState === 'drawer') return '打开导航'
  return props.navigationState === 'collapsed' ? '展开导航' : '收起导航'
})

const clearCommand = () => {
  query.value = ''
}
</script>

<style scoped>
.app-topbar {
  position: relative;
  z-index: 20;
  flex: 0 0 42px;
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 42px;
  padding: 0 8px;
  color: var(--app-topbar-text);
  background: var(--app-topbar-bg);
  border-bottom: 1px solid var(--app-topbar-border);
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
  flex: 0 0 34px;
  justify-content: center;
  width: 34px;
  height: 34px;
  padding: 2px;
  border-radius: 10px;
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
  flex: 0 0 28px;
  place-items: center;
  width: 28px;
  height: 28px;
  overflow: visible;
  background: var(--app-topbar-logo-bg);
  border: 1px solid var(--app-topbar-border);
  border-radius: 8px;
  box-shadow: 0 1px 2px color-mix(in srgb, var(--app-topbar-text) 8%, transparent), 0 0 0 1px color-mix(in srgb, var(--app-topbar-text) 18%, transparent) inset;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.app-topbar__logo img {
  width: 22px;
  height: 22px;
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

.app-command-center {
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  align-items: center;
  width: clamp(300px, 34vw, 520px);
  height: 34px;
  margin: 0 auto;
  padding: 0 9px;
  transform: translate(-50%, -50%);
  color: var(--app-topbar-text);
  background: var(--app-topbar-input-bg);
  border: 1px solid var(--app-topbar-input-border);
  border-radius: 10px;
  box-shadow: 0 1px 2px color-mix(in srgb, var(--app-topbar-text) 6%, transparent), 0 0 0 1px color-mix(in srgb, var(--app-topbar-text) 16%, transparent) inset;
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
  margin-right: 7px;
  font-size: 15px;
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
  min-width: 32px;
  padding: 3px 6px;
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
    position: static;
    width: min(calc(100vw - 150px), 420px);
    transform: none;
  }
}

@media (max-width: 560px) {
  .app-topbar {
    padding: 0 7px;
  }

  .app-command-center {
    width: calc(100vw - 145px);
  }

  .app-command-center kbd {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .app-topbar__brand,
  .app-command-center {
    transition: none;
  }
}

/* Screenshot refinement: keep the top chrome quiet and precise. */
.app-topbar__menu-links button {
  height: 30px;
  border-radius: 6px;
}

.app-command-center {
  height: 32px;
  border-radius: 9px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.22);
}

.app-command-center.is-focused {
  box-shadow: 0 0 0 3px var(--app-topbar-focus-ring), 0 2px 8px rgba(0, 0, 0, 0.26);
}
</style>
