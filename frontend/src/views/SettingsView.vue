<!-- 个人设置页面 — 延续 AgentOS 深色工作区，并采用侧栏分组 + 单列设置内容的结构。 -->
<template>
  <div class="settings-view">
    <aside class="settings-rail" aria-label="设置导航">
      <button class="back-to-app" type="button" @click="router.push('/chat')">
        <el-icon><ArrowLeft /></el-icon>
        <span>返回应用</span>
      </button>

      <div class="settings-search">
        <el-icon aria-hidden="true"><Search /></el-icon>
        <input v-model="searchTerm" type="search" placeholder="搜索设置..." aria-label="搜索设置" />
      </div>

      <nav class="settings-nav">
        <section v-for="section in visibleSections" :key="section.label" class="settings-nav-section">
          <h2>{{ section.label }}</h2>
          <button
            v-for="item in section.items"
            :key="item.id"
            class="settings-nav-item"
            :class="{ active: activeTab === item.id && !item.route && (section.label === '个人' || (section.label === '工作区' && (item.id === 'chat' || item.id === 'model'))) }"
            type="button"
            @click="selectSettingsItem(item)"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
            <el-icon v-if="item.route" class="item-arrow"><ArrowLeft /></el-icon>
          </button>
        </section>
        <p v-if="!visibleSections.length" class="settings-empty">没有匹配的设置</p>
      </nav>

      <button class="rail-account" type="button" @click="router.push('/user')">
        <el-avatar :size="30" class="rail-avatar">{{ accountInitial }}</el-avatar>
        <span class="rail-account-copy">
          <strong>{{ accountName }}</strong>
          <small>打开个人中心</small>
        </span>
        <el-icon><ArrowLeft /></el-icon>
      </button>
    </aside>

    <main class="settings-content">
      <header class="settings-header">
        <div>
          <span class="settings-eyebrow">PERSONAL SETTINGS</span>
          <h1>{{ currentTab.label }}</h1>
          <p>{{ currentTab.description }}</p>
        </div>
        <div class="settings-header-actions">
          <span class="save-state" :class="{ saved: lastSaved }">
            <i aria-hidden="true"></i>
            {{ lastSaved ? `已保存 ${lastSavedText}` : '本地设置' }}
          </span>
          <el-button type="primary" class="header-save" @click="saveSettings">
            <el-icon><Check /></el-icon>
            保存设置
          </el-button>
        </div>
      </header>

      <section v-if="activeTab === 'general'" class="settings-section">
        <div class="section-label">权限</div>
        <div class="setting-card">
          <div class="setting-row">
            <div>
              <strong>默认权限</strong>
              <p>默认情况下，知弈可以读取和编辑当前工作空间中的文件。</p>
            </div>
            <el-switch v-model="settings.defaultPermission" aria-label="默认权限" />
          </div>
          <div class="setting-row">
            <div>
              <strong>完整访问权限</strong>
              <p>允许任务在需要时访问工作空间之外的文件，使用前请确认任务边界。</p>
            </div>
            <el-switch v-model="settings.fullAccess" aria-label="完整访问权限" />
          </div>
        </div>

        <div class="section-label">常规</div>
        <div class="setting-card">
          <div class="setting-row setting-row-control">
            <div>
              <strong>无项目任务文件夹</strong>
              <p>在项目外启动的任务默认存储数据的位置。</p>
            </div>
            <el-input v-model="settings.workspaceFolder" class="inline-input" aria-label="无项目任务文件夹" />
          </div>
          <div class="setting-row setting-row-control">
            <div>
              <strong>语言</strong>
              <p>应用界面使用的语言。</p>
            </div>
            <el-select v-model="settings.language" class="inline-select" @change="handleLanguageChange">
              <el-option label="简体中文" value="zh-CN" />
              <el-option label="English" value="en" />
            </el-select>
          </div>
          <div class="setting-row setting-row-control">
            <div>
              <strong>字体大小</strong>
              <p>调整界面文字与控件的整体尺寸。</p>
            </div>
            <div class="compact-slider">
              <el-slider v-model="settings.fontSize" :min="12" :max="20" aria-label="字体大小" />
              <span>{{ settings.fontSize }}px</span>
            </div>
          </div>
        </div>
      </section>

      <section v-else-if="activeTab === 'appearance'" class="settings-section">
        <div class="section-label">主题</div>
        <div class="theme-grid">
          <button
            v-for="theme in themeOptions"
            :key="theme.id"
            class="theme-option"
            :class="[{ active: settings.colorScheme === theme.id }, `theme-${theme.tone}`]"
            type="button"
            @click="settings.colorScheme = theme.id; applyTheme()"
          >
            <span class="theme-preview" :style="{ '--theme-accent': theme.previewColor }">
              <i></i><i></i><i></i>
              <b></b><b></b>
            </span>
            <span class="theme-option-footer">
              <strong>{{ theme.label }}</strong>
              <el-icon v-if="settings.colorScheme === theme.id"><Check /></el-icon>
            </span>
          </button>
        </div>

        <div class="section-label">界面</div>
        <div class="setting-card">
          <div class="setting-row">
            <div>
              <strong>紧凑侧边栏</strong>
              <p>减少导航留白，为工作区保留更多空间。</p>
            </div>
            <el-switch v-model="settings.compactSidebar" aria-label="紧凑侧边栏" />
          </div>
          <div class="setting-row">
            <div>
              <strong>显示底部状态栏</strong>
              <p>在编辑器底部显示当前工作区状态。</p>
            </div>
            <el-switch v-model="settings.showStatusBar" aria-label="显示底部状态栏" />
          </div>
        </div>
      </section>

      <section v-else-if="activeTab === 'privacy'" class="settings-section">
        <div class="section-label">隐私与数据</div>
        <div class="setting-card">
          <div class="setting-row setting-row-control">
            <div>
              <strong>存储位置</strong>
              <p>对话记录和本地偏好设置保存的位置。</p>
            </div>
            <el-radio-group v-model="settings.storageLocation" class="segmented-control">
              <el-radio-button label="local">本地</el-radio-button>
              <el-radio-button label="cloud">云端</el-radio-button>
            </el-radio-group>
          </div>
          <div class="setting-row setting-row-control">
            <div>
              <strong>自动删除记录</strong>
              <p>自动清理旧对话，释放本地存储空间。</p>
            </div>
            <el-select v-model="settings.autoDelete" class="inline-select">
              <el-option label="永不删除" value="never" />
              <el-option label="7天后删除" value="7" />
              <el-option label="30天后删除" value="30" />
            </el-select>
          </div>
          <div class="setting-row setting-row-control">
            <div>
              <strong>隐私密码</strong>
              <p>可选，用于保护敏感设置。</p>
            </div>
            <el-input v-model="settings.privacyPassword" type="password" show-password class="inline-input" placeholder="未设置" />
          </div>
        </div>
      </section>

      <section v-else-if="activeTab === 'chat'" class="settings-section">
        <div class="section-label">对话体验</div>
        <div class="setting-card">
          <div class="setting-row">
            <div>
              <strong>自动发送</strong>
              <p>输入后按回车直接发送消息。</p>
            </div>
            <el-switch v-model="settings.autoSend" aria-label="自动发送" />
          </div>
          <div class="setting-row">
            <div>
              <strong>消息提示音</strong>
              <p>AI 回复完成后播放提示音。</p>
            </div>
            <el-switch v-model="settings.messageSound" aria-label="消息提示音" />
          </div>
          <div class="setting-row setting-row-control">
            <div>
              <strong>历史保留时长</strong>
              <p>控制本地历史对话的保留时间。</p>
            </div>
            <el-select v-model="settings.historyRetention" class="inline-select">
              <el-option label="1天" value="1" />
              <el-option label="7天" value="7" />
              <el-option label="30天" value="30" />
              <el-option label="永久" value="forever" />
            </el-select>
          </div>
        </div>
      </section>

      <section v-else-if="activeTab === 'model'" class="settings-section">
        <div class="section-label">模型服务</div>
        <div class="section-heading">
          <div>
            <h2>当前连接</h2>
            <p>选择服务商并配置当前浏览器使用的模型连接。</p>
          </div>
          <span class="local-only-badge"><el-icon><Lock /></el-icon> 仅存本机</span>
        </div>
        <div class="provider-grid" role="radiogroup" aria-label="模型服务商">
          <button
            v-for="provider in modelProviderPresets"
            :key="provider.id"
            class="provider-option"
            :class="{ active: modelSettings.provider === provider.id }"
            type="button"
            role="radio"
            :aria-checked="modelSettings.provider === provider.id"
            @click="selectProvider(provider.id)"
          >
            <span class="provider-mark">{{ provider.name.slice(0, 1) }}</span>
            <span class="provider-copy">
              <strong>{{ provider.name }}</strong>
              <small>{{ provider.description }}</small>
            </span>
            <el-icon v-if="modelSettings.provider === provider.id" class="provider-check"><Check /></el-icon>
          </button>
        </div>
        <div v-if="modelSettings.provider !== 'system'" class="connection-form setting-card">
          <el-form-item label="API 地址" required>
            <el-input v-model="modelSettings.baseUrl" placeholder="https://api.example.com/v1" />
          </el-form-item>
          <el-form-item label="API Key" required>
            <el-input v-model="modelSettings.apiKey" type="password" show-password autocomplete="off" placeholder="输入服务商 API Key" />
          </el-form-item>
          <el-form-item label="可用模型" required>
            <el-select v-model="modelSettings.models" multiple filterable allow-create default-first-option class="wide-control" placeholder="输入模型名称后按回车添加" @change="ensureSelectedModel">
              <el-option v-for="model in modelSettings.models" :key="model" :label="model" :value="model" />
            </el-select>
          </el-form-item>
          <el-form-item label="默认模型" required>
            <el-select v-model="modelSettings.selectedModel" filterable allow-create class="wide-control" placeholder="选择默认模型">
              <el-option v-for="model in modelSettings.models" :key="model" :label="model" :value="model" />
            </el-select>
          </el-form-item>
        </div>
        <div v-else class="system-provider-note">
          <el-icon><InfoFilled /></el-icon>
          <span>继续使用服务端配置的默认模型，无需在浏览器中填写 API Key。</span>
        </div>
      </section>

      <section v-else-if="activeTab === 'voice'" class="settings-section">
        <div class="section-label">语音输出</div>
        <div class="setting-card">
          <div class="setting-row setting-row-control">
            <div>
              <strong>语音类型</strong>
              <p>选择语音讲解时使用的声音。</p>
            </div>
            <el-select v-model="settings.voice" class="inline-select">
              <el-option label="默认助手" value="default" />
              <el-option label="女声A" value="female" />
              <el-option label="男声A" value="male" />
              <el-option label="女声B" value="gentle" />
              <el-option label="男声B" value="lively" />
            </el-select>
          </div>
          <div class="setting-row setting-row-control">
            <div>
              <strong>语速</strong>
              <p>调整语音播放的速度。</p>
            </div>
            <div class="compact-slider">
              <el-slider v-model="settings.speed" :min="0.5" :max="2.0" :step="0.1" aria-label="语速" />
              <span>{{ settings.speed.toFixed(1) }}x</span>
            </div>
          </div>
          <div class="setting-row setting-row-control">
            <div>
              <strong>音调</strong>
              <p>调整语音输出的音调。</p>
            </div>
            <div class="compact-slider">
              <el-slider v-model="settings.pitch" :min="0.5" :max="2.0" :step="0.1" aria-label="音调" />
              <span>{{ settings.pitch.toFixed(1) }}x</span>
            </div>
          </div>
        </div>
      </section>

      <footer class="settings-footer">
        <div class="hint"><el-icon><InfoFilled /></el-icon><span>{{ inlineHint }}</span></div>
        <div class="actions">
          <el-button @click="resetSettings">恢复默认</el-button>
          <el-button type="primary" @click="saveSettings">保存设置</el-button>
        </div>
      </footer>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ArrowLeft, Brush, ChatDotRound, Check, Connection, Cpu, Download, FolderOpened, InfoFilled, Key, Lock, Microphone, Monitor, Search, Setting, User } from '@element-plus/icons-vue'
