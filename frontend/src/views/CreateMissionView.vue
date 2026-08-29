<template>
  <WorkbenchLayout :show-left="false" :show-right="false" storage-key="zhiyi.create-mission.layout.v1">
    <template #main>
      <main class="create-mission" aria-label="Create Mission">
        <header class="create-mission__header">
          <span class="create-mission__eyebrow">CREATE MISSION</span>
          <h1>新建工程</h1>
          <p>创建一个长期稳定的 Mission，并立即启动首个 Run。</p>
        </header>

        <form class="create-mission__form" @submit.prevent="submit">
          <section class="create-section">
            <label for="mission-title">项目名称</label>
            <input id="mission-title" v-model="draft.title" class="create-mission__title" type="text" placeholder="例如：IC-200 智能装配生产线实施方案" autocomplete="off" />
          </section>

          <section class="create-section create-section--split">
            <div>
              <label for="mission-material">任务材料</label>
              <textarea id="mission-material" v-model="draft.materialText" rows="7" placeholder="粘贴需求、背景资料、研究材料或其他任务上下文"></textarea>
              <label class="create-file" for="mission-file">
                <span>＋ 添加文件</span>
                <small v-if="fileState === 'parsing'">正在解析…</small>
                <small v-else-if="fileName">{{ fileName }}</small>
                <input id="mission-file" type="file" accept=".pdf,.docx,.txt,.md" @change="handleFile" />
              </label>
            </div>
            <div>
              <label for="mission-goal">项目目标</label>
              <textarea id="mission-goal" v-model="draft.taskGoal" rows="7" placeholder="描述目标、范围和成功标准"></textarea>
            </div>
          </section>

          <section class="create-section create-section--split">
            <div>
              <label for="mission-constraints">执行约束</label>
              <textarea id="mission-constraints" v-model="constraintsText" rows="3" placeholder="使用逗号或换行分隔，例如：两周内完成、控制预算"></textarea>
            </div>
            <div>
              <label for="mission-artifacts">预期交付物</label>
              <textarea id="mission-artifacts" v-model="expectedArtifactsText" rows="3" placeholder="使用逗号或换行分隔，例如：实施方案、风险清单"></textarea>
            </div>
          </section>

          <section class="create-section create-section--config">
            <div class="create-section__heading">
              <div><strong>Runtime Configuration</strong><span>能力包与本次 Run 的规划、审核策略</span></div>
            </div>
            <div class="config-line">
              <span class="config-line__label">Capabilities</span>
              <div class="config-options">
                <button class="config-option" :class="{ 'is-selected': !draft.enabledPluginIds.length }" type="button" @click="clearPlugin">Native Core <b>✓</b></button>
                <button v-for="plugin in plugins" :key="plugin.pluginId" class="config-option" :class="{ 'is-selected': draft.enabledPluginIds.includes(plugin.pluginId) }" type="button" @click="togglePlugin(plugin.pluginId)">{{ plugin.displayName }} <b>{{ draft.enabledPluginIds.includes(plugin.pluginId) ? '✓' : '○' }}</b></button>
              </div>
            </div>
            <div class="config-line">
              <span class="config-line__label">Planning</span>
              <label class="config-select"><span class="sr-only">Planning mode</span><select v-model="draft.planningMode"><option value="dynamic">Dynamic</option><option value="template_preferred">Template preferred</option></select></label>
            </div>
            <div class="config-line">
              <span class="config-line__label">Review</span>
              <label class="config-select"><span class="sr-only">Review mode</span><select v-model="draft.reviewMode"><option value="auto">Auto</option><option value="human_in_loop">Human review</option></select></label>
            </div>
          </section>

          <p v-if="errorMessage" class="create-mission__error" role="alert">{{ errorMessage }}</p>
          <footer class="create-mission__footer">
            <button class="create-mission__cancel" type="button" @click="goBack">取消</button>
            <button class="create-mission__submit" type="submit" :disabled="submitting">
              {{ submitting ? '正在创建…' : '创建并运行' }}
            </button>
          </footer>
        </form>
      </main>
    </template>
  </WorkbenchLayout>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import WorkbenchLayout from '@/components/workbench/WorkbenchLayout.vue'
