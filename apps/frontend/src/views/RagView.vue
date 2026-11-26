<template>
  <div class="rag-view">
    <WorkbenchLayout
      :show-left="false"
      :show-right="false"
      storage-key="zhiyi.rag.layout.v1"
    >
      <template #main>
        <main class="rag-view__main" aria-label="知识库">
          <WorkspacePageHero
            title="知识库"
            description="从文档中查找答案、追溯来源和探索知识关系。"
          >
            <template #actions>
              <button
                class="rag-action rag-action--primary"
                type="button"
                @click="showUploadDialog = true"
              >
                <el-icon aria-hidden="true"><Upload /></el-icon>
                <span>上传文档</span>
              </button>
            </template>
          </WorkspacePageHero>

          <nav class="rag-tabs" role="tablist" aria-label="知识库功能">
            <button
              type="button"
              role="tab"
              :aria-selected="activeTab === 'query'"
              :class="{ active: activeTab === 'query' }"
              @click="activeTab = 'query'"
            >
              知识检索
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="activeTab === 'graph'"
              :class="{ active: activeTab === 'graph' }"
              @click="activeTab = 'graph'"
            >
              知识图谱
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="activeTab === 'docs'"
              :class="{ active: activeTab === 'docs' }"
              @click="activeTab = 'docs'"
            >
              文档管理
            </button>
          </nav>

          <section
            v-show="activeTab === 'query'"
            class="rag-query-layout"
            aria-label="知识检索"
          >
            <RagQuery />
            <aside class="rag-library" aria-label="文档概览">
              <header>
                <h2><el-icon aria-hidden="true"><Document /></el-icon>文档库</h2>
                <span v-if="!documentsLoading && !documentsError">{{ documents.length }} 个文档</span>
              </header>
              <p v-if="documentsLoading" role="status">正在加载文档…</p>
              <div v-else-if="documentsError" class="rag-library__body">
                <p role="status">加载文档失败</p>
                <button class="rag-action" type="button" @click="loadDocuments">重试</button>
              </div>
              <div v-else-if="documents.length === 0" class="rag-library__body">
                <p>添加文档，让检索有资料可查。</p>
                <button class="rag-action" type="button" @click="showUploadDialog = true">
                  <el-icon aria-hidden="true"><Upload /></el-icon>添加首份文档
                </button>
              </div>
              <div v-else class="rag-library__body">
                <ul aria-label="最近上传">
                  <li v-for="document in recentDocuments" :key="document.doc_id" :title="document.filename">
                    {{ document.filename }}
                  </li>
                </ul>
                <button class="rag-action" type="button" @click="activeTab = 'docs'">查看全部文档</button>
              </div>
            </aside>
          </section>

          <section
            v-if="activeTab === 'graph'"
            class="rag-graph"
            aria-label="知识图谱"
          >
            <KnowledgeGraphVisualization />
          </section>

          <section v-if="activeTab === 'docs'" class="rag-docs-only" aria-label="文档管理">
            <p v-if="documentsLoading" role="status">正在加载文档…</p>
            <div v-else-if="documentsError" class="rag-library">
              <p role="status">加载文档失败</p>
              <button class="rag-action" type="button" @click="loadDocuments">重试</button>
            </div>
            <KnowledgeDocumentsPanel
              v-else
              :documents="documents"
              @delete="handleDelete"
            />
          </section>
        </main>
      </template>
    </WorkbenchLayout>

    <el-dialog
      v-model="showUploadDialog"
      title="上传文档"
      width="520px"
      align-center
      class="rag-upload-dialog"
    >
      <div class="rag-upload-container">
        <el-upload
          class="rag-upload-area"
          :http-request="handleUpload"
          :on-success="handleUploadSuccess"
          :on-error="handleUploadError"
          :before-upload="beforeUpload"
          drag
        >
          <div class="rag-upload-content">
            <div class="rag-upload-icon" aria-hidden="true">
              <el-icon><UploadFilled /></el-icon>
            </div>
            <h3>点击或拖拽上传</h3>
            <p>支持 PDF、Word、TXT、Markdown 等格式</p>
          </div>
        </el-upload>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Upload, UploadFilled } from '@element-plus/icons-vue'
import WorkbenchLayout from '@/components/workbench/WorkbenchLayout.vue'
import WorkspacePageHero from '@/components/app/WorkspacePageHero.vue'
import KnowledgeDocumentsPanel, {
  type KnowledgeDocument,
} from '@/components/knowledge/KnowledgeDocumentsPanel.vue'
import RagQuery from '@/components/RagQuery.vue'
import { ragApi } from '@/services/api/rag'
import { useRoleStore } from '@/stores/role'
import { resolveKnowledgeRoleId } from '@/utils/knowledgeRole'

const KnowledgeGraphVisualization = defineAsyncComponent(
  () => import('@/components/KnowledgeGraphVisualization.vue')
)

type RagTab = 'query' | 'graph' | 'docs'

const roleStore = useRoleStore()
const showUploadDialog = ref(false)
const activeTab = ref<RagTab>('query')
const documents = ref<KnowledgeDocument[]>([])
const documentsLoading = ref(true)
const documentsError = ref(false)
const recentDocuments = computed(() => [...documents.value]
  .sort((a, b) => (Date.parse(b.upload_time) || 0) - (Date.parse(a.upload_time) || 0))
  .slice(0, 3))
const currentRoleId = computed(() => resolveKnowledgeRoleId(roleStore.currentRole))

