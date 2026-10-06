<template>
  <div class="history-view">
    <header class="history-header">
      <div>
        <span class="history-eyebrow">HISTORY</span>
        <h1>历史记录</h1>
      </div>
    </header>

    <section class="history-toolbar" aria-label="历史记录筛选">
      <label class="history-search">
        <el-icon aria-hidden="true"><Search /></el-icon>
        <input v-model="searchKeyword" type="search" placeholder="搜索历史记录..." />
      </label>
      <div class="history-toolbar-actions">
        <button type="button" class="history-action" :disabled="refreshing" @click="refresh">
          <el-icon aria-hidden="true"><Refresh /></el-icon>
          <span>{{ refreshing ? '刷新中' : '刷新' }}</span>
        </button>
        <button type="button" class="history-action history-action--danger" @click="clearAll">
          <el-icon aria-hidden="true"><Delete /></el-icon>
          <span>清空对话</span>
        </button>
      </div>
    </section>

    <nav class="history-tabs" aria-label="历史记录类型">
      <button
        data-testid="history-tab-conversations"
        type="button"
        :class="{ active: activeTab === 'conversations' }"
        @click="selectTab('conversations')"
      >
        <el-icon><ChatLineRound /></el-icon>
        <span>对话历史</span>
      </button>
      <button
        data-testid="history-tab-files"
        type="button"
        :class="{ active: activeTab === 'files' }"
        @click="selectTab('files')"
      >
        <el-icon><Document /></el-icon>
        <span>文件历史</span>
      </button>
      <button
        data-testid="history-tab-acg"
        type="button"
        :class="{ active: activeTab === 'acg' }"
        @click="selectTab('acg')"
      >
        <el-icon><Monitor /></el-icon>
        <span>ACG 历史</span>
      </button>
    </nav>

    <main class="history-content">
      <ConversationList
        v-if="activeTab === 'conversations'"
        :key="`conversations-${refreshKey}`"
        :search-keyword="searchKeyword"
        workspace-mode="chat"
        @select="handleSelectConversation"
      />
      <FileHistoryList
        v-else-if="activeTab === 'files'"
        :key="`files-${refreshKey}`"
        :search-keyword="searchKeyword"
      />
      <AcgHistoryPanel v-else :key="`acg-${refreshKey}`" />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatLineRound, Delete, Document, Monitor, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ConversationList from '@/components/ConversationList.vue'
import FileHistoryList from '@/components/FileHistoryList.vue'
import AcgHistoryPanel from '@/components/history/AcgHistoryPanel.vue'
import { conversationApi } from '@/services/api/conversation'
import { useUserStore } from '@/stores/user'

type HistoryTab = 'conversations' | 'files' | 'acg'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const searchKeyword = ref('')
const refreshKey = ref(0)
const refreshing = ref(false)

const normalizeTab = (value: unknown): HistoryTab => {
  return value === 'files' || value === 'acg' ? value : 'conversations'
}

const activeTab = computed<HistoryTab>(() => normalizeTab(route.query.tab))

const selectTab = (tab: HistoryTab) => {
  void router.replace({
    path: '/history',
    query: tab === 'conversations' ? {} : { tab },
  })
}

watch(() => route.query.tab, value => {
  if (value !== undefined && (value !== 'files' && value !== 'acg')) {
    void router.replace({ path: '/history', query: {} })
  }
}, { immediate: true })

const handleSelectConversation = (conversation: { id: string; contextId?: string }) => {
  const contextId = conversation.contextId || conversation.id
  void router.push({ path: '/chat', query: { contextId, workspace: 'chat' } })
}

const refresh = async () => {
  if (refreshing.value) return
  refreshing.value = true
  refreshKey.value += 1
  await nextTick()
  refreshing.value = false
  ElMessage.success('已刷新')
}

const clearAll = async () => {
  try {
    await ElMessageBox.confirm('确定要清空所有对话历史吗？此操作不可恢复。', '确认清空', {
      confirmButtonText: '确定清空',
      cancelButtonText: '取消',
      type: 'warning',
      customClass: 'destructive-confirm',
    })
    const userId = userStore.currentUser?.id
    if (!userId) {
      ElMessage.error('无法获取用户信息')
      return
    }
    await conversationApi.deleteAllConversations(userId, 'chat')
    ElMessage.success('对话历史已清空')
    refresh()
  } catch (error: unknown) {
    if (error !== 'cancel') {
      const message = error instanceof Error ? error.message : '未知错误'
      ElMessage.error(`清空失败：${message}`)
    }
  }
}
</script>

