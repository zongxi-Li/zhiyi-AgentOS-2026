<template>
  <article class="mission-editor editor-document" aria-label="mission.md">
    <header class="editor-document__header">
      <div>
        <h1>mission.md</h1>
        <p>{{ projection.missionSemanticView ? '任务目标与约束' : '任务说明' }}</p>
      </div>
      <div class="mission-editor__toolbar" role="tablist" aria-label="任务说明视图">
        <div class="mission-editor__mode">
          <button
            v-for="item in modeTabs"
            :key="item.id"
            type="button"
            role="tab"
            :aria-selected="mode === item.id"
            :class="{ 'is-active': mode === item.id }"
            @click="mode = item.id"
          >{{ item.label }}</button>
        </div>
        <span class="mission-editor__readonly">只读</span>
      </div>
      <button v-if="projection.missionSemanticView && !editing" type="button" aria-label="编辑正式目标与约束" @click="beginEdit">{{ projection.missionSemanticView.semanticStatus === 'INITIALIZED' ? '编辑目标与约束' : '初始化正式语义' }}</button>
    </header>

    <section class="mission-editor__versions" aria-label="文档版本归属">
      <span>所选 Run：<code>{{ projection.activeRun?.runId || '尚未创建' }}</code></span>
      <span>生效计划：{{ planLabel }}</span>
      <span>执行图：{{ graphLabel }}</span>
      <span v-if="projection.missionSemanticView">目标 revision {{ projection.missionSemanticView.missionRevision }}</span>
      <p v-if="planUnavailable" role="status">计划快照不可用，正文中的步骤不能视为已核验的生效计划。</p>
      <p v-if="historicalNotice" role="status">{{ historicalNotice }}</p>
    </section>

    <MissionRevisionNotice v-if="projection.missionSemanticView && projection.activeRun"
      :mission-id="projection.mission.missionId" :run-id="projection.activeRun.runId"
      :revision="projection.missionSemanticView.missionRevision" :run-status="projection.activeRun.status || ''"
      :readonly="readonly"
      :action-capabilities="actionCapabilities"
      @changed="emit('semanticsSaved')" />

    <form v-if="editing" class="mission-editor__meta" @submit.prevent="saveSemantics">
      <label>正式目标<textarea v-model="objective" aria-label="正式目标" :disabled="saving" required rows="6" /></label>
      <div v-for="(constraint, index) in constraints" :key="constraint.constraintId">
        <label>约束 {{ index + 1 }}<textarea v-model="constraint.text" :aria-label="`约束 ${index + 1}`" :disabled="saving" required /></label>
        <button type="button" :disabled="saving" @click="constraints.splice(index, 1)">移除约束</button>
      </div>
      <button type="button" :disabled="saving" @click="addConstraint">添加约束</button>
      <p>修改作用于后续新 Run；所选 Run 继续使用历史依据。</p>
      <p v-if="saveError" role="alert">{{ saveError }}</p>
      <button type="submit" :disabled="saving || conflicted || !objective.trim()">{{ saving ? '保存中…' : '保存正式语义' }}</button>
      <button v-if="conflicted" type="button" @click="emit('semanticsSaved'); editing = false">刷新当前版本</button>
      <button type="button" :disabled="saving" @click="editing = false">取消</button>
    </form>



    <MissionMarkdownEditor
      v-if="mode === 'source'"
      :model-value="sourceContent"
      class="mission-editor__codemirror"
      read-only
      aria-label="任务说明 Markdown"
    />
    <div v-else class="editor-document__body markdown-body" v-html="previewContent" />

    <section v-if="projection.selectedRunBasis || projection.selectedRunBasisStatus" class="mission-editor__meta" aria-label="Mission metadata">
      <div v-if="projection.selectedRunBasis" class="property-row"><span>所选 Run 依据</span><span>{{ projection.selectedRunBasis.sourceType }} · revision {{ projection.selectedRunBasis.sourceRevision }}</span></div>
      <div v-else-if="projection.selectedRunBasisStatus" class="property-row"><span>所选 Run 依据</span><span>{{ runDisplayObjective(projection) }}</span></div>
    </section>
    <section v-if="projection.inputAttachments?.length" class="mission-editor__meta" aria-label="Run input attachments">
      <div class="property-row"><strong>Input attachments</strong><span>{{ projection.inputAttachments.length }}</span></div>
      <div v-for="attachment in projection.inputAttachments" :key="attachment.attachmentId" class="property-row">
        <span>{{ attachment.originalFilename }}</span>
        <code>{{ attachment.status }} · {{ formatBytes(attachment.sizeBytes) }}</code>
      </div>
    </section>
  </article>
</template>

