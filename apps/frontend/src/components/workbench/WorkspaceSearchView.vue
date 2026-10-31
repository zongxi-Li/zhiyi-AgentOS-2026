<template>
  <section class="workspace-search" aria-label="工作区搜索">
    <label class="workspace-search__input">
      <el-icon aria-hidden="true"><Search /></el-icon>
      <input v-model="query" type="search" placeholder="搜索内容…" aria-label="搜索内容" />
      <button v-if="query" class="workspace-search__clear" type="button" aria-label="清除搜索" @click="query = ''">×</button>
    </label>

    <p v-if="hint" class="workspace-search__status">{{ hint }}</p>
    <p v-else-if="searching" class="workspace-search__status" role="status">搜索中…</p>
    <p v-else-if="error" class="workspace-search__error" role="alert">{{ error }}</p>
    <p v-else-if="result && !result.matches.length" class="workspace-search__status">没有匹配结果</p>
    <ul v-else-if="result" class="workspace-search__results" role="list">
      <li v-for="match in result.matches" :key="`${match.path}:${match.line}`">
        <button type="button" class="workspace-search__result" @click="openMatch(match)">
          <span class="workspace-search__path">{{ match.path }}<span class="workspace-search__line">:{{ match.line }}</span></span>
          <span class="workspace-search__text">{{ match.text }}</span>
        </button>
      </li>
    </ul>

    <footer v-if="result && !hint" class="workspace-search__footer">
      {{ result.matches.length }} 条结果<span v-if="result.truncated">（已截断）</span> · {{ result.engine }}
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { agentosApi } from '@/services/api/agentos'
import { searchWorkspace, type WorkspaceSearchResult } from '@/services/workspaceSearch'
import { getElectronBridge } from '@/platform/electron/bridge'
import { requestReveal } from '@/workbench/core/reveal'

const props = defineProps<{ missionId: string }>()
const emit = defineEmits<{ (event: 'open-file', request: Record<string, unknown>): void }>()

const query = ref('')
const searching = ref(false)
const error = ref('')
const result = ref<WorkspaceSearchResult | null>(null)
const root = ref('')
const workspaceId = ref<string | null>(null)
const rootError = ref('')

let timer: number | undefined
let generation = 0
let disposed = false

const bridge = getElectronBridge()?.workspace
const hint = computed(() => {
  if (!bridge?.search) return '全文搜索仅在桌面端可用'
  if (rootError.value) return rootError.value
  if (!root.value) return '正在定位工作区…'
  if (query.value.trim().length < 2) return '输入至少 2 个字符开始搜索'
  return ''
})

const messageOf = (cause: any) => cause?.message || '搜索失败'

async function resolveRoot(): Promise<void> {
  rootError.value = ''
  try {
    const folder = await bridge?.current?.()
    if (folder) {
      root.value = folder.root
      workspaceId.value = folder.id
      return
    }
    if (props.missionId) {
      const listing = await agentosApi.listWorkspaceFiles(props.missionId, '.')
      root.value = listing.workspaceRoot
    }
  } catch (cause) {
    rootError.value = messageOf(cause)
  }
}

async function run(): Promise<void> {
  const text = query.value.trim()
  if (text.length < 2 || !root.value) {
    result.value = null
    return
  }
  const token = ++generation
  searching.value = true
  error.value = ''
  try {
    const response = await searchWorkspace(root.value, { query: text, maxResults: 200 })
    if (disposed || token !== generation) return
    result.value = response
  } catch (cause) {
    if (disposed || token !== generation) return
    error.value = messageOf(cause)
  } finally {
    if (!disposed && token === generation) searching.value = false
  }
}

watch(query, () => {
  window.clearTimeout(timer)
  result.value = null
  error.value = ''
  timer = window.setTimeout(() => void run(), 260)
})

function openMatch(match: { path: string; line: number }): void {
  const name = match.path.split('/').pop() || match.path
  requestReveal(match.path, match.line)
  emit('open-file', {
    missionId: props.missionId,
    workspaceRoot: root.value,
    relativePath: match.path,
    name,
    // 搜索根目录来自桌面宿主时，文件读写也必须走同一个本地工作区，否则服务端会拒绝。
    ...(workspaceId.value ? { desktopWorkspaceId: workspaceId.value } : {})
  })
}

onMounted(() => { void resolveRoot() })
onBeforeUnmount(() => {
  disposed = true
  generation += 1
  window.clearTimeout(timer)
})
</script>

<style scoped>
.workspace-search { display:flex; flex-direction:column; width:100%; min-width:0; min-height:0; color:var(--wb-text); font:12px/1.45 var(--font-sans, sans-serif); }
.workspace-search__input { display:flex; align-items:center; gap:6px; margin:8px 10px; padding:4px 8px; border:1px solid var(--wb-border-strong); border-radius:4px; background:var(--wb-surface-inset, #161616); color:var(--wb-text-muted); }
.workspace-search__input input { flex:1; min-width:0; border:0; outline:none; background:transparent; color:var(--wb-text); font:inherit; }
.workspace-search__clear { border:0; background:transparent; color:var(--wb-text-muted); cursor:pointer; font-size:14px; line-height:1; }
.workspace-search__status { margin:8px 12px; color:var(--wb-text-muted); }
.workspace-search__error { margin:8px 12px; color:var(--wb-danger); }
.workspace-search__results { flex:1; min-height:0; margin:0; padding:0 0 8px; overflow:auto; list-style:none; }
.workspace-search__result { display:flex; flex-direction:column; gap:2px; width:100%; padding:5px 12px; border:0; background:transparent; color:inherit; text-align:left; cursor:pointer; }
.workspace-search__result:hover, .workspace-search__result:focus-visible { background:var(--wb-hover); outline:none; }
.workspace-search__path { color:var(--wb-text-secondary); font-size:11px; }
.workspace-search__line { color:var(--wb-accent); }
.workspace-search__text { overflow:hidden; color:var(--wb-text); font:11.5px/1.4 var(--font-mono, Consolas, monospace); text-overflow:ellipsis; white-space:nowrap; }
.workspace-search__footer { flex:none; padding:6px 12px; border-top:1px solid var(--wb-border); color:var(--wb-text-muted); font-size:11px; }
</style>