import { applyFontSize, useTheme } from '@/composables/useTheme'
import { colorSchemes, type ColorSchemeId } from '@/themes/presets'
import {
  applyProviderPreset,
  getDefaultModelSettings,
  loadModelSettings,
  modelProviderPresets,
  saveModelSettings,
  type ModelProviderId
} from '@/config/modelSettings'

type TabId = 'general' | 'appearance' | 'privacy' | 'chat' | 'model' | 'voice'
type NavigationItem = {
  id: TabId | 'profile'
  label: string
  icon: Component
  description?: string
  route?: string
}

interface AppSettings {
  colorScheme: ColorSchemeId
  language: 'zh-CN' | 'en'
  fontSize: number
  primaryColor: string
  defaultPermission: boolean
  fullAccess: boolean
  workspaceFolder: string
  compactSidebar: boolean
  showStatusBar: boolean
  storageLocation: 'local' | 'cloud'
  autoDelete: 'never' | '7' | '30'
  privacyPassword: string
  autoSend: boolean
  messageSound: boolean
  historyRetention: '1' | '7' | '30' | 'forever'
  voice: 'default' | 'female' | 'male' | 'gentle' | 'lively'
  speed: number
  pitch: number
}

const { locale } = useI18n()
const { applyColorScheme } = useTheme()
const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const tabs = [
  { id: 'general' as TabId, label: '常规', description: '管理工作区权限、默认目录与基础偏好。', icon: Setting },
  { id: 'appearance' as TabId, label: '外观', description: '调整主题、密度与界面显示方式。', icon: Brush },
  { id: 'privacy' as TabId, label: '隐私', description: '控制数据存储、历史记录与敏感设置。', icon: Lock },
  { id: 'chat' as TabId, label: '对话', description: '管理消息发送与历史对话体验。', icon: ChatDotRound },
  { id: 'model' as TabId, label: '模型与 API', description: '配置当前浏览器使用的模型连接。', icon: Cpu },
  { id: 'voice' as TabId, label: '语音', description: '管理语音讲解的声音与播放参数。', icon: Microphone }
]

