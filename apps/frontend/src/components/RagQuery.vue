<!-- RAG 查询组件：知识库智能检索输入与结果展示。 -->
<template>
  <div class="rag-query-container">
    <div class="query-card">
      <header class="card-header">
        <div class="header-left">
          <el-icon class="header-icon" aria-hidden="true"><Search /></el-icon>
          <h2 class="header-title">向知识库提问</h2>
        </div>
      </header>

      <div class="query-body">
        <form class="query-composer" @submit.prevent="handleQuery">
          <textarea
            ref="queryInput"
            v-model="queryText"
            class="query-textarea"
            aria-label="检索问题"
            placeholder="例如：文档中提到了哪些部署要求？"
            rows="3"
            @keydown.ctrl.enter.prevent="handleQuery"
            @keydown.meta.enter.prevent="handleQuery"
          ></textarea>

        <div class="input-footer">
          <div class="header-settings">
            <span class="settings-label" title="每次检索最多取回的文档片段数">检索条数</span>
            <el-input-number
              v-model="topK"
              :min="1"
              :max="10"
              size="small"
              controls-position="right"
              aria-label="检索条数"
              class="k-input"
            />
          </div>
          <button
            class="submit-button"
            type="submit"
            :disabled="loading || !queryText.trim()"
            title="Ctrl / ⌘ + Enter"
          >
            <el-icon v-if="!loading" class="submit-icon" aria-hidden="true"><ArrowRight /></el-icon>
            <el-icon v-else class="submit-icon loading" aria-hidden="true"><Loading /></el-icon>
            <span>{{ loading ? '检索中' : '开始检索' }}</span>
          </button>
        </div>
        </form>

        <p v-if="queryError" class="query-error" role="alert">{{ queryError }}</p>

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
        <div v-if="result && recommendations.length" class="query-suggestions">
          <span>继续追问</span>
          <button
            v-for="item in recommendations"
            :key="item.text"
            type="button"
            @click="applyRecommendation(item.text)"
          >{{ item.text }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, Link, Loading, Search } from '@element-plus/icons-vue'
import { recommendationApi, type RecommendationItem } from '@/services/api/recommendation'
import { ragApi } from '@/services/api/rag'
import { useRoleStore } from '@/stores/role'
import { resolveKnowledgeRoleId } from '@/utils/knowledgeRole'

type RagResult = Awaited<ReturnType<typeof ragApi.query>>

const queryText = ref('')
const queryInput = ref<HTMLTextAreaElement | null>(null)
const topK = ref(5)
const loading = ref(false)
const queryError = ref('')
const result = ref<RagResult | null>(null)
const recommendations = ref<RecommendationItem[]>([])

const roleStore = useRoleStore()
const currentRoleId = computed(() => resolveKnowledgeRoleId(roleStore.currentRole))

const handleQuery = async () => {
  const question = queryText.value.trim()
  if (loading.value || !question) return
  const roleId = currentRoleId.value

  loading.value = true
  queryError.value = ''
  result.value = null
  recommendations.value = []

  try {
    const answer = await ragApi.query(
      question,
      topK.value ?? 5,
      undefined,
      roleId,
    )
    if (currentRoleId.value !== roleId) return
    result.value = answer
    void loadRecommendations(question, result.value)
  } catch (error: any) {
    if (currentRoleId.value === roleId) {
      queryError.value = `检索失败：${error.message || '请重试'}`
    }
  } finally {
    loading.value = false
  }
}

const loadRecommendations = async (question: string, queryResult: RagResult) => {
  try {
    const items = await recommendationApi.getContextualRecommendations({
      roleName: roleStore.currentRole?.name,
      scope: 'rag',
      scene: 'query',
      currentInput: question,
      currentOutput: queryResult.answer,
      conversationHistory: [question],
    })
    if (result.value === queryResult) recommendations.value = items
  } catch (error) {
    console.warn('加载 RAG 推荐失败', error)
  }
}

const applyRecommendation = (question: string) => {
  queryText.value = question
  queryInput.value?.focus()
}

watch(currentRoleId, () => {
  result.value = null
  queryError.value = ''
})
</script>

<style scoped>
.rag-query-container {
  display: flex;
  width: 100%;
  min-height: 0;
}

.query-card {
  display: flex;
  flex-direction: column;
  width: 100%;
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
  padding: 10px 20px 0;
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

.header-title {
  margin: 0;
  font-size: 16px;
}

.header-settings {
  gap: 8px;
}

.settings-label,
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
  padding: 12px 20px 20px;
}

.query-composer {
  border: 1px solid var(--border-light);
  border-radius: var(--radius-card);
  background: var(--bg-input);
}

.query-composer:focus-within {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px var(--primary-fade);
}

.query-textarea {
  display: block;
  width: 100%;
  min-height: 84px;
  padding: 12px;
  resize: vertical;
  border: 0;
  border-radius: var(--radius-card);
  outline: none;
  color: var(--text-primary);
  background: transparent;
  font: inherit;
  font-size: 13px;
  line-height: 1.6;
  transition:
    border-color 160ms var(--ease-out),
    box-shadow 160ms var(--ease-out),
    background-color 160ms var(--ease-out);
}

.query-textarea::placeholder {
  color: var(--text-muted);
}

.input-footer {
  justify-content: space-between;
  gap: 12px;
  min-height: 32px;
  flex-wrap: wrap;
  padding: 8px 10px;
  border-top: 1px solid var(--border-light);
}

.query-error {
  margin: 0;
  color: var(--danger-color, #e87179);
  font-size: 12px;
}

.query-suggestions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 12px;
}

.query-suggestions button {
  padding: 5px 10px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-control);
  color: var(--text-primary);
  background: var(--surface-subtle);
  font: inherit;
  overflow-wrap: anywhere;
  text-align: left;
  cursor: pointer;
}

.query-suggestions button:hover {
  border-color: var(--primary-color);
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
 padding-top: 14px; }

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