<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { graphVersionsKey, graphVersionPair } from './graphVersions'
import MissionRevisionNotice from './MissionRevisionNotice.vue'
import MissionMarkdownEditor from './MissionMarkdownEditor.vue'
import { agentosApi, type MissionSemanticEditRequest } from '@/services/api/agentos'
import { missionDocumentContent, runDisplayObjective } from './missionSemanticDisplay'
import { renderMarkdown } from '@/utils/markdown'
import type { MissionWorkspaceProjection, WorkspaceEntry, RunActionCapabilities } from '@/services/api/agentos'

const props = defineProps<{
  projection: MissionWorkspaceProjection
  entry: WorkspaceEntry
  readonly?: boolean
  actionCapabilities?: RunActionCapabilities | null
}>()
const emit = defineEmits<{ semanticsSaved: [] }>()
const editing = ref(false)
const saving = ref(false)
const conflicted = ref(false)
const saveError = ref('')
const objective = ref('')
const constraints = ref<MissionSemanticEditRequest['constraints']>([])
let expectedRevision = 0
let sourceRefs: string[] = []
let pending: MissionSemanticEditRequest | null = null
const newOperationId = () => crypto.randomUUID()
const beginEdit = () => {
  const view = props.projection.missionSemanticView
  objective.value = view?.objective || ''
  constraints.value = (view?.constraints || []).map(item => ({ ...item, sourceRefs: [...(item.sourceRefs || [])] }))
  sourceRefs = [...(view?.sourceReferences || [])]
  expectedRevision = view?.missionRevision || 0
  pending = null
  saveError.value = ''
  conflicted.value = false
  editing.value = true
}
const addConstraint = () => constraints.value.push({ constraintId: newOperationId(), text: '', sourceRefs: [] })
const saveSemantics = async () => {
  if (saving.value || conflicted.value) return
  const content = { objective: objective.value, constraints: constraints.value, sourceRefs }
  if (!pending || JSON.stringify(content) !== JSON.stringify({ objective: pending.objective, constraints: pending.constraints, sourceRefs: pending.sourceRefs })) {
    pending = JSON.parse(JSON.stringify({ ...content, expectedMissionRevision: expectedRevision, operationId: newOperationId() }))
  }
  saving.value = true
  saveError.value = ''
  try {
    await agentosApi.editMissionSemantics(props.projection.mission.missionId, pending!)
    editing.value = false
    pending = null
    emit('semanticsSaved')
  } catch (error: any) {
    conflicted.value = error?.response?.status === 409
    saveError.value = conflicted.value ? '版本冲突，请刷新当前版本后重新编辑。' : '保存失败，可重试相同内容。'
  } finally {
    saving.value = false
  }
}

// Generated document follows the workspace projection; formal edits use the semantic form.
const modeTabs = [
  { id: 'source' as const, label: '源码' },
  { id: 'preview' as const, label: '预览' }
]
const mode = ref<'source' | 'preview'>('source')
const sourceContent = computed(() => props.projection.entries.some(entry => entry.entryId === 'overview:mission.md')
  || props.projection.missionSemanticView
  ? missionDocumentContent(props.projection)
  : props.entry.content || missionDocumentContent(props.projection))
const previewContent = computed(() => renderMarkdown(sourceContent.value))
const graphVersions = inject(graphVersionsKey, null)
const planUnavailable = computed(() => props.projection.diagnostics.some(item => item.code === 'PLAN_SNAPSHOT_UNRESOLVED'))
const planLabel = computed(() => planUnavailable.value || props.projection.activeGraph?.taskPlanVersion == null
  ? '版本未登记' : `ACG v${props.projection.activeGraph.taskPlanVersion}`)
const graphLabel = computed(() => props.projection.activeGraph?.graphVersion == null
  ? '版本未登记' : `RGraph v${props.projection.activeGraph.graphVersion}`)
const historicalNotice = computed(() => graphVersions?.historical.value && graphVersions.selected.value
  ? `正在查看 ${graphVersionPair(graphVersions.selected.value)} 历史图；mission.md 仍展示所选 Run 的生效计划 ${planLabel.value}。`
  : '')

const formatBytes = (bytes: number) => bytes < 1024
  ? `${bytes} B`
  : bytes < 1024 * 1024
    ? `${(bytes / 1024).toFixed(1)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`
</script>

<style scoped>
.mission-editor {
  flex: 1 1 auto;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  padding: 0;
  border: 1px solid var(--wb-border-soft);
  border-radius: var(--wb-radius-section);
  background: var(--wb-surface-section);
  box-shadow: var(--wb-shadow-section);
  color: var(--wb-text);
}

/* 贴边编辑器：卡片不留呼吸边距，标题行/工具条/正文各自带最小内衬。 */
.editor-document__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  padding: 14px 16px 12px;
  border-bottom: 1px solid var(--wb-border-soft);
}