const settingsSections: Array<{ label: string; items: NavigationItem[] }> = [
  {
    label: '个人',
    items: [
      { id: 'general', label: '常规', icon: Setting, description: '管理工作区权限、默认目录与基础偏好。' },
      { id: 'profile', label: '个人资料', icon: User, route: '/user' },
      { id: 'appearance', label: '外观', icon: Brush, description: '调整主题、密度与界面显示方式。' },
      { id: 'voice', label: '语音', icon: Microphone, description: '管理语音讲解的声音与播放参数。' },
      { id: 'privacy', label: '隐私', icon: Key, description: '控制数据存储、历史记录与敏感设置。' }
    ]
  },
  {
    label: '工作区',
    items: [
      { id: 'chat', label: '对话', icon: ChatDotRound, description: '管理消息发送与历史对话体验。' },
      { id: 'model', label: '模型与 API', icon: Cpu, description: '配置当前浏览器使用的模型连接。' },
      { id: 'general', label: '导入', icon: Download, description: '管理工作区权限、默认目录与基础偏好。' }
    ]
  },
  {
    label: '集成',
    items: [
      { id: 'model', label: '连接', icon: Connection, description: '配置当前浏览器使用的模型连接。' },
      { id: 'general', label: '浏览器', icon: Monitor, description: '管理工作区权限、默认目录与基础偏好。' },
      { id: 'general', label: '环境', icon: FolderOpened, description: '管理工作区权限、默认目录与基础偏好。' }
    ]
  }
]