<style scoped lang="scss">
/* 头部与工具栏的排版对齐 ProjectListView（工程项目页）：眉标 + 大标题 + 下挂工具栏行 */
.history-view {
  width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 34px clamp(24px, 5vw, 76px) 28px;
  box-sizing: border-box;
  background: var(--bg-app);
  color: var(--text-primary);
}

.history-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  max-width: 1040px;
  width: 100%;
  margin: 0 auto;
  padding-bottom: 28px;
}

.history-eyebrow {
  color: var(--primary-color);
  font: 10px var(--font-mono, monospace);
  letter-spacing: .14em;
}

.history-header h1 {
  margin: 8px 0 5px;
  font-size: 25px;
  line-height: 1.2;
}

.history-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  max-width: 1040px;
  width: 100%;
  margin: 0 auto;
  padding: 14px 0;
}

.history-search {
  display: flex;
  align-items: center;
  gap: 10px;
  box-sizing: border-box;
  width: min(460px, 100%);
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid var(--border-light);
  border-radius: 9px;
  color: var(--text-muted);
  background: color-mix(in srgb, var(--surface-subtle) 82%, transparent);
  transition: border-color 160ms var(--ease-out), background-color 160ms var(--ease-out), box-shadow 160ms var(--ease-out);
}

.history-search:focus-within {
  border-color: color-mix(in srgb, var(--primary-color) 58%, var(--border-light));
  background: var(--surface-solid);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary-color) 12%, transparent);
}

.history-search .el-icon {
  flex: 0 0 auto;
  font-size: 16px;
}

.history-search input {
  min-width: 0;
  width: 100%;
  border: 0;
  outline: 0;
  color: var(--text-primary);
  background: transparent;
  font-size: 13px;
}

.history-search input::placeholder {
  color: var(--text-muted);
  opacity: .9;
}

.history-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.history-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 34px;
  padding: 0 12px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  color: var(--text-secondary);
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 11px;
  transition: border-color 160ms var(--ease-out), color 160ms var(--ease-out), background-color 160ms var(--ease-out);
}

.history-action:hover:not(:disabled),
.history-action:focus-visible {
  color: var(--text-primary);
  border-color: var(--primary-line);
  background: var(--surface-subtle);
  outline: none;
}

.history-action:disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

.history-action--danger { color: var(--danger); }
.history-action--danger:hover:not(:disabled),
.history-action--danger:focus-visible {
  color: var(--danger);
  border-color: color-mix(in srgb, var(--danger) 35%, var(--border-light));
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

.history-tabs {
  flex: none;
  min-height: 42px;
  display: flex;
  gap: 3px;
  max-width: 1040px;
  width: 100%;
  margin: 0 auto;
  padding: 3px 6px 0;
  border-bottom: 1px solid var(--wb-border-soft);
  background: color-mix(in srgb, var(--wb-surface-pane) 58%, transparent);
}

.history-tabs button {
  height: 39px;
  gap: 6px;
  padding: 0 13px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--wb-text-secondary);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  transition: var(--transition);
}

.history-tabs button:hover,
.history-tabs button.active { color: var(--wb-accent); }
.history-tabs button:hover { background: color-mix(in srgb, var(--wb-accent-soft) 48%, transparent); }
.history-tabs button.active { border-bottom-color: var(--wb-accent); font-weight: 650; }

.history-tabs button:focus-visible,
.history-action:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: 2px;
}

.history-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  max-width: 1040px;
  width: 100%;
  margin: 0 auto;
  padding: 14px 0 16px;
  scrollbar-gutter: stable;
}

.history-content :deep(.conversation-list-container),
.history-content :deep(.file-history-list) {
  min-height: 0;
}

/* 列表卡片对齐 ProjectListView 的行样式：默认透明无边框，悬停浮起 */
.history-content :deep(.list-content) {
  gap: 4px;
}

