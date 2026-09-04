import { createI18n } from 'vue-i18n'
import zhCN from './locales/zh-CN.json'
import en from './locales/en.json'

// 从 localStorage 获取保存的语言设置，默认为简体中文
const getDefaultLocale = (): string => {
  const saved = localStorage.getItem('appSettings')
  if (saved) {
    try {
      const settings = JSON.parse(saved)
      return settings.language || 'zh-CN'
    } catch (e) {
      console.error('加载语言设置失败', e)
    }
  }
  return 'zh-CN' // 默认使用简体中文
}

const i18n = createI18n({
  legacy: false, // 使用 Composition API 模式
  locale: getDefaultLocale(),
  fallbackLocale: 'zh-CN', // 回退语言为简体中文
  messages: {
    'zh-CN': zhCN,
    'en': en
  }
})

export default i18n