const themeOptions = colorSchemes.slice(0, 3).map((theme, index) => ({
  id: theme.id,
  label: index === 0 ? '深色' : index === 1 ? '暖色' : '蓝紫',
  tone: index === 0 ? 'dark' : index === 1 ? 'light' : 'soft',
  previewColor: theme.previewColor
}))

const defaultSettings = (): AppSettings => ({
  colorScheme: 'codex-dark',
  language: 'zh-CN',
  fontSize: 14,
  primaryColor: '#4f46e5',
  defaultPermission: true,
  fullAccess: false,
  workspaceFolder: '',
  compactSidebar: false,
  showStatusBar: true,
  storageLocation: 'local',
  autoDelete: 'never',
  privacyPassword: '',
  autoSend: false,
  messageSound: true,
  historyRetention: '7',
  voice: 'default',
  speed: 1.0,
  pitch: 1.0
})

const settings = ref<AppSettings>(defaultSettings())
const modelSettings = ref(getDefaultModelSettings())
const activeTab = ref<TabId>('general')
const searchTerm = ref('')
const lastSaved = ref<Date | null>(null)
const inlineHint = ref('修改后点击“保存设置”即可生效。')

const currentTab = computed(() => tabs.find((tab) => tab.id === activeTab.value) || tabs[0])
const visibleSections = computed(() => {
  const query = searchTerm.value.trim().toLowerCase()
  if (!query) return settingsSections
  return settingsSections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => item.label.toLowerCase().includes(query))
    }))
    .filter((section) => section.items.length)
})
const accountName = computed(() => userStore.currentUser?.username || '我的账户')
const accountInitial = computed(() => accountName.value.slice(0, 1).toUpperCase())

const lastSavedText = computed(() => {
  if (!lastSaved.value) return '尚未保存'
  return lastSaved.value.toLocaleTimeString('zh-CN', { hour12: false })
})

function applyTheme(): void {
  applyColorScheme(settings.value.colorScheme)
  applyFontSize(settings.value.fontSize)
}

watch(() => settings.value.fontSize, (fontSize) => {
  applyFontSize(fontSize)
})

function handleLanguageChange(newLang: 'zh-CN' | 'en'): void {
  locale.value = newLang
  inlineHint.value = `语言已切换为 ${newLang === 'zh-CN' ? '简体中文' : 'English'}，记得保存设置。`
}

function selectSettingsItem(item: NavigationItem): void {
  if (item.route) {
    router.push(item.route)
    return
  }
  activeTab.value = item.id as TabId
}

function loadSettings(): void {
  const saved = localStorage.getItem('appSettings')
  if (!saved) return
  try {
    const parsed = JSON.parse(saved) as Partial<AppSettings> & { theme?: unknown }
    const { theme: _legacyTheme, ...savedSettings } = parsed
    settings.value = { ...defaultSettings(), ...savedSettings }
    locale.value = settings.value.language
    applyTheme()
    inlineHint.value = '已读取本地设置。'
  } catch {
    settings.value = defaultSettings()
    inlineHint.value = '本地设置解析失败，已使用默认配置。'
  }
}

function saveSettings(): void {
  if (modelSettings.value.provider !== 'system') {
    if (!modelSettings.value.baseUrl.trim() || !modelSettings.value.apiKey.trim() || !modelSettings.value.selectedModel.trim()) {
      activeTab.value = 'model'
      inlineHint.value = '请完整填写 API 地址、API Key 和默认模型。'
      return
    }
    if (!/^https?:\/\//i.test(modelSettings.value.baseUrl.trim())) {
      activeTab.value = 'model'
      inlineHint.value = 'API 地址必须以 http:// 或 https:// 开头。'
      return
    }
  }
  localStorage.setItem('appSettings', JSON.stringify(settings.value))
  saveModelSettings(modelSettings.value)
  applyTheme()
  lastSaved.value = new Date()
  inlineHint.value = '设置已保存。'
}

function resetSettings(): void {
  settings.value = defaultSettings()
  modelSettings.value = getDefaultModelSettings()
  locale.value = 'zh-CN'
  localStorage.removeItem('appSettings')
  saveModelSettings(modelSettings.value)
  applyTheme()
  lastSaved.value = new Date()
  inlineHint.value = '已恢复默认设置。'
}

