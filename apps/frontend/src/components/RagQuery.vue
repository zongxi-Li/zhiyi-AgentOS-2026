<!-- RAG 查询组件：知识库智能检索输入与结果展示。 -->
<template>
  <div class="rag-query-container">
    <div class="query-card">
      <header class="card-header">
        <div class="header-left">
          <el-icon class="header-icon" aria-hidden="true"><Search /></el-icon>
          <span class="header-title">智能检索</span>
        </div>
        <div class="header-settings">
          <span class="settings-label">Top K</span>
          <el-input-number
            v-model="topK"
            :min="1"
            :max="10"
            size="small"
            controls-position="right"
            class="k-input"
          />
        </div>
      </header>

      <div class="query-body">
        <div class="input-area">
          <textarea
            v-model="queryText"
            class="query-textarea"
            placeholder="请输入您的问题，AI 将基于知识库为您解答..."
            rows="4"
            @keydown.enter.prevent.ctrl="handleQuery"
          ></textarea>
        </div>

        <div class="input-footer">
          <span class="hint-text">Ctrl + Enter 发送</span>
          <button
            class="submit-button"
            type="button"
            :disabled="loading"
            @click="handleQuery"
          >
            <el-icon v-if="!loading" class="submit-icon" aria-hidden="true"><ArrowRight /></el-icon>
            <el-icon v-else class="submit-icon loading" aria-hidden="true"><Loading /></el-icon>
            <span>查询</span>
          </button>
        </div>

        <RecommendationPanel
          title="检索推荐"
          subtitle="基于当前角色、查询和检索结果生成"
          :items="recommendations"
          :loading="recommendationLoading"
          refreshable
          @refresh="loadRecommendations"
          @select="applyRecommendation"
        />

        <transition name="fade-slide">
          <div v-if="result" class="result-area">
            <div class="result-header">
              <div class="result-title-wrapper">
                <span class="title-indicator" aria-hidden="true"></span>
                <span class="result-title">AI 回答</span>
              </div>
              <div v-if="result.confidence" class="confidence-badge">
                <span class="confidence-label">置信度</span>
                <span class="confidence-value">
                  {{ Math.round(result.confidence * 100) }}%
                </span>
              </div>
            </div>

            <div class="answer-box">
              <div class="answer-content">{{ result.answer }}</div>
            </div>

            <div v-if="result.sources?.length" class="sources-section">
              <div class="sources-header">
                <el-icon class="sources-icon" aria-hidden="true"><Link /></el-icon>
                <span class="sources-title">参考来源</span>
              </div>
              <div class="sources-list">
                <div
                  v-for="(source, index) in result.sources"
                  :key="index"
                  class="source-item"
                >
                  <span class="source-number">{{ index + 1 }}</span>
                  <span class="source-text">{{ source.title || source.url || '未知来源' }}</span>
                </div>
              </div>
            </div>
          </div>
        </transition>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight, Link, Loading, Search } from '@element-plus/icons-vue'
import RecommendationPanel from '@/components/RecommendationPanel.vue'
import { recommendationApi, type RecommendationItem } from '@/services/api/recommendation'
import { ragApi } from '@/services/api/rag'
import { useDebounce } from '@/composables/useDebounce'
import { useRoleStore } from '@/stores/role'
import { resolveKnowledgeRoleId } from '@/utils/knowledgeRole'

type RagResult = Awaited<ReturnType<typeof ragApi.query>>

const queryText = ref('')
const topK = ref(5)
const loading = ref(false)
const result = ref<RagResult | null>(null)
const recommendations = ref<RecommendationItem[]>([])
const recommendationLoading = ref(false)

const roleStore = useRoleStore()
const currentRoleId = computed(() => resolveKnowledgeRoleId(roleStore.currentRole))
const debouncedQueryText = useDebounce(queryText, 350)

const handleQuery = async () => {
  if (!queryText.value.trim()) {
    ElMessage.warning('请输入查询内容')
    return
  }

  loading.value = true
  result.value = null

  try {
    result.value = await ragApi.query(
      queryText.value,
      topK.value,
      undefined,
      currentRoleId.value,
    )
    ElMessage.success('查询成功')
  } catch (error: any) {
    ElMessage.error(`查询失败：${error.message || '未知错误'}`)
  } finally {
    loading.value = false
  }
}