.history-content :deep(.conversation-item),
.history-content :deep(.file-item) {
  min-height: 82px;
  padding: 14px 16px;
  border: 1px solid transparent;
  border-radius: 12px;
  background: transparent;
  box-shadow: none;
  transition: background-color 180ms var(--ease-out), border-color 180ms var(--ease-out), box-shadow 180ms var(--ease-out);
}

.history-content :deep(.conversation-item:hover),
.history-content :deep(.file-item:hover) {
  border-color: color-mix(in srgb, var(--primary-line) 42%, var(--border-light));
  background: color-mix(in srgb, var(--primary-fade) 56%, transparent);
  box-shadow: var(--shadow-sm);
}

.history-content :deep(.item-left .avatar-wrapper),
.history-content :deep(.item-left .file-icon-wrapper) {
  width: 38px;
  height: 38px;
  border: 1px solid color-mix(in srgb, var(--primary-line) 82%, var(--border-light));
  border-radius: 10px;
  color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-fade) 72%, var(--surface-subtle));
  box-shadow: none;
  transition: background-color 180ms var(--ease-out), border-color 180ms var(--ease-out), transform 180ms var(--ease-out);
}

.history-content :deep(.avatar-text) { font-size: 16px; }

.history-content :deep(.conversation-item:hover .item-left .avatar-wrapper),
.history-content :deep(.file-item:hover .item-left .file-icon-wrapper) {
  border-color: var(--primary-line);
  background: var(--primary-fade);
  transform: translateY(-1px);
}

.history-content :deep(.item-header .title),
.history-content :deep(.item-header .filename) {
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
}

.history-content :deep(.item-header .time) {
  color: var(--text-secondary);
  font-size: 11px;
}

.history-content :deep(.item-main) { gap: 6px; }

.history-content :deep(.item-preview),
.history-content :deep(.item-meta) {
  color: var(--text-muted);
  font-size: 11px;
}

.history-content :deep(.empty-state) {
  min-height: 280px;
  border: 1px dashed var(--wb-border);
  border-radius: var(--wb-radius-section);
  background: color-mix(in srgb, var(--wb-surface-section) 72%, transparent);
}

.history-content :deep(.loading-state) {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 0;
  min-height: 0;
  border: 0;
  background: transparent;
}

.history-content :deep(.skeleton-item) {
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 82px;
  padding: 14px 16px;
  box-sizing: border-box;
  border: 1px solid transparent;
  border-radius: 12px;
  background: color-mix(in srgb, var(--surface-subtle) 60%, transparent);
}

.history-content :deep(.skeleton-avatar),
.history-content :deep(.skeleton-icon),
.history-content :deep(.skeleton-line) {
  background: #111111;
  animation: none;
}

.history-content :deep(.skeleton-avatar),
.history-content :deep(.skeleton-icon) {
  width: 38px;
  height: 38px;
  border-radius: 10px;
}

.history-content :deep(.skeleton-content) { min-width: 0; gap: 10px; }
.history-content :deep(.skeleton-title) { width: min(34%, 260px); height: 10px; border-radius: 5px; }
.history-content :deep(.skeleton-text) { width: min(58%, 460px); height: 7px; border-radius: 4px; }
.history-content :deep(.skeleton-item:nth-child(2) .skeleton-title) { width: min(27%, 205px); }
.history-content :deep(.skeleton-item:nth-child(2) .skeleton-text) { width: min(45%, 350px); }
.history-content :deep(.skeleton-item:nth-child(3) .skeleton-title) { width: min(39%, 300px); }
.history-content :deep(.skeleton-item:nth-child(3) .skeleton-text) { width: min(51%, 400px); }


.history-content :deep(.empty-state .empty-icon) {
  border: 1px solid color-mix(in srgb, var(--wb-accent) 24%, var(--wb-border-soft));
  background: var(--wb-accent-soft);
}

.history-content :deep(.empty-state .empty-text) { color: var(--wb-text); }
.history-content :deep(.empty-state .empty-hint) { color: var(--wb-text-secondary); }

@media (max-width: 720px) {
  .history-view { padding: 24px 18px 28px; }
  .history-toolbar { align-items: stretch; flex-direction: column; gap: 12px; padding: 12px 0; }
  .history-search { width: 100%; }
  .history-toolbar-actions { justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
  .history-tabs { overflow-x: auto; }
  .history-tabs button { flex: 0 0 auto; }
}
</style>