.editor-document__header h1 { max-width: 820px; margin: 7px 0 4px; font-size: 19px; line-height: 1.3; text-wrap: pretty; overflow-wrap: anywhere; }
.editor-document__header p { margin: 0; color: var(--wb-text-secondary); font-size: 12px; }
.editor-document__header code { align-self: flex-start; max-width: 220px; overflow: hidden; color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.editor-document__eyebrow { color: var(--wb-accent); font: 10px var(--font-mono, monospace); letter-spacing: .1em; }

.editor-document__body { width: min(calc(100% - 32px), 820px); margin: 0 16px; padding: 24px 0 40px; font-size: 14px; line-height: 1.7; }

/* 只读源码和预览共用文档工具条。 */
.mission-editor__toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  margin: 0 0 0 auto;
  padding: 0;
}

.mission-editor__mode {
  display: inline-flex;
  flex-shrink: 0;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--wb-border-soft);
  border-radius: 9px;
  background: var(--wb-surface-inset);
}

.mission-editor__mode button {
  min-height: 26px;
  padding: 0 12px;
  margin: 0;
  border: 0;
  border-radius: 7px;
  color: var(--wb-text-muted);
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  transition: color 140ms var(--ease-out), background-color 140ms var(--ease-out);
}

.mission-editor__mode button:hover { color: var(--wb-text-secondary); background: var(--wb-hover); }

.mission-editor__mode button.is-active {
  color: var(--wb-accent);
  background: var(--wb-surface-2);
  font-weight: 650;
  box-shadow: 0 1px 3px rgba(0, 0, 0, .08);
}

.mission-editor__mode button:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: -1px; }

.mission-editor__codemirror { width: 100%; font-size: 13px; }
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) { color: var(--wb-text); line-height: 1.35; text-wrap: pretty; }
.markdown-body :deep(h1) { margin: 0 0 18px; font-size: 18px; }
.markdown-body :deep(h2) { margin: 28px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--wb-border); font-size: 17px; }
.markdown-body :deep(h3) { margin: 20px 0 8px; font-size: 14px; }
.markdown-body :deep(p),
.markdown-body :deep(li) { color: var(--wb-text-secondary); font-size: inherit; line-height: 1.7; overflow-wrap: anywhere; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) { padding-left: 23px; }
.markdown-body :deep(code) { padding: 2px 4px; color: var(--wb-text); background: var(--wb-surface-inset); font: 11px var(--font-mono, monospace); }
.markdown-body :deep(pre) { overflow: auto; padding: 12px; border: 1px solid var(--wb-border); background: var(--wb-surface-inset); }
.markdown-body :deep(pre code) { padding: 0; background: transparent; }
.markdown-body :deep(blockquote) { margin: 12px 0; padding-left: 12px; border-left: 2px solid var(--wb-accent); color: var(--wb-text-secondary); }
.markdown-body :deep(a) { color: var(--wb-accent); }
/* Markdown 表格样式收敛到 global.css 的全局三线表 */

.mission-editor__meta { width: min(calc(100% - 32px), 820px); margin: 30px 16px 0; padding-top: 14px; border-top: 1px solid var(--wb-border-soft); }
.mission-editor__meta textarea { display: block; width: 100%; margin: 8px 0; padding: 10px; color: var(--wb-text); background: var(--wb-surface-inset); border: 1px solid var(--wb-border-soft); font: inherit; }
.mission-editor button { padding: 6px 10px; margin: 4px; color: var(--wb-text); background: var(--wb-surface-inset); border: 1px solid var(--wb-border-soft); cursor: pointer; }
/* 工具条按钮不受上面的通用按钮规则影响：必须排在它之后（同特异性靠后者胜）。 */
.mission-editor .mission-editor__mode button { min-height: 26px; padding: 0 12px; margin: 0; border: 0; }
.mission-editor .mission-editor__reset { min-height: 26px; padding: 0 11px; margin: 0 0 0 auto; }
.property-row { display: flex; justify-content: space-between; gap: 24px; min-height: 30px; padding: 7px 0; color: var(--wb-text-secondary); font-size: 12px; }
.property-row + .property-row { border-top: 1px solid color-mix(in srgb, var(--wb-border-soft) 70%, transparent); }
.property-row code { color: var(--wb-text); font: 11px var(--font-mono, monospace); }
</style>

<style scoped>
.mission-editor__readonly { color: var(--wb-text-muted); font-size: 11px; }
.mission-editor__versions { display: flex; flex-wrap: wrap; gap: 8px 18px; padding: 12px 16px; border-bottom: 1px solid var(--wb-border-soft); color: var(--wb-text-secondary); font-size: 12px; }
.mission-editor__versions code { overflow-wrap: anywhere; }
.mission-editor__versions p { flex-basis: 100%; margin: 0; color: var(--wb-text-muted); line-height: 1.6; }
.editor-document__header { flex-wrap: wrap; }
</style>
