<template>
  <div class="history-view" data-max-width="1400px">
    <WorkspacePageHero eyebrow="HISTORY" title="历史记录" description="查看和管理对话、文件与 ACG 运行记录">
      <template #actions>
        <div class="history-actions">
          <label class="history-search">
            <el-icon><Search /></el-icon>
            <input v-model="searchKeyword" type="search" placeholder="搜索历史记录..." />
          </label>
          <button type="button" class="history-action" :disabled="refreshing" @click="refresh">
            <el-icon><Refresh /></el-icon>
            <span>{{ refreshing ? '刷新中' : '刷新' }}</span>
          </button>
          <button type="button" class="history-action history-action--danger" @click="clearAll">
            <el-icon><Delete /></el-icon>
            <span>清空对话</span>
          </button>
        </div>
      </template>
    </WorkspacePageHero>

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
import WorkspacePageHero from '@/components/app/WorkspacePageHero.vue'
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
.history-view {
  width: min(100%, 1400px);
  height: 100%;
  min-height: 0;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 0 clamp(18px, 3.4vw, 56px) 28px;
  box-sizing: border-box;
  background: var(--wb-surface-shell);
  color: var(--wb-text);
}

.history-view :deep(.workspace-page-hero) {
  width: 100%;
}

.history-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 7px;
}

.history-search {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 226px;
  height: 34px;
  padding: 0 10px;
  box-sizing: border-box;
  border: 1px solid var(--wb-border-soft);
  border-radius: var(--wb-radius-sm);
  background: var(--wb-surface-inset);
  color: var(--wb-text-secondary);
  transition: var(--transition);
}

.history-search:focus-within {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--wb-accent) 12%, transparent);
}

.history-search input {
  width: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--wb-text);
  font: inherit;
  font-size: 12px;
}

.history-search input::placeholder { color: var(--wb-text-muted); }

.history-action {
  height: 34px;
  padding: 0 11px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--wb-border-soft);
  border-radius: var(--wb-radius-sm);
  background: var(--wb-surface-section);
  color: var(--wb-text-secondary);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  transition: var(--transition);
}

.history-action:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--wb-accent) 36%, var(--wb-border-soft));
  color: var(--wb-accent);
  background: var(--wb-hover);
}

.history-action:disabled { cursor: wait; opacity: .62; }
.history-action--danger { color: var(--wb-danger); }
.history-action--danger:hover:not(:disabled) { border-color: color-mix(in srgb, var(--wb-danger) 35%, var(--wb-border-soft)); color: var(--wb-danger); background: var(--danger-fade); }

.history-tabs {
  flex: none;
  min-height: 42px;
  display: flex;
  gap: 3px;
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
  padding: 2px 0 16px;
  scrollbar-gutter: stable;
}

.history-content :deep(.conversation-list-container),
.history-content :deep(.file-history-list) {
  min-height: 0;
}

.history-content :deep(.list-content) {
  gap: 8px;
}

.history-content :deep(.conversation-item),
.history-content :deep(.file-item) {
  min-height: 70px;
  padding: 13px 14px;
  border: 1px solid var(--wb-border-soft);
  border-radius: var(--wb-radius-section);
  background: var(--wb-surface-section);
  box-shadow: var(--wb-shadow-section);
  transition: var(--transition);
}

.history-content :deep(.conversation-item:last-child),
.history-content :deep(.file-item:last-child) { border-bottom: 1px solid var(--wb-border-soft); }

.history-content :deep(.conversation-item:hover),
.history-content :deep(.file-item:hover) {
  border-color: color-mix(in srgb, var(--wb-accent) 38%, var(--wb-border-soft));
  background: color-mix(in srgb, var(--wb-accent-soft) 24%, var(--wb-surface-section));
  box-shadow: var(--shadow-sm);
}

.history-content :deep(.item-left .avatar-wrapper),
.history-content :deep(.item-left .file-icon-wrapper) {
  border-color: color-mix(in srgb, var(--wb-accent) 30%, var(--wb-border-soft));
  background: var(--wb-surface-inset);
}

.history-content :deep(.item-header .title),
.history-content :deep(.item-header .filename) { color: var(--wb-text); }
.history-content :deep(.item-preview),
.history-content :deep(.item-meta) { color: var(--wb-text-secondary); }

.history-content :deep(.loading-state),
.history-content :deep(.empty-state) {
  min-height: 280px;
  border: 1px dashed var(--wb-border);
  border-radius: var(--wb-radius-section);
  background: color-mix(in srgb, var(--wb-surface-section) 72%, transparent);
}

.history-content :deep(.empty-state .empty-icon) {
  border: 1px solid color-mix(in srgb, var(--wb-accent) 24%, var(--wb-border-soft));
  background: var(--wb-accent-soft);
}

.history-content :deep(.empty-state .empty-text) { color: var(--wb-text); }
.history-content :deep(.empty-state .empty-hint) { color: var(--wb-text-secondary); }

@media (max-width: 768px) {
  .history-view { padding-right: 14px; padding-left: 14px; }
  .history-actions { justify-content: flex-start; }
  .history-actions { flex-wrap: wrap; }
  .history-search { flex: 1 1 190px; width: auto; }
  .history-tabs { overflow-x: auto; }
  .history-tabs button { flex: 0 0 auto; }
}
</style>