onMounted(() => {
  loadSettings()
  modelSettings.value = loadModelSettings()
  void userStore.loadCurrentUser()
})

function selectProvider(provider: ModelProviderId): void {
  modelSettings.value = applyProviderPreset(modelSettings.value, provider)
  inlineHint.value = provider === 'system' ? '已选择服务端默认模型。' : '请检查 API Key 后保存设置。'
}

function ensureSelectedModel(models: string[]): void {
  if (!models.includes(modelSettings.value.selectedModel)) {
    modelSettings.value.selectedModel = models[0] || ''
  }
}
</script>

<style scoped>
.settings-view {
  position: relative;
  width: 100%;
  height: 100%;
  padding: var(--page-padding-y) var(--page-padding-x);
  display: flex;
  flex-direction: column;
  gap: var(--page-gap);
  color: var(--text-primary);
  overflow-y: auto;
  overflow-x: hidden;
}

.glass-panel {
  position: relative;
  z-index: 1;
  background: color-mix(in srgb, var(--bg-card) 90%, transparent);
  border: 1px solid var(--border-light);
  border-radius: 8px;
  box-shadow: var(--shadow-sm);
}

.page-header {
  padding: 16px 18px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.page-header h1 {
  margin: 0;
  font-size: 24px;
}

.page-header p {
  margin: 8px 0 0;
  color: var(--text-secondary);
  font-size: 14px;
}

.status-chip {
  border-radius: 999px;
  background: var(--primary-fade);
  color: var(--primary-color);
  padding: 6px 12px;
  font-size: 12px;
  white-space: nowrap;
}

.tabs-bar {
  padding: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.tab-btn {
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
}

.tab-btn.active {
  background: var(--primary-fade);
  border-color: var(--primary-line);
  color: var(--primary-color);
}

.content-panel {
  padding: 16px;
}

.form-grid {
  display: grid;
  gap: 16px;
}

.model-settings {
  display: grid;
  gap: 20px;
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.section-heading h2 {
  margin: 0;
  font-size: 18px;
}

.section-heading p {
  margin: 5px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.local-only-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
  padding: 5px 9px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 12px;
}

.provider-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.provider-option {
  position: relative;
  min-height: 90px;
  padding: 12px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-card);
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  transition: var(--transition);
}

.provider-option:hover {
  border-color: var(--border-hover);
  transform: translateY(-1px);
}

.provider-option.active {
  border-color: var(--primary-color);
  background: var(--primary-fade);
  box-shadow: 0 0 0 1px var(--primary-line);
}

.provider-mark {
  display: grid;
  width: 26px;
  height: 26px;
  margin-bottom: 9px;
  place-items: center;
  border-radius: 6px;
  background: var(--primary-color);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}

.provider-copy {
  display: grid;
  gap: 3px;
}

.provider-copy strong {
  font-size: 13px;
}

.provider-copy small {
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.35;
}

.provider-check {
  position: absolute;
  top: 10px;
  right: 10px;
  color: var(--primary-color);
}

.connection-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 18px;
  padding-top: 18px;
  border-top: 1px solid var(--border-light);
}

.connection-form :deep(.el-select) {
  width: 100%;
}

.system-provider-note {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--primary-fade);
  color: var(--text-secondary);
  font-size: 13px;
}

.slider-box {
  display: flex;
  align-items: center;
  gap: 10px;
}

.slider-box span {
  width: 58px;
  color: var(--text-secondary);
  font-size: 12px;
}