import { workflowApi } from '@/services/api/workflow'
import { fileApi } from '@/services/api/file'
import { buildWorkbenchStartRequest, createNativeWorkbenchDraft, type WorkbenchDraft } from '@/features/acg/workbench'
import { pluginUiExtensions } from '@/plugins'

const router = useRouter()
const draft = ref<WorkbenchDraft>(createNativeWorkbenchDraft())
const submitting = ref(false)
const errorMessage = ref('')
const fileState = ref<'idle' | 'parsing'>('idle')
const fileName = ref('')
let controller: AbortController | null = null

const plugins = computed(() => pluginUiExtensions.all())
const constraintsText = computed({
  get: () => draft.value.constraints.join('，'),
  set: value => { draft.value.constraints = value.split(/[,，\n]/).map(item => item.trim()).filter(Boolean) }
})
const expectedArtifactsText = computed({
  get: () => draft.value.expectedArtifacts.join('，'),
  set: value => { draft.value.expectedArtifacts = value.split(/[,，\n]/).map(item => item.trim()).filter(Boolean) }
})

const togglePlugin = (pluginId: string) => {
  if (draft.value.enabledPluginIds.includes(pluginId)) {
    clearPlugin()
    return
  }
  draft.value.enabledPluginIds = [pluginId]
  const defaults = pluginUiExtensions.get(pluginId)?.createDefaults?.()
  if (!defaults) return
  if (!draft.value.title && defaults.title) draft.value.title = defaults.title
  if (!draft.value.taskGoal && defaults.taskGoal) draft.value.taskGoal = defaults.taskGoal
  if (!draft.value.expectedArtifacts.length && defaults.expectedArtifacts) draft.value.expectedArtifacts = [...defaults.expectedArtifacts]
  if (defaults.reviewMode) draft.value.reviewMode = defaults.reviewMode
  if (defaults.pluginData) draft.value.pluginData = { ...draft.value.pluginData, ...defaults.pluginData }
}

const clearPlugin = () => {
  draft.value.enabledPluginIds = []
  draft.value.pluginData = {}
  draft.value.reviewMode = 'auto'
}

const handleFile = async (event: Event) => {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  fileState.value = 'parsing'
  errorMessage.value = ''
  try {
    const result = await fileApi.extractDocumentText(file)
    const text = (result.text || result.content || '').trim()
    if (!text) throw new Error('文件中没有可提取的文字')
    draft.value.materialText = text
    fileName.value = file.name
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail || error?.message || '文件解析失败'
  } finally {
    fileState.value = 'idle'
  }
}

