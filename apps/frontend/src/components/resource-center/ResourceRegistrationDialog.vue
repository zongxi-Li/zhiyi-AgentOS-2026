<template>
  <el-dialog
    :model-value="modelValue"
    width="760px"
    class="resource-registration"
    :show-close="true"
    align-center
    @update:model-value="emit('update:modelValue', $event)"
    @closed="resetForm"
  >
    <template #header>
      <div class="rr-header">
        <span class="rr-header__icon" aria-hidden="true"><el-icon><Connection /></el-icon></span>
        <div class="rr-header__copy">
          <strong>注册资源</strong>
          <span>把 Agent、Skill、MCP 工具等接入统一调度目录</span>
        </div>
      </div>
    </template>

    <div class="rr-body">
      <section class="rr-section">
        <h3 class="rr-section__title"><i>01</i>资源类型</h3>
        <div class="rr-type-grid">
          <button
            v-for="type in resourceTypeOptions"
            :key="type.value"
            type="button"
            class="rr-type"
            :class="{ 'is-active': form.resourceType === type.value }"
            :aria-pressed="form.resourceType === type.value"
            @click="form.resourceType = type.value"
          >
            <el-icon aria-hidden="true" :style="{ color: type.tone }"><component :is="type.icon" /></el-icon>
            <strong>{{ type.label }}</strong>
            <small>{{ type.desc }}</small>
          </button>
        </div>
      </section>

      <section class="rr-section">
        <h3 class="rr-section__title"><i>02</i>基础信息</h3>
        <div class="rr-form">
          <div class="rr-grid rr-grid--2">
            <label class="rr-field" :class="{ 'is-invalid': fieldErrors.resourceId }">
              <span>资源标识 <b>*</b></span>
              <input v-model="form.resourceId" type="text" placeholder="例如 legal-agent / research-mcp" />
              <small v-if="fieldErrors.resourceId" class="rr-field__hint">{{ fieldErrors.resourceId }}</small>
            </label>
            <label class="rr-field">
              <span>部署层级</span>
              <div class="rr-tier">
                <button v-for="tier in tierOptions" :key="tier.value" type="button" :class="{ 'is-active': form.deploymentTier === tier.value }" :aria-pressed="form.deploymentTier === tier.value" @click="form.deploymentTier = tier.value">{{ tier.label }}</button>
              </div>
            </label>
          </div>
          <div class="rr-grid rr-grid--2">
            <label class="rr-field" :class="{ 'is-invalid': fieldErrors.capabilities }">
              <span>能力 <b>*</b>（回车添加）</span>
              <el-select v-model="form.capabilities" multiple filterable allow-create default-first-option placeholder="输入能力后回车" class="rr-select" />
              <small v-if="fieldErrors.capabilities" class="rr-field__hint">{{ fieldErrors.capabilities }}</small>
            </label>
            <label class="rr-field">
              <span>领域（回车添加）</span>
              <el-select v-model="form.domains" multiple filterable allow-create default-first-option placeholder="例如 legal / education" class="rr-select" />
            </label>
          </div>
        </div>
      </section>

      <section class="rr-section">
        <h3 class="rr-section__title"><i>03</i>算力画像 <small>可选</small></h3>
        <div class="rr-form">
          <div class="rr-grid rr-grid--3">
            <label class="rr-field"><span>CPU 核数</span><input v-model.number="form.cpuCores" type="number" min="0" placeholder="0" /></label>
            <label class="rr-field"><span>内存 (MB)</span><input v-model.number="form.memoryMb" type="number" min="0" placeholder="0" /></label>
            <label class="rr-field"><span>带宽 (Mbps)</span><input v-model.number="form.bandwidthMbps" type="number" min="0" placeholder="0" /></label>
          </div>
          <div class="rr-grid rr-grid--2">
            <label class="rr-field"><span>GPU 型号</span><input v-model="form.gpuType" type="text" placeholder="例如 A100，无则留空" /></label>
            <label class="rr-field"><span>GPU 显存 (MB)</span><input v-model.number="form.gpuMemoryMb" type="number" min="0" placeholder="0" /></label>
          </div>
        </div>
      </section>

      <section class="rr-section">
        <h3 class="rr-section__title"><i>04</i>部署与端点</h3>
        <div class="rr-form">
          <div class="rr-grid rr-grid--2">
            <label class="rr-field">
              <span>端点协议</span>
              <el-select v-model="form.endpointProtocol" class="rr-select">
                <el-option label="HTTP" value="http" />
                <el-option label="HTTPS" value="https" />
                <el-option label="gRPC" value="grpc" />
                <el-option label="本地" value="local" />
              </el-select>
            </label>
            <label class="rr-field"><span>端点地址</span><input v-model="form.endpointAddress" type="text" placeholder="例如 10.0.0.8:9000" /></label>
          </div>
          <div class="rr-grid rr-grid--3">
            <label class="rr-field">
              <span>隐私级别</span>
              <el-select v-model="form.privacyLevel" class="rr-select">
                <el-option label="内部 internal" value="internal" />
                <el-option label="私有 private" value="private" />
                <el-option label="公开 public" value="public" />
              </el-select>
            </label>
            <label class="rr-field"><span>位置</span><input v-model="form.location" type="text" placeholder="例如 华东-1" /></label>
            <label class="rr-field"><span>数据域</span><input v-model="form.dataZone" type="text" placeholder="例如 edge-zone" /></label>
          </div>
          <label class="rr-field rr-field--capacity"><span>并发容量</span><input v-model.number="form.capacity" type="number" min="1" placeholder="1" /></label>
        </div>
      </section>

      <p v-if="errorMessage" class="rr-error" role="alert">{{ errorMessage }}</p>
    </div>

    <template #footer>
      <div class="rr-footer">
        <button type="button" class="rr-cancel" @click="emit('update:modelValue', false)">取消</button>
        <button type="button" class="rr-submit" :disabled="submitting" @click="submit">
          {{ submitting ? '注册中…' : '注册资源' }}
        </button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { Connection } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { agentosApi, type RuntimeResourceProfile, type RuntimeResourceSnapshot } from '@/services/api/agentos'