.switch-row {
  border: 1px solid var(--border-light);
  border-radius: 10px;
  padding: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.switch-row strong {
  display: block;
}

.switch-row p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.footer-bar {
  padding: 12px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.hint {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.actions {
  display: flex;
  gap: 8px;
}

.scheme-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.scheme-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid var(--border-light);
  border-radius: 10px;
  background: var(--bg-card);
  color: var(--text-regular);
  font-size: 13px;
  cursor: pointer;
  transition: var(--transition);
}

.scheme-chip:hover {
  border-color: var(--border-hover);
  transform: translateY(-1px);
}

.scheme-chip.active {
  border-color: var(--primary-line);
  background: var(--primary-fade);
  color: var(--primary-color);
  box-shadow: 0 0 0 1px var(--primary-line);
}

.scheme-dot {
  width: 18px;
  height: 18px;
  border-radius: 6px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  flex-shrink: 0;
}

@media (max-width: 760px) {
  .settings-view {
    padding: var(--space-md);
    gap: var(--space-md);
  }

  .page-header {
    flex-direction: column;
  }

  .footer-bar {
    flex-direction: column;
    align-items: stretch;
  }

  .actions {
    justify-content: flex-end;
  }

  .provider-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .connection-form {
    grid-template-columns: 1fr;
  }

  .section-heading {
    flex-direction: column;
  }
}

@media (min-width: 761px) and (max-width: 1100px) {
  .provider-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

/* 与其他管理页面统一为紧凑工具栏和连续工作区 */
.settings-view {
  padding: 12px;
  gap: 10px;
}

.page-header {
  box-sizing: border-box;
  min-height: 50px;
  padding: 7px 12px;
  align-items: center;
  gap: 10px;
  border-radius: 7px;
  box-shadow: none;
}

.page-header h1 {
  font-size: 18px;
  line-height: 1.2;
}

.page-header p {
  display: none;
}

.status-chip {
  height: 28px;
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  padding: 0 9px;
  font-size: 11px;
}

.tabs-bar {
  min-height: 46px;
  box-sizing: border-box;
  padding: 5px 8px;
  gap: 4px;
  border-radius: 7px;
  box-shadow: none;
}

.tab-btn {
  height: 34px;
  padding: 0 10px;
  gap: 5px;
  border-radius: 7px;
  font-size: 12px;
}

.content-panel {
  padding: 12px;
  border-radius: 7px;
  box-shadow: none;
}

.form-grid {
  gap: 12px;
}

.model-settings {
  gap: 12px;
}

.footer-bar {
  min-height: 50px;
  box-sizing: border-box;
  padding: 7px 12px;
  border-radius: 7px;
  box-shadow: none;
}

.actions :deep(.el-button) {
  height: 30px;
  padding: 0 12px;
  border-radius: 6px;
  font-size: 12px;
}
</style>

<style scoped>
/* 个人设置视觉层：窄侧栏承载定位，主区域保持安静的纵向阅读节奏。 */
.settings-view {
  width: 100%;
  height: 100%;
  min-height: 0;
  padding: 0;
  display: grid;
  grid-template-columns: minmax(210px, 250px) minmax(0, 1fr);
  overflow: hidden;
  background: var(--bg-app);
  color: var(--text-primary);
}

.settings-rail {
  min-width: 0;
  min-height: 0;
  padding: 22px 12px 14px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-light);
  background: color-mix(in srgb, var(--bg-sidebar) 78%, var(--bg-app));
}

.back-to-app,
.rail-account,
.settings-nav-item {
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  cursor: pointer;
  transition: var(--transition);
}

.back-to-app {
  min-height: 34px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  border-radius: var(--radius-control);
  font-size: 12px;
}

.back-to-app:hover,
.back-to-app:focus-visible {
  color: var(--text-primary);
  background: var(--bg-input);
}

.back-to-app .el-icon {
  font-size: 15px;
}

.settings-search {
  height: 36px;
  margin: 18px 0 14px;
  padding: 0 11px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--bg-input) 88%, transparent);
  color: var(--text-muted);
}

.settings-search:focus-within {
  box-shadow: 0 0 0 1px var(--primary-color) inset;
  color: var(--primary-color);
}

.settings-search input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: 12px;
}

.settings-search input::placeholder {
  color: var(--text-muted);
}

.settings-nav {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  padding: 0 1px 12px;
}

.settings-nav-section {
  margin-bottom: 20px;
}

.settings-nav-section h2 {
  padding: 0 10px;
  margin: 0 0 7px;
  color: var(--text-muted);
  font: 600 11px/1.4 var(--font-sans);
  letter-spacing: .04em;
}

.settings-nav-item {
  width: 100%;
  min-height: 35px;
  padding: 0 10px;
  display: flex;
  align-items: center;
  gap: 9px;
  border-radius: 9px;
  text-align: left;
  font-size: 12px;
}

.settings-nav-item .el-icon {
  flex: 0 0 16px;
  color: var(--text-muted);
  font-size: 15px;
}

.settings-nav-item:hover,
.settings-nav-item:focus-visible {
  color: var(--text-primary);
  background: var(--bg-input);
}

.settings-nav-item:hover .el-icon,
.settings-nav-item:focus-visible .el-icon {
  color: var(--primary-color);
}

.settings-nav-item.active {
  color: var(--text-primary);
  background: color-mix(in srgb, var(--primary-color) 12%, var(--bg-card));
  box-shadow: inset 2px 0 0 var(--primary-color);
}

.settings-nav-item.active .el-icon {
  color: var(--primary-color);
}

.settings-nav-item .item-arrow {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 12px;
  transform: rotate(180deg);
}

.settings-empty {
  padding: 12px 10px;
  color: var(--text-muted);
  font-size: 12px;
}

.rail-account {
  width: 100%;
  min-height: 54px;
  padding: 8px;
  display: flex;
  align-items: center;
  gap: 9px;
  border-top: 1px solid var(--border-light);
  border-radius: 0;
  text-align: left;
}

.rail-account:hover,
.rail-account:focus-visible {
  background: var(--bg-input);
}

.rail-avatar {
  flex: 0 0 auto;
  background: var(--primary-color);
  color: var(--on-primary);
  font-weight: 700;
}

.rail-account-copy {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 1px;
}

.rail-account-copy strong,
.rail-account-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rail-account-copy strong {
  color: var(--text-primary);
  font-size: 12px;
}

.rail-account-copy small {
  color: var(--text-muted);
  font-size: 10px;
}

.rail-account > .el-icon {
  color: var(--text-muted);
  font-size: 13px;
  transform: rotate(180deg);
}

.settings-content {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 42px clamp(24px, 5vw, 76px) 56px;
}