const createClientRequestId = () => typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`

const submit = async () => {
  if (submitting.value) return
  if (!draft.value.title.trim()) { errorMessage.value = '请输入项目名称'; return }
  if (!draft.value.taskGoal.trim()) { errorMessage.value = '请输入项目目标'; return }
  submitting.value = true
  errorMessage.value = ''
  controller?.abort()
  controller = new AbortController()
  try {
    const request = buildWorkbenchStartRequest(draft.value, plugins.value.filter(plugin => draft.value.enabledPluginIds.includes(plugin.pluginId)), createClientRequestId())
    if (draft.value.materialText.trim()) {
      const manifest = await workflowApi.createMaterial(draft.value.materialText.trim(), 'text/plain')
      request.materialRefs = [manifest.manifestId]
      delete request.input.materialText
    }
    const run = await workflowApi.startWorkflowAsync(request, { signal: controller.signal })
    await router.replace({ name: 'MissionWorkspace', params: { missionId: run.missionId }, query: { runId: run.runId } })
  } catch (error: any) {
    if (error?.name === 'CanceledError' || error?.name === 'AbortError') return
    errorMessage.value = error?.response?.data?.detail || error?.message || 'Mission 创建失败，请稍后重试。'
    ElMessage.error(errorMessage.value)
  } finally {
    submitting.value = false
  }
}

const goBack = () => { void router.push({ name: 'AcgVisualization' }) }
onBeforeUnmount(() => controller?.abort())
</script>

<style scoped>
.create-mission { width: 100%; min-height: 100%; padding: 38px clamp(22px, 6vw, 88px) 48px; color: var(--text-primary); background: var(--bg-app); }
.create-mission__header, .create-mission__form { max-width: 940px; margin: 0 auto; }
.create-mission__header { padding-bottom: 25px; border-bottom: 1px solid var(--border-light); }
.create-mission__eyebrow { color: var(--primary-color); font: 10px var(--font-mono, monospace); letter-spacing: .14em; }
.create-mission h1 { margin: 8px 0 5px; font-size: 25px; line-height: 1.2; }
.create-mission__header p { margin: 0; color: var(--text-secondary); font-size: 12px; }
.create-section { padding: 23px 0; border-bottom: 1px solid var(--border-light); }
.create-section label { display: block; margin-bottom: 9px; color: var(--text-primary); font-size: 12px; font-weight: 650; }
.create-section input[type='text'], .create-section textarea, .config-select select { width: 100%; border: 1px solid var(--border-light); border-radius: 4px; outline: 0; color: var(--text-primary); background: var(--bg-card); font: inherit; font-size: 12px; }
.create-section input[type='text'] { height: 40px; padding: 0 11px; }
.create-section textarea { min-height: 80px; padding: 10px 11px; resize: vertical; line-height: 1.6; }
.create-section input:focus, .create-section textarea:focus, .config-select select:focus { border-color: var(--primary-color); box-shadow: 0 0 0 2px var(--primary-fade); }
.create-section--split { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; }
.create-file { display: flex !important; align-items: center; gap: 10px; margin-top: 10px; color: var(--primary-color) !important; cursor: pointer; font-weight: 500 !important; }
.create-file small { color: var(--text-muted); font-size: 10px; font-weight: 400; }
.create-file input { display: none; }
.create-section--config { display: grid; gap: 17px; }
.create-section__heading { padding-bottom: 3px; }
.create-section__heading strong, .create-section__heading span { display: block; }
.create-section__heading strong { font-size: 13px; }
.create-section__heading span { margin-top: 4px; color: var(--text-secondary); font-size: 11px; }
.config-line { display: grid; grid-template-columns: 130px minmax(0, 1fr); align-items: center; gap: 14px; min-height: 34px; }
.config-line__label { color: var(--text-secondary); font-size: 11px; }
.config-options { display: flex; flex-wrap: wrap; gap: 8px; }
.config-option { padding: 7px 10px; border: 1px solid var(--border-light); border-radius: 4px; color: var(--text-secondary); background: transparent; cursor: pointer; font-size: 11px; }
.config-option b { margin-left: 7px; color: var(--text-muted); font-weight: 500; }
.config-option.is-selected { border-color: var(--primary-line); color: var(--primary-color); background: var(--primary-fade); }
.config-option.is-selected b { color: var(--primary-color); }
.config-select select { width: min(240px, 100%); height: 32px; padding: 0 8px; }
.create-mission__error { margin: 18px 0 0; color: var(--danger); font-size: 12px; }
.create-mission__footer { display: flex; justify-content: flex-end; gap: 10px; padding-top: 25px; }
.create-mission__cancel, .create-mission__submit { min-width: 82px; height: 36px; padding: 0 14px; border-radius: 5px; cursor: pointer; font-size: 12px; }
.create-mission__cancel { border: 1px solid var(--border-light); color: var(--text-secondary); background: transparent; }
.create-mission__submit { border: 1px solid var(--primary-color); color: #fff; background: var(--primary-color); }
.create-mission__submit:disabled { opacity: .6; cursor: wait; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 720px) { .create-mission { padding: 26px 18px 40px; } .create-section--split { grid-template-columns: 1fr; gap: 22px; } .config-line { grid-template-columns: 1fr; gap: 7px; } }
</style>
