<template>
  <header class="app-topbar" aria-label="应用工作栏">
    <div class="app-topbar__brand-zone">
      <button
        class="app-topbar__icon-button app-topbar__menu-button"
        type="button"
        aria-label="打开导航"
        title="打开导航"
        @click="emit('menu')"
      >
        <el-icon><Menu /></el-icon>
      </button>

      <button
        class="app-topbar__brand"
        type="button"
        aria-label="知弈工作台"
        title="知弈工作台"
        @click="emit('home')"
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

    <div class="app-topbar__context" aria-label="当前工作区">
      <span class="app-topbar__context-eyebrow">{{ contextEyebrow }}</span>
      <span class="app-topbar__context-divider" aria-hidden="true">/</span>
      <strong class="app-topbar__context-title" :title="contextTitle">{{ contextTitle }}</strong>
      <span v-if="contextMeta" class="app-topbar__context-meta" :title="contextMeta">{{ contextMeta }}</span>
    </div>

    <div class="app-topbar__command">
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

  </header>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import {
  Menu,
  Search
} from '@element-plus/icons-vue'

withDefaults(defineProps<{
  contextEyebrow: string
  contextTitle: string
  contextMeta?: string
}>(), {
  contextMeta: ''
})

const emit = defineEmits<{
  menu: []
  home: []
  navigate: [path: string]
}>()

const query = ref('')
const commandFocused = ref(false)

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

.app-topbar__brand-zone,
.app-topbar__menu-links,
.app-topbar__brand {
  display: flex;
  align-items: center;
}

.app-topbar__brand-zone {
  min-width: 0;
}

.app-topbar__brand,
.app-topbar__icon-button {
  color: inherit;
  border: 0;
  background: transparent;
  cursor: pointer;
  transition: background-color 160ms ease, color 160ms ease, opacity 160ms ease;
}

.app-topbar__brand {
  flex: 0 0 30px;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 2px;
  border-radius: 6px;
  text-align: left;
}

.app-topbar__brand:hover,
.app-topbar__icon-button:hover:not(:disabled) {
  background: var(--app-topbar-hover);
}

.app-topbar__brand:focus-visible,
.app-topbar__icon-button:focus-visible,
.app-command-center:focus-within {
  outline: 2px solid var(--app-topbar-focus-ring);
  outline-offset: 1px;
}

.app-topbar__logo {
  display: grid;
  flex: 0 0 24px;
  place-items: center;
  width: 24px;
  height: 24px;
  overflow: hidden;
  background: var(--app-topbar-logo-bg);
  border: 1px solid var(--app-topbar-border);
  border-radius: 6px;
}

.app-topbar__logo img {
  width: 19px;
  height: 19px;
  object-fit: contain;
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
  font-size: 12px;
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

.app-topbar__menu-links button:focus-visible {
  outline: 2px solid var(--app-topbar-focus-ring);
  outline-offset: 1px;
}

.app-topbar__icon-button {
  display: inline-grid;
  flex: 0 0 28px;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 5px;
}

.app-topbar__icon-button:disabled {
  color: var(--app-topbar-muted);
  cursor: default;
  opacity: 0.44;
}

.app-topbar__context,
.app-topbar__command {
  min-width: 0;
}

.app-topbar__context {
  display: flex;
  align-items: center;
  gap: 7px;
  overflow: hidden;
  min-width: 0;
  padding-right: clamp(230px, 31vw, 510px);
  color: var(--app-topbar-muted);
  white-space: nowrap;
}

.app-topbar__context-eyebrow {
  flex: 0 0 auto;
  color: var(--app-topbar-muted);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.app-topbar__context-divider {
  color: var(--app-topbar-muted);
  opacity: 0.55;
}

.app-topbar__context-title,
.app-topbar__context-meta {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-topbar__context-title {
  color: var(--app-topbar-text);
  font-size: 13px;
  font-weight: 560;
}

.app-topbar__context-meta {
  flex: 0 0 auto;
  max-width: 150px;
  color: var(--app-topbar-muted);
  font-family: var(--font-mono);
  font-size: 10px;
}

.app-command-center {
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  align-items: center;
  width: clamp(280px, 31vw, 500px);
  height: 30px;
  margin: 0 auto;
  padding: 0 8px;
  transform: translate(-50%, -50%);
  color: var(--app-topbar-muted);
  background: var(--app-topbar-input-bg);
  border: 1px solid var(--app-topbar-input-border);
  border-radius: 6px;
  transition: border-color 160ms ease, background-color 160ms ease, box-shadow 160ms ease;
}

.app-command-center:hover,
.app-command-center.is-focused {
  background: var(--app-topbar-input-bg-hover);
  border-color: var(--app-topbar-focus-border);
}

.app-command-center.is-focused {
  box-shadow: 0 0 0 3px var(--app-topbar-focus-ring);
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
  font-size: 12px;
  background: transparent;
  border: 0;
  outline: 0;
}

.app-command-center input::placeholder {
  color: var(--app-topbar-muted);
  opacity: 0.8;
}

.app-command-center kbd {
  flex: 0 0 auto;
  padding: 2px 5px;
  color: var(--app-topbar-muted);
  font-family: var(--font-mono);
  font-size: 9px;
  line-height: 1.2;
  background: var(--app-topbar-kbd-bg);
  border: 1px solid var(--app-topbar-border);
  border-radius: 4px;
}

@media (max-width: 1180px) {
  .app-topbar {
    grid-template-columns: auto minmax(0, 1fr) auto;
    gap: 8px;
  }

  .app-topbar__context {
    padding-right: clamp(200px, 32vw, 380px);
  }

  .app-topbar__context-meta {
    display: none;
  }

  .app-topbar__menu-links {
    display: none;
  }
}

@media (max-width: 860px) {
  .app-topbar {
    grid-template-columns: auto minmax(160px, 1fr) auto;
  }

  .app-topbar__context {
    display: none;
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
  .app-topbar__icon-button,
  .app-command-center {
    transition: none;
  }
}
</style>
