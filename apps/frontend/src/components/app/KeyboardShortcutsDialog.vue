<template>
  <el-dialog
    v-model="visible"
    title="键盘快捷键"
    width="480px"
    align-center
    class="shortcuts-dialog"
  >
    <div v-for="group in groups" :key="group.title" class="shortcuts-group">
      <h3 class="shortcuts-group__title">{{ group.title }}</h3>
      <ul class="shortcuts-list">
        <li v-for="item in group.items" :key="item.label" class="shortcuts-list__row">
          <span class="shortcuts-list__label">
            {{ item.label }}
            <span v-if="item.note" class="shortcuts-list__note">{{ item.note }}</span>
          </span>
          <span class="shortcuts-list__keys">
            <template v-for="(combo, comboIndex) in item.combos" :key="comboIndex">
              <span v-if="comboIndex > 0" class="shortcuts-list__sep" aria-hidden="true">/</span>
              <kbd v-for="(key, keyIndex) in combo" :key="`${comboIndex}-${keyIndex}`">{{ key }}</kbd>
            </template>
          </span>
        </li>
      </ul>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { isDesktop } from '@/platform'
import { commands, isMacPlatform, type CommandDescriptor } from '@/workbench/core/commands'

// 快捷键速查浮层：F1 / ? 唤起（useAppKeyboardShortcuts）。
// 渲染进程内由命令表生成；F11/F12 与界面缩放由 Electron Main 处理，单列「系统」组。
interface ShortcutItem {
  label: string
  combos: string[][]
  note?: string
}

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value)
})

const snapshot = ref<CommandDescriptor[]>([])
let unsubscribe: (() => void) | null = null
onMounted(() => {
  const sync = () => { snapshot.value = commands.visible() }
  sync()
  unsubscribe = commands.onDidChange(sync)
})
onBeforeUnmount(() => {
  unsubscribe?.()
  unsubscribe = null
})

const KEY_LABELS: Record<string, string> = {
  arrowleft: '←',
  arrowright: '→',
  arrowup: '↑',
  arrowdown: '↓',
  backquote: '`',
  escape: 'Esc',
  space: 'Space',
  enter: 'Enter',
  tab: 'Tab'
}

const modifierLabel = (token: string): string => {
  if (token === 'mod') return isMacPlatform() ? '⌘' : 'Ctrl'
  if (token === 'ctrl') return 'Ctrl'
  if (token === 'meta') return '⌘'
  if (token === 'alt') return 'Alt'
  return 'Shift'
}

const formatCombo = (binding: string): string[] => {
  const tokens = binding.split('+')
  const key = tokens.pop() || ''
  const keys = tokens.map(modifierLabel)
  keys.push(KEY_LABELS[key] || key.toUpperCase())
  return keys
}

// 系统级快捷键：Electron Main 的 before-input-event 与视图内建行为，不进命令表。
const systemShortcuts = (): ShortcutItem[] => [
  { label: '关闭弹层 / 退出', combos: [['Esc']] },
  { label: '搜索（资源中心）', combos: [['/']] },
  { label: '界面缩放', combos: [['Ctrl', '='], ['Ctrl', '-'], ['Ctrl', '0']] },
  { label: '缩放（滚轮）', combos: [['Ctrl', '滚轮']] },
  ...(isDesktop()
    ? [
        { label: '窗口全屏', combos: [['F11']] },
        { label: '开发者工具', combos: [['F12']], note: '开发模式' }
      ]
    : [])
]

const groups = computed<{ title: string; items: ShortcutItem[] }[]>(() => {
  const grouped = new Map<string, Map<string, ShortcutItem>>()
  for (const command of snapshot.value) {
    if (!command.keys?.length) continue
    const category = command.category || '通用'
    const items = grouped.get(category) || new Map<string, ShortcutItem>()
    const item = items.get(command.title) || { label: command.title, combos: [] }
    item.combos.push(...command.keys.map(formatCombo))
    items.set(command.title, item)
    grouped.set(category, items)
  }
  const result = [...grouped].map(([title, items]) => ({ title, items: [...items.values()] }))
  const system = systemShortcuts()
  if (system.length) result.push({ title: '系统', items: system })
  return result
})
</script>

<style scoped>
.shortcuts-group + .shortcuts-group {
  margin-top: 18px;
}

.shortcuts-group__title {
  margin: 0 0 8px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-tertiary, var(--text-secondary, #8a8f9d));
}

.shortcuts-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.shortcuts-list__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 5px 0;
  font-size: 12.5px;
  color: var(--text-primary, var(--text-secondary, #31394d));
}

.shortcuts-list__label {
  min-width: 0;
}

.shortcuts-list__note {
  margin-left: 6px;
  font-size: 10.5px;
  color: var(--text-tertiary, var(--text-secondary, #8a8f9d));
}

.shortcuts-list__keys {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
}

.shortcuts-list__sep {
  margin: 0 2px;
  font-size: 10.5px;
  color: var(--text-tertiary, var(--text-secondary, #8a8f9d));
}

.shortcuts-list__keys kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border: 1px solid var(--border-secondary, var(--border-color, rgba(127, 127, 127, 0.28)));
  border-radius: 4px;
  background: var(--bg-tertiary, var(--bg-secondary, rgba(127, 127, 127, 0.08)));
  font: 10.5px/1 var(--font-mono, Consolas, monospace);
  color: var(--text-secondary, #5a6172);
  box-shadow: inset 0 -1px 0 rgba(127, 127, 127, 0.16);
}

@media (prefers-reduced-motion: reduce) {
  .shortcuts-dialog :deep(.el-dialog) {
    transition: none;
  }
}
</style>
