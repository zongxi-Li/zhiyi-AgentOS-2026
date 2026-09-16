<template>
  <section class="knowledge-documents" aria-labelledby="knowledge-documents-title">
    <header class="knowledge-documents__header">
      <div>
        <span class="knowledge-documents__eyebrow">DOCUMENTS</span>
        <h2 id="knowledge-documents-title">文档管理</h2>
      </div>
      <span class="knowledge-documents__count">{{ documents.length }} 个文档</span>
    </header>

    <div class="knowledge-documents__body">
      <div v-if="documents.length === 0" class="knowledge-documents__empty">
        <div class="knowledge-documents__empty-icon" aria-hidden="true">
          <el-icon><Document /></el-icon>
        </div>
        <strong>暂无文档</strong>
        <p>上传文档后即可开始使用知识库</p>
      </div>

      <div v-else class="knowledge-documents__list">
        <article v-for="document in documents" :key="document.doc_id" class="knowledge-document">
          <div class="knowledge-document__icon" aria-hidden="true">
            <el-icon><Document /></el-icon>
          </div>
          <div class="knowledge-document__copy">
            <strong :title="document.filename">{{ document.filename }}</strong>
            <span>{{ formatTime(document.upload_time) }}</span>
          </div>
          <button
            type="button"
            class="knowledge-document__delete"
            title="删除文档"
            :aria-label="`删除文档 ${document.filename}`"
            @click="emit('delete', document.doc_id)"
          >
            <el-icon><Delete /></el-icon>
          </button>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { Delete, Document } from '@element-plus/icons-vue'

export type KnowledgeDocument = {
  doc_id: string
  filename: string
  upload_time: string
}

defineProps<{
  documents: KnowledgeDocument[]
}>()

const emit = defineEmits<{
  delete: [docId: string]
}>()

const formatTime = (time: string) => {
  if (!time) return ''
  const date = new Date(time)
  return Number.isNaN(date.getTime()) ? time : date.toLocaleDateString()
}
</script>

<style scoped>
.knowledge-documents {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  color: var(--text-primary);
  background: var(--surface-raised);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-panel);
  box-shadow: var(--shadow-sm);
}

.knowledge-documents__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 58px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-light);
}

.knowledge-documents__eyebrow {
  color: var(--primary-color);
  font: 10px var(--font-mono, monospace);
  letter-spacing: .12em;
}

.knowledge-documents h2 {
  margin: 5px 0 0;
  color: var(--text-primary);
  font-size: 15px;
  line-height: 1.25;
}

.knowledge-documents__count {
  flex: 0 0 auto;
  color: var(--text-muted);
  font: 11px var(--font-mono, monospace);
}

.knowledge-documents__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 12px;
}

.knowledge-documents__empty {
  display: grid;
  justify-items: center;
  align-content: center;
  min-height: 260px;
  color: var(--text-secondary);
  text-align: center;
}

.knowledge-documents__empty-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  margin-bottom: 12px;
  color: var(--primary-color);
  background: var(--primary-fade);
  border: 1px solid var(--primary-line);
  border-radius: var(--radius-control);
}

.knowledge-documents__empty-icon .el-icon {
  font-size: 20px;
}

.knowledge-documents__empty strong {
  color: var(--text-primary);
  font-size: 14px;
}

.knowledge-documents__empty p {
  margin: 5px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.knowledge-documents__list {
  display: grid;
  gap: 6px;
}

.knowledge-document {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 9px;
  border: 1px solid transparent;
  border-radius: var(--radius-control);
  background: transparent;
  transition: background-color 160ms var(--ease-out), border-color 160ms var(--ease-out);
}

.knowledge-document:hover {
  border-color: var(--primary-line);
  background: var(--primary-fade);
}

.knowledge-document__icon {
  display: grid;
  flex: 0 0 30px;
  place-items: center;
  width: 30px;
  height: 30px;
  color: var(--primary-color);
  background: var(--primary-fade);
  border-radius: var(--radius-control);
}

.knowledge-document__copy {
  display: grid;
  flex: 1 1 auto;
  min-width: 0;
  gap: 3px;
}

.knowledge-document__copy strong,
.knowledge-document__copy span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.knowledge-document__copy strong {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
}

.knowledge-document__copy span {
  color: var(--text-muted);
  font: 10px var(--font-mono, monospace);
}

.knowledge-document__delete {
  display: grid;
  flex: 0 0 28px;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  color: var(--text-muted);
  background: transparent;
  border: 0;
  border-radius: var(--radius-control);
  cursor: pointer;
  opacity: .7;
  transition: color 160ms var(--ease-out), background-color 160ms var(--ease-out), opacity 160ms var(--ease-out);
}

.knowledge-document__delete:hover,
.knowledge-document__delete:focus-visible {
  color: var(--danger);
  background: var(--danger-fade);
  opacity: 1;
  outline: none;
}

@media (prefers-reduced-motion: reduce) {
  .knowledge-document,
  .knowledge-document__delete { transition: none; }
}
</style>
