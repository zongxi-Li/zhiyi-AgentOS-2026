import { createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  ElAlert,
  ElAside,
  ElAvatar,
  ElButton,
  ElCard,
  ElCheckbox,
  ElCol,
  ElCollapse,
  ElCollapseItem,
  ElColorPicker,
  ElContainer,
  ElDialog,
  ElDrawer,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElHeader,
  ElIcon,
  ElImage,
  ElInput,
  ElInputNumber,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElProgress,
  ElRadio,
  ElRadioButton,
  ElRadioGroup,
  ElResult,
  ElRow,
  ElSelect,
  ElSlider,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTabPane,
  ElTabs,
  ElTag,
  ElTooltip,
  ElUpload,
  ElLoading,
  provideGlobalConfig
} from 'element-plus'
import 'element-plus/dist/index.css'
import zhCN from 'element-plus/dist/locale/zh-cn.mjs'
import en from 'element-plus/dist/locale/en.mjs'

import App from './App.vue'
import router from './router'
import i18n from './i18n'
import { initTheme } from './composables/useTheme'
import './styles/global.css'
import './styles/responsive.css'
import './styles/animations.css'

initTheme()

const app = createApp(App)
const pinia = createPinia()

const elementPlugins = [
  ElLoading,
  ElMessage,
  ElMessageBox
]

const elementComponents = [
  ElAlert,
  ElAside,
  ElAvatar,
  ElButton,
  ElCard,
  ElCheckbox,
  ElCol,
  ElCollapse,
  ElCollapseItem,
  ElColorPicker,
  ElContainer,
  ElDialog,
  ElDrawer,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElHeader,
  ElIcon,
  ElImage,
  ElInput,
  ElInputNumber,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElProgress,
  ElRadio,
  ElRadioButton,
  ElRadioGroup,
  ElResult,
  ElRow,
  ElSelect,
  ElSlider,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTabPane,
  ElTabs,
  ElTag,
  ElTooltip,
  ElUpload
]

for (const plugin of elementPlugins) app.use(plugin)
for (const component of elementComponents) app.use(component)

// 根据当前语言设置 Element Plus 语言
const getElementPlusLocale = () => {
  const currentLocale = i18n.global.locale.value
  return currentLocale === 'en' ? en : zhCN
}

app.use(pinia)
app.use(router)
app.use(i18n)
provideGlobalConfig({ locale: getElementPlusLocale() }, app, true)

app.mount('#app')

