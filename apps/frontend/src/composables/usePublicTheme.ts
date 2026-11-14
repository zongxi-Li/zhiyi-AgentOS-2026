import { computed } from 'vue'
import { colorSchemes, isDarkColorScheme, type ColorSchemeId } from '@/themes/presets'
import { useTheme } from './useTheme'

/**
 * 公开介绍页与认证页的明暗状态——直接跟随工作台主题（单一事实源）。
 *
 * 2026-11-14 用户裁定：操作界面是暗色介绍页就暗色，浅色就都浅色。
 * 取代原先「公开页独立浅色、sessionStorage 共享」的设计。
 * 页面上的明暗切换按钮直接改全局主题并持久化（appSettings.colorScheme），
 * 工作台与设置页随之同步；浅色变体沿用 useTheme 的记忆键。
 */
const LIGHT_SCHEME_KEY = 'theme.public_light_scheme'
const LAST_DARK_KEY = 'theme.public_last_dark_scheme'

function savedLightScheme(): ColorSchemeId {
  try {
    const saved = localStorage.getItem(LIGHT_SCHEME_KEY)
    const scheme = colorSchemes.find(item => item.id === saved)
    if (scheme && !isDarkColorScheme(scheme.id)) return scheme.id
  } catch {
    // 禁用存储时回退默认浅色。
  }
  return 'blue-purple'
}

function lastDarkScheme(): ColorSchemeId {
  try {
    const saved = localStorage.getItem(LAST_DARK_KEY)
    const scheme = colorSchemes.find(item => item.id === saved)
    if (scheme && isDarkColorScheme(scheme.id)) return scheme.id
  } catch {
    // 禁用存储时回退默认暗色。
  }
  return 'codex-dark'
}

export function usePublicTheme() {
  const { currentScheme, setPersistedColorScheme } = useTheme()

  const isDarkTheme = computed(() => isDarkColorScheme(currentScheme.value))
  const themeToggleLabel = computed(() => `切换到${isDarkTheme.value ? '明亮' : '黑暗'}模式`)
  const toggleTheme = () => {
    if (isDarkTheme.value) {
      try { localStorage.setItem(LAST_DARK_KEY, currentScheme.value) } catch { /* 忽略 */ }
      setPersistedColorScheme(savedLightScheme())
    } else {
      setPersistedColorScheme(lastDarkScheme())
    }
  }

  return { isDarkTheme, themeToggleLabel, toggleTheme }
}