.settings-header,
.settings-section,
.settings-footer {
  width: min(100%, 920px);
  margin: 0 auto;
}

.settings-header {
  min-height: 84px;
  padding-bottom: 24px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  border-bottom: 1px solid var(--border-light);
}

.settings-eyebrow {
  display: block;
  margin-bottom: 8px;
  color: var(--primary-color);
  font: 10px/1 var(--font-mono);
  letter-spacing: .12em;
}

.settings-header h1 {
  margin: 0;
  color: var(--text-primary);
  font-size: clamp(23px, 2.2vw, 30px);
  line-height: 1.15;
}

.settings-header p {
  margin: 8px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.settings-header-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}

.save-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: 11px;
  white-space: nowrap;
}

.save-state i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
}

.save-state.saved i { background: var(--success); }

.header-save {
  height: 34px;
  padding: 0 13px;
  border-radius: 8px;
  font-size: 12px;
}

.settings-section {
  padding-top: 30px;
}

.section-label {
  margin: 0 0 10px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 650;
}

.settings-section > .section-label:not(:first-child) {
  margin-top: 30px;
}

.setting-card {
  overflow: hidden;
  border: 1px solid var(--border-light);
  border-radius: 13px;
  background: color-mix(in srgb, var(--surface-solid) 92%, transparent);
}

.setting-row {
  min-height: 78px;
  padding: 15px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  border-bottom: 1px solid color-mix(in srgb, var(--border-light) 82%, transparent);
}

.setting-row:last-child { border-bottom: 0; }

.setting-row > div:first-child {
  min-width: 0;
}

.setting-row strong {
  display: block;
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 650;
}

.setting-row p {
  max-width: 620px;
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.45;
  text-wrap: pretty;
}

.setting-row-control { min-height: 72px; }

.inline-input,
.inline-select {
  width: min(100%, 280px);
  flex: 0 0 280px;
}

.compact-slider {
  width: min(100%, 250px);
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 0 0 250px;
}

.compact-slider .el-slider { flex: 1; }

.compact-slider > span {
  width: 40px;
  color: var(--text-secondary);
  font: 11px var(--font-mono);
  text-align: right;
}

.theme-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.theme-option {
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--border-light);
  border-radius: 12px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
  transition: var(--transition);
}

.theme-option:hover,
.theme-option:focus-visible {
  border-color: var(--border-hover);
  transform: translateY(-1px);
}

.theme-option.active {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 1px var(--primary-color);
}

.theme-preview {
  position: relative;
  height: 116px;
  padding: 24px 14px 12px;
  display: grid;
  grid-template-columns: 38px 1fr;
  grid-template-rows: 8px 8px 1fr;
  gap: 8px 10px;
  overflow: hidden;
  background: #242536;
}

.theme-preview::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 48px;
  background: color-mix(in srgb, #ffffff 7%, transparent);
}