import { resourceTypeMeta } from '@/utils/resourceFormat'
import { resourceTypeIcon } from '@/utils/resourceTypeIcons'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void; (e: 'registered'): void }>()

const resourceTypeOptions = [
  { value: 'agent', label: 'Agent', desc: '智能体运行时' },
  { value: 'skill', label: 'Skill', desc: '可复用技能' },
  { value: 'mcp', label: 'MCP', desc: 'MCP 工具协议' },
  { value: 'tool', label: 'Tool', desc: '工具调用' },
  { value: 'model', label: 'Model', desc: '模型服务' },
  { value: 'worker', label: 'Worker', desc: '工作节点' },
  { value: 'embedding', label: 'Embedding', desc: '向量嵌入' }
].map(option => ({ ...option, icon: resourceTypeIcon(option.value), tone: resourceTypeMeta(option.value).tone }))

const tierOptions = [
  { value: 'local', label: '本地' },
  { value: 'terminal', label: '端侧' },
  { value: 'edge', label: '边缘' },
  { value: 'cloud', label: '云端' }
]

const form = reactive({
  resourceId: '',
  resourceType: 'agent',
  deploymentTier: 'local',
  capabilities: [] as string[],
  domains: [] as string[],
  capacity: 1,
  privacyLevel: 'internal',
  location: '',
  dataZone: '',
  endpointProtocol: 'http',
  endpointAddress: '',
  cpuCores: 0,
  memoryMb: 0,
  gpuType: '',
  gpuMemoryMb: 0,
  bandwidthMbps: 0
})

const submitting = ref(false)
const errorMessage = ref('')

const canSubmit = computed(() => form.resourceId.trim().length > 0 && form.capabilities.length > 0)

const attempted = ref(false)
const fieldErrors = computed(() => ({
  resourceId: attempted.value && !form.resourceId.trim() ? '请输入资源标识' : '',
  capabilities: attempted.value && form.capabilities.length === 0 ? '请至少添加一项能力' : ''
}))

const buildProfile = (): RuntimeResourceProfile => ({
  resourceId: form.resourceId.trim(),
  resourceType: form.resourceType,
  deploymentTier: form.deploymentTier,
  capabilities: form.capabilities,
  domains: form.domains,
  labels: {},
  location: form.location.trim() || null,
  dataZone: form.dataZone.trim() || null,
  costMetadata: {},
  capacity: Math.max(1, form.capacity),
  ownerScope: null,
  privacyLevel: form.privacyLevel,
  executionEndpoint: form.endpointAddress.trim()
    ? { protocol: form.endpointProtocol, address: form.endpointAddress.trim() }
    : null,
  computeCapacity: {
    cpuCores: form.cpuCores || 0,
    memoryMb: form.memoryMb || 0,
    gpuType: form.gpuType.trim() || null,
    gpuMemoryMb: form.gpuMemoryMb || 0,
    bandwidthMbps: form.bandwidthMbps || 0
  },
  modelIds: [],
  enabled: true,
  metadata: {},
  version: 1
})

const buildSnapshot = (): RuntimeResourceSnapshot => ({
  resourceId: form.resourceId.trim(),
  observedAt: new Date().toISOString(),
  availableSlots: Math.max(1, form.capacity),
  utilization: 0,
  healthStatus: 'unknown',
  reliability: null,
  latencyMs: null,
  metrics: {}
})

const submit = async () => {
  if (submitting.value) return
  if (!canSubmit.value) {
    attempted.value = true
    errorMessage.value = '请先填写必填项：资源标识与至少一项能力。'
    return
  }
  attempted.value = false
  submitting.value = true
  errorMessage.value = ''
  try {
    await agentosApi.registerResource({ profile: buildProfile(), snapshot: buildSnapshot() })
    ElMessage.success('资源注册成功')
    emit('registered')
  } catch {
    errorMessage.value = '注册失败，请检查资源标识是否已存在，或端点信息是否正确。'
  } finally {
    submitting.value = false
  }
}