const beforeUpload = (file: File) => {
  const maxSize = 10 * 1024 * 1024

  if (file.size > maxSize) {
    ElMessage.error('文件大小不能超过 10MB')
    return false
  }

  if (currentRoleId.value) {
    const roleName = roleStore.currentRole?.name || '当前角色'
    ElMessage.info(`文档将添加到“${roleName}”的知识库`)
  } else {
    ElMessage.warning('未选择角色，文档将添加到通用知识库')
  }

  return true
}

// 返回 Promise 交给 el-upload，成功/失败由 :on-success / :on-error 统一回调，避免重复提示
const handleUpload = (options: any) => ragApi.uploadDocument(options.file, currentRoleId.value)

const handleUploadSuccess = () => {
  ElMessage.success('文档上传成功')
  showUploadDialog.value = false
  void loadDocuments()
}

const handleUploadError = (error?: any) => {
  ElMessage.error(`文档上传失败${error?.message ? `：${error.message}` : ''}`)
}

const handleDelete = async (docId: string) => {
  try {
    await ragApi.deleteDocument(docId)
    ElMessage.success('文档删除成功')
    void loadDocuments()
  } catch (error: any) {
    ElMessage.error(`删除失败：${error?.message || '未知错误'}`)
  }
}

const loadDocuments = async () => {
  documentsLoading.value = true
  documentsError.value = false
  try {
    const response = await ragApi.listDocuments(currentRoleId.value)
    documents.value = response.documents || []
  } catch {
    documentsError.value = true
  } finally {
    documentsLoading.value = false
  }
}

onMounted(() => {
  void loadDocuments()
})
</script>

<style scoped>
.rag-view {
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--bg-app);
}

.rag-view__main {
  width: min(100%, 1400px);
  height: 100%;
  margin: 0 auto;
  overflow: auto;
  padding: 0 clamp(20px, 4vw, 58px) 48px;
  color: var(--text-primary);
}

.rag-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid var(--primary-line);
  border-radius: var(--radius-control);
  color: var(--primary-color);
  background: var(--primary-fade);
  cursor: pointer;
  font: inherit;
  font-size: 11px;
  transition:
    background-color 160ms var(--ease-out),
    border-color 160ms var(--ease-out),
    color 160ms var(--ease-out);
}

.rag-action--primary {
  border-color: transparent;
  color: var(--on-primary, #fff);
  background: var(--primary-color);
  box-shadow: var(--shadow-sm);
}

.rag-action:hover,
.rag-action:focus-visible {
  border-color: var(--primary-line);
  color: var(--text-primary);
  background: var(--surface-subtle);
  outline: none;
}

.rag-action--primary:hover,
.rag-action--primary:focus-visible {
  border-color: transparent;
  color: var(--on-primary, #fff);
  background: var(--primary-hover);
}

.rag-tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border-light);
}

.rag-tabs button {
  min-height: 36px;
  padding: 0 14px;
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--text-secondary);
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  transition:
    color 160ms var(--ease-out),
    border-color 160ms var(--ease-out);
}

.rag-tabs button:hover,
.rag-tabs button.active {
  color: var(--primary-color);
}

.rag-tabs button.active {
  border-bottom-color: var(--primary-color);
  font-weight: 650;
}

.rag-query-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 28%);
  align-items: start;
  gap: 20px;
  padding-top: 24px;
}

.rag-library {
  padding: 18px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-panel);
  background: var(--surface-raised);
  color: var(--text-secondary);
  font-size: 12px;
}

.rag-library header,
.rag-library h2 {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rag-library header {
  justify-content: space-between;
  flex-wrap: wrap;
}

.rag-library h2 {
  margin: 0;
  color: var(--text-primary);
  font-size: 14px;
}

.rag-library h2 .el-icon {
  color: var(--primary-color);
}

.rag-library__body {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border-light);
}

.rag-library__body p,
.rag-library__body ul {
  margin: 0 0 12px;
}

.rag-library__body ul {
  display: grid;
  gap: 6px;
  padding: 0;
  list-style: none;
}

.rag-library__body li {
  overflow: hidden;
  padding-block: 4px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.rag-query-layout > * {
  min-width: 0;
  min-height: 0;
}

.rag-graph,
.rag-docs-only {
  min-width: 0;
  min-height: min(680px, calc(100vh - 220px));
  padding-top: 18px;
}

.rag-graph :deep(.knowledge-graph-viz) {
  min-height: 100%;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-panel);
  box-shadow: var(--shadow-sm);
}

.rag-upload-container {
  padding: 8px 0;
}

.rag-upload-area :deep(.el-upload-dragger) {
  width: 100%;
  height: 240px;
  border: 1px dashed var(--border-light);
  border-radius: var(--radius-card);
  background: var(--bg-input);
  transition:
    border-color 160ms var(--ease-out),
    background-color 160ms var(--ease-out);
}

.rag-upload-area :deep(.el-upload-dragger:hover) {
  border-color: var(--primary-color);
  background: var(--primary-fade);
}

.rag-upload-content {
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 10px;
  height: 100%;
  text-align: center;
}

.rag-upload-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border: 1px solid var(--primary-line);
  border-radius: var(--radius-control);
  color: var(--primary-color);
  background: var(--primary-fade);
}

.rag-upload-icon .el-icon {
  font-size: 24px;
}

.rag-upload-content h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 15px;
}

.rag-upload-content p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
}

@media (max-width: 820px) {
  .rag-query-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 700px) {
  .rag-view__main {
    padding-right: 16px;
    padding-left: 16px;
  }

  .rag-tabs {
    overflow-x: auto;
    scrollbar-width: none;
  }

  .rag-tabs::-webkit-scrollbar {
    display: none;
  }

  .rag-tabs button {
    flex: 0 0 auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .rag-action,
  .rag-tabs button {
    transition: none;
  }
}
</style>