.theme-preview i,
.theme-preview b {
  position: relative;
  z-index: 1;
  display: block;
  border-radius: 999px;
  background: color-mix(in srgb, #ffffff 28%, transparent);
}

.theme-preview i:nth-child(1) { grid-row: 1 / span 3; width: 26px; height: 100%; border-radius: 4px; background: color-mix(in srgb, var(--theme-accent) 38%, transparent); }
.theme-preview i:nth-child(2) { grid-column: 2; width: 84px; }
.theme-preview i:nth-child(3) { grid-column: 2; width: 58px; opacity: .6; }
.theme-preview b:nth-of-type(1) { grid-column: 2; grid-row: 3; align-self: start; height: 42px; border-radius: 7px; background: color-mix(in srgb, #ffffff 86%, transparent); }
.theme-preview b:nth-of-type(2) { position: absolute; z-index: 2; right: 15px; bottom: 15px; width: 28px; height: 5px; background: var(--theme-accent); }

.theme-light .theme-preview { background: #f4f3f0; }
.theme-light .theme-preview::after { background: color-mix(in srgb, #ffffff 36%, transparent); }
.theme-light .theme-preview i { background: color-mix(in srgb, #56545a 25%, transparent); }
.theme-light .theme-preview b:nth-of-type(1) { background: #ffffff; }
.theme-soft .theme-preview { background: #e9eafa; }
.theme-soft .theme-preview::after { background: color-mix(in srgb, #ffffff 48%, transparent); }
.theme-soft .theme-preview i { background: color-mix(in srgb, #33344d 24%, transparent); }
.theme-soft .theme-preview b:nth-of-type(1) { background: #ffffff; }

.theme-option-footer {
  min-height: 42px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--surface-solid);
  font-size: 12px;
}

.theme-option-footer strong { color: var(--text-primary); font-weight: 600; }
.theme-option-footer .el-icon { color: var(--primary-color); }

.section-heading {
  margin-bottom: 14px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.section-heading h2 {
  margin: 0;
  color: var(--text-primary);
  font-size: 15px;
}

.section-heading p {
  margin: 5px 0 0;
  color: var(--text-secondary);
  font-size: 11px;
}

.local-only-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 8px;
  border: 1px solid var(--border-light);
  border-radius: 7px;
  color: var(--text-secondary);
  font-size: 10px;
  white-space: nowrap;
}

.provider-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.provider-option {
  position: relative;
  min-height: 92px;
  padding: 12px;
  border: 1px solid var(--border-light);
  border-radius: 10px;
  background: var(--surface-solid);
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  transition: var(--transition);
}

.provider-option:hover,
.provider-option:focus-visible {
  border-color: var(--border-hover);
  transform: translateY(-1px);
}

.provider-option.active {
  border-color: var(--primary-color);
  background: var(--primary-fade);
  box-shadow: 0 0 0 1px var(--primary-line);
}

.provider-mark {
  width: 25px;
  height: 25px;
  margin-bottom: 8px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: var(--primary-color);
  color: var(--on-primary);
  font-size: 11px;
  font-weight: 700;
}

.provider-copy { display: grid; gap: 3px; }
.provider-copy strong { font-size: 12px; }
.provider-copy small { color: var(--text-secondary); font-size: 10px; line-height: 1.35; }
.provider-check { position: absolute; top: 10px; right: 10px; color: var(--primary-color); }

.connection-form {
  padding: 18px 16px 2px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 2px 18px;
}

.connection-form :deep(.el-form-item) { margin-bottom: 14px; }
.connection-form :deep(.el-form-item__label) { color: var(--text-primary); font-size: 11px; font-weight: 600; }
.connection-form :deep(.el-select) { width: 100%; }
.wide-control { width: 100%; }

.system-provider-note {
  padding: 13px 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--border-light);
  border-radius: 10px;
  background: var(--primary-fade);
  color: var(--text-secondary);
  font-size: 11px;
}

.settings-footer {
  padding-top: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.hint {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--text-muted);
  font-size: 11px;
}

.hint span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hint .el-icon { color: var(--text-secondary); }
.actions { display: flex; gap: 8px; flex-shrink: 0; }
.actions :deep(.el-button) { height: 34px; padding: 0 13px; border-radius: 8px; font-size: 12px; }

.setting-row :deep(.el-input__wrapper),
.connection-form :deep(.el-input__wrapper),
.setting-row :deep(.el-select .el-input__wrapper) {
  min-height: 34px;
  border: 1px solid var(--border-light) !important;
  border-radius: 8px !important;
  background: var(--bg-input) !important;
}

.setting-row :deep(.el-input__inner),
.connection-form :deep(.el-input__inner) {
  color: var(--text-primary);
  font-size: 11px;
}

.setting-row :deep(.el-input__inner::placeholder),
.connection-form :deep(.el-input__inner::placeholder) { color: var(--text-disabled); }

.setting-row :deep(.el-radio-button__inner) {
  padding: 8px 11px;
  border-color: var(--border-light);
  background: var(--bg-input);
  color: var(--text-secondary);
  font-size: 11px;
  box-shadow: none;
}

.setting-row :deep(.el-radio-button:first-child .el-radio-button__inner) { border-radius: 7px 0 0 7px; }
.setting-row :deep(.el-radio-button:last-child .el-radio-button__inner) { border-radius: 0 7px 7px 0; }
.setting-row :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) { color: var(--on-primary); background: var(--primary-color); border-color: var(--primary-color); box-shadow: none; }
.setting-row :deep(.el-switch.is-checked .el-switch__core) { border-color: var(--primary-color); background: var(--primary-color); }

@media (max-width: 980px) {
  .settings-view { grid-template-columns: 190px minmax(0, 1fr); }
  .settings-content { padding-right: 28px; padding-left: 28px; }
  .provider-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 700px) {
  .settings-view { display: block; overflow: auto; }
  .settings-rail { min-height: auto; padding: 12px; border-right: 0; border-bottom: 1px solid var(--border-light); }
  .settings-nav { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 2px; }
  .settings-nav-section { min-width: max-content; margin: 0; }
  .settings-nav-section h2 { display: none; }
  .settings-nav-item { width: auto; min-height: 32px; padding: 0 9px; white-space: nowrap; }
  .settings-nav-item .item-arrow { display: none; }
  .rail-account { display: none; }
  .settings-search { margin: 12px 0 10px; }
  .settings-content { height: auto; overflow: visible; padding: 26px 16px 36px; }
  .settings-header { align-items: flex-start; flex-direction: column; gap: 18px; }
  .settings-header-actions { width: 100%; justify-content: space-between; }
  .theme-grid { grid-template-columns: 1fr; }
  .theme-preview { height: 94px; }
  .setting-row,
  .setting-row-control { align-items: flex-start; flex-direction: column; gap: 12px; }
  .inline-input, .inline-select, .compact-slider { width: 100%; flex-basis: auto; }
  .compact-slider { max-width: none; }
  .provider-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .connection-form { grid-template-columns: 1fr; }
  .settings-footer { align-items: stretch; flex-direction: column; }
  .actions { justify-content: flex-end; }
}

@media (prefers-reduced-motion: reduce) {
  .settings-view *, .settings-view *::before, .settings-view *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
}
</style>