const resetForm = () => {
  form.resourceId = ''
  form.resourceType = 'agent'
  form.deploymentTier = 'local'
  form.capabilities = []
  form.domains = []
  form.capacity = 1
  form.privacyLevel = 'internal'
  form.location = ''
  form.dataZone = ''
  form.endpointProtocol = 'http'
  form.endpointAddress = ''
  form.cpuCores = 0
  form.memoryMb = 0
  form.gpuType = ''
  form.gpuMemoryMb = 0
  form.bandwidthMbps = 0
  errorMessage.value = ''
  attempted.value = false
}
</script>

<style scoped>
.rr-header { display: flex; align-items: center; gap: 12px; }
.rr-header__icon { display: inline-grid; place-items: center; width: 40px; height: 40px; border-radius: 12px; color: #fff; background: linear-gradient(135deg, var(--primary-color), var(--accent-color, #6f668f)); box-shadow: 0 6px 18px color-mix(in srgb, var(--primary-color) 30%, transparent); }
.rr-header__copy { display: grid; gap: 2px; }
.rr-header__copy strong { color: var(--text-primary); font-size: 15px; }
.rr-header__copy span { color: var(--text-muted); font-size: 11px; }
.rr-body { display: grid; gap: 22px; max-height: 62vh; overflow-y: auto; padding-right: 4px; }
.rr-section { display: grid; gap: 12px; }
.rr-section__title { display: flex; align-items: baseline; gap: 8px; margin: 0; color: var(--text-secondary); font-size: 12px; font-weight: 650; letter-spacing: .02em; }
.rr-section__title i { font-style: normal; color: var(--primary-color); font: 11px var(--font-mono, monospace); }
.rr-section__title small { color: var(--text-muted); font-weight: 400; }
.rr-type-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.rr-type { display: grid; justify-items: start; gap: 6px; padding: 14px 12px; border: 1px solid var(--border-light); border-radius: 12px; color: var(--text-secondary); background: var(--bg-card); cursor: pointer; text-align: left; transition: all .2s ease; }
.rr-type:hover { border-color: var(--primary-line); transform: translateY(-2px); box-shadow: var(--shadow-sm); }
.rr-type.is-active { border-color: var(--primary-color); color: var(--primary-color); background: var(--primary-fade); box-shadow: 0 0 0 1px var(--primary-color) inset; }
.rr-type .el-icon { font-size: 20px; }
.rr-type strong { font-size: 12px; }
.rr-type small { color: var(--text-muted); font-size: 10px; }
.rr-form { display: grid; gap: 14px; }
.rr-grid { display: grid; gap: 14px; }
.rr-grid--2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.rr-grid--3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.rr-field { display: grid; gap: 6px; min-width: 0; }
.rr-field > span { color: var(--text-muted); font-size: 11px; }
.rr-field > span b { color: var(--danger, #b64d55); }
.rr-field input { width: 100%; min-height: 38px; padding: 0 11px; border: 1px solid var(--border-light); border-radius: 8px; color: var(--text-primary); background: var(--bg-input); font: inherit; font-size: 12px; outline: 0; transition: border-color .2s ease; }
.rr-field input:focus { border-color: var(--primary-color); }
.rr-field.is-invalid input { border-color: var(--danger, #b64d55); }
.rr-field__hint { color: var(--danger, #b64d55); font-size: 10px; }
.rr-field input::placeholder { color: var(--text-secondary); }
.rr-select { width: 100%; }
.rr-tier { display: flex; gap: 6px; min-height: 38px; padding: 3px; border: 1px solid var(--border-light); border-radius: 8px; background: var(--bg-input); }
.rr-tier button { flex: 1; border: 0; border-radius: 6px; color: var(--text-muted); background: transparent; cursor: pointer; font-size: 11px; }
.rr-tier button.is-active { color: #fff; background: var(--primary-color); }
.rr-field--capacity { max-width: 160px; }
.rr-error { margin: 0; padding: 10px 12px; border: 1px solid color-mix(in srgb, var(--danger, #b64d55) 30%, transparent); border-radius: 8px; color: var(--danger, #b64d55); background: color-mix(in srgb, var(--danger, #b64d55) 8%, transparent); font-size: 11px; }
.rr-footer { display: flex; justify-content: flex-end; gap: 10px; }
.rr-cancel { min-height: 36px; padding: 0 18px; border: 1px solid var(--border-light); border-radius: 8px; color: var(--text-secondary); background: transparent; cursor: pointer; font-size: 12px; }
.rr-cancel:hover { background: var(--bg-input); }
.rr-submit { min-height: 36px; padding: 0 22px; border: 0; border-radius: 8px; color: #fff; background: linear-gradient(135deg, var(--primary-color), var(--accent-color, #6f668f)); cursor: pointer; font-size: 12px; box-shadow: 0 6px 16px color-mix(in srgb, var(--primary-color) 30%, transparent); }
.rr-submit:hover:not(:disabled) { filter: brightness(1.06); }
.rr-submit:disabled { opacity: .55; cursor: not-allowed; }
@media (max-width: 640px) {
  .rr-type-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rr-grid--2, .rr-grid--3 { grid-template-columns: 1fr; }
}
</style>