const loadRecommendations = async () => {
  recommendationLoading.value = true

  try {
    recommendations.value = await recommendationApi.getContextualRecommendations({
      roleName: roleStore.currentRole?.name,
      scope: 'rag',
      scene: 'query',
      currentInput: queryText.value,
      currentOutput: result.value?.answer,
      conversationHistory: queryText.value.trim() ? [queryText.value.trim()] : [],
    })
  } catch (error) {
    console.warn('加载 RAG 推荐失败', error)
    recommendations.value = []
  } finally {
    recommendationLoading.value = false
  }
}

const applyRecommendation = (item: RecommendationItem) => {
  queryText.value = item.text
}

watch(
  [currentRoleId, debouncedQueryText, () => result.value?.answer],
  () => {
    void loadRecommendations()
  },
)

onMounted(() => {
  void loadRecommendations()
})
</script>

<style scoped>
.rag-query-container {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
}

.query-card {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-panel);
  color: var(--text-primary);
  background: var(--surface-raised);
  box-shadow: var(--shadow-sm);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 58px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-light);
}

.header-left,
.header-settings,
.input-footer,
.result-header,
.result-title-wrapper,
.sources-header {
  display: flex;
  align-items: center;
}

.header-left {
  gap: 8px;
  min-width: 0;
}

.header-icon,
.sources-icon {
  flex: 0 0 auto;
  color: var(--primary-color);
  font-size: 17px;
}

.header-title,
.result-title,
.sources-title {
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 650;
}

.header-settings {
  gap: 8px;
}

.settings-label,
.hint-text,
.confidence-label {
  color: var(--text-muted);
  font-size: 11px;
}

.k-input {
  width: 82px;
}

.query-body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
  gap: 14px;
  overflow: auto;
  padding: 14px;
}

.input-area {
  flex: 0 0 auto;
}

.query-textarea {
  display: block;
  width: 100%;
  min-height: 150px;
  padding: 12px;
  resize: vertical;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-card);
  outline: none;
  color: var(--text-primary);
  background: var(--bg-input);
  font: inherit;
  font-size: 13px;
  line-height: 1.6;
  transition:
    border-color 160ms var(--ease-out),
    box-shadow 160ms var(--ease-out),
    background-color 160ms var(--ease-out);
}

.query-textarea:focus {
  border-color: var(--border-focus);
  outline: none;
  background: var(--surface-solid);
  box-shadow: 0 0 0 3px var(--primary-fade);
}

.query-textarea::placeholder {
  color: var(--text-muted);
}

.input-footer {
  justify-content: space-between;
  gap: 12px;
  min-height: 32px;
}

.submit-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 72px;
  height: 32px;
  padding: 0 12px;
  border: 0;
  border-radius: var(--radius-control);
  color: var(--on-primary);
  background: var(--primary-color);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  transition: background-color 160ms var(--ease-out), transform 160ms var(--ease-out);
}

.submit-button:hover:not(:disabled),
.submit-button:focus-visible {
  outline: none;
  background: var(--primary-hover);
}

.submit-button:active:not(:disabled) {
  transform: translateY(1px);
}

.submit-button:disabled {
  cursor: not-allowed;
  opacity: .55;
}

.submit-icon {
  font-size: 14px;
}

.submit-icon.loading {
  animation: rag-query-spin 900ms linear infinite;
}

.result-area {
  margin-top: 2px;
  padding-top: 14px;
  border-top: 1px solid var(--border-light);
}

.result-header {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.result-title-wrapper {
  gap: 7px;
}

.title-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary-color);
  box-shadow: 0 0 0 3px var(--primary-fade);
}

.confidence-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.confidence-value {
  color: var(--primary-color);
  font: 12px var(--font-mono, monospace);
}

.answer-box {
  padding: 12px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-card);
  background: var(--bg-input);
}

.answer-content {
  color: var(--text-regular);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.sources-section {
  margin-top: 14px;
}

.sources-header {
  gap: 7px;
  margin-bottom: 8px;
}

.sources-list {
  display: grid;
  gap: 6px;
}

.source-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-control);
  color: var(--text-secondary);
  background: var(--surface-subtle);
}

.source-number {
  display: grid;
  flex: 0 0 20px;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  color: var(--primary-color);
  background: var(--primary-fade);
  font: 10px var(--font-mono, monospace);
}

.source-text {
  min-width: 0;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity 160ms var(--ease-out), transform 160ms var(--ease-out);
}

.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

@keyframes rag-query-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 700px) {
  .card-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .header-settings {
    justify-content: space-between;
    width: 100%;
  }

  .query-body {
    padding: 12px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .fade-slide-enter-active,
  .fade-slide-leave-active,
  .submit-icon.loading,
  .submit-button {
    transition: none;
    animation: none;
  }
}
</style>
