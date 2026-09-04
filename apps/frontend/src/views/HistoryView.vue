<template>
  <div class="history-view">
    <header class="history-header">
      <div class="history-title">
        <span class="history-title__icon"><el-icon><Clock /></el-icon></span>
        <div>
          <h1>历史记录</h1>
          <p>查看和管理对话、文件与 ACG 运行记录</p>
        </div>
      </div>

      <div class="history-actions">
        <label class="history-search">
          <el-icon><Search /></el-icon>
          <input v-model="searchKeyword" type="search" placeholder="搜索历史记录..." />
        </label>
        <button type="button" class="history-action" @click="refresh">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </button>
        <button type="button" class="history-action history-action--danger" @click="clearAll">
          <el-icon><Delete /></el-icon>
          <span>清空对话</span>
        </button>
      </div>
    </header>

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
        :user-id="userStore.currentUser?.id"
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
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatLineRound, Clock, Delete, Document, Monitor, Refresh, Search } from '@element-plus/icons-vue'
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

const normalizeTab = (value: unknown): HistoryTab => {
  return value === 'files' || value === 'acg' ? value : 'conversations'
}

const activeTab = ref<HistoryTab>(normalizeTab(route.query.tab))

const selectTab = (tab: HistoryTab) => {
  activeTab.value = tab
  void router.replace({
    path: '/history',
    query: tab === 'conversations' ? {} : { tab },
  })
}

const handleSelectConversation = (conversation: { id: string; contextId?: string }) => {
  const contextId = conversation.contextId || conversation.id
  void router.push({ path: '/chat', query: { contextId, workspace: 'chat' } })
}

const refresh = () => {
  refreshKey.value += 1
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
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  box-sizing: border-box;
}

.history-header,
.history-tabs,
.history-content {
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg-card) 80%, transparent);
  box-shadow: var(--shadow-sm);
  backdrop-filter: var(--backdrop-blur);
}

.history-header {
  min-height: 50px;
  padding: 7px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.history-title,
.history-actions,
.history-search,
.history-tabs button {
  display: flex;
  align-items: center;
}

.history-title { gap: 10px; }
.history-title__icon {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  color: var(--primary-color);
}
.history-title h1 { margin: 0; font-size: 18px; line-height: 1.2; color: var(--text-primary); }
.history-title p { margin: 3px 0 0; color: var(--text-secondary); font-size: 12px; }
.history-actions { gap: 6px; }
.history-search {
  width: 220px;
  height: 30px;
  gap: 6px;
  padding: 0 9px;
  box-sizing: border-box;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  background: var(--bg-input);
}
.history-search input { width: 100%; border: 0; outline: 0; background: transparent; color: var(--text-primary); font: inherit; font-size: 12px; }
.history-action {
  height: 30px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  background: var(--surface-solid);
  color: var(--text-primary);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
}
.history-action:hover { border-color: var(--border-hover); background: var(--bg-input); }
.history-action--danger { color: var(--danger); }

.history-tabs {
  min-height: 38px;
  display: flex;
  gap: 2px;
  padding: 0 6px;
}
.history-tabs button {
  height: 38px;
  gap: 6px;
  padding: 0 12px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
}
.history-tabs button:hover,
.history-tabs button.active { color: var(--primary-color); }
.history-tabs button.active { border-bottom-color: var(--primary-color); font-weight: 600; }

.history-content { flex: 1; min-height: 0; overflow: hidden; }

@media (max-width: 768px) {
  .history-view { padding: 8px; }
  .history-header { align-items: stretch; }
  .history-actions { flex-wrap: wrap; }
  .history-search { flex: 1 1 180px; width: auto; }
  .history-action { flex: 1; justify-content: center; }
  .history-tabs { overflow-x: auto; }
  .history-tabs button { flex: 0 0 auto; }
}
</style>
