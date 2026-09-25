<template>
  <div class="workspace-file-explorer__branch" role="none">
    <button
      class="workspace-file-explorer__row"
      :class="{
        'is-selected': node.type === 'file' && selectedPath === node.path,
        'is-directory': node.type === 'directory'
      }"
      type="button"
      role="treeitem"
      :aria-expanded="node.type === 'directory' ? node.expanded : undefined"
      :aria-selected="node.type === 'file' ? selectedPath === node.path : undefined"
      :title="node.path"
      @click="node.type === 'directory' ? emit('toggleDirectory', node.source) : emit('selectFile', node.source)"
    >
      <span class="workspace-file-explorer__chevron" :class="{ 'is-expanded': node.expanded }" aria-hidden="true">
        <el-icon v-if="node.type === 'directory'"><ArrowRight /></el-icon>
      </span>
      <span class="workspace-file-explorer__file-icon" aria-hidden="true">
        <el-icon>
          <FolderOpened v-if="node.type === 'directory' && node.expanded" />
          <Folder v-else-if="node.type === 'directory'" />
          <Document v-else />
        </el-icon>
      </span>
      <span class="workspace-file-explorer__name">{{ node.name }}</span>
      <span v-if="node.loading" class="workspace-file-explorer__inline-status">加载中</span>
    </button>
    <div v-if="node.type === 'directory' && node.expanded" class="workspace-file-explorer__children" role="group">
      <div v-if="node.error" class="workspace-file-explorer__message is-error" role="alert">
        <span>{{ node.error }}</span>
        <button type="button" @click="emit('retryDirectory', node.source)">重试</button>
      </div>
      <div v-else-if="node.loaded && node.visibleChildren.length === 0" class="workspace-file-explorer__message workspace-file-explorer__message--nested">
        {{ filterText ? '没有匹配的已加载文件' : '空文件夹' }}
      </div>
      <WorkspaceFileTreeNode
        v-for="child in node.visibleChildren"
        :key="child.path"
        :node="child"
        :selected-path="selectedPath"
        :filter-text="filterText"
        @toggle-directory="emit('toggleDirectory', $event)"
        @select-file="emit('selectFile', $event)"
        @retry-directory="emit('retryDirectory', $event)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ArrowRight, Document, Folder, FolderOpened } from '@element-plus/icons-vue'
import type { WorkspaceFileTreeItem, WorkspaceFileVisibleTreeItem } from './workspaceFileExplorer.types'

defineProps<{
  node: WorkspaceFileVisibleTreeItem
  selectedPath: string
  filterText: string
}>()

const emit = defineEmits<{
  toggleDirectory: [node: WorkspaceFileTreeItem]
  selectFile: [node: WorkspaceFileTreeItem]
  retryDirectory: [node: WorkspaceFileTreeItem]
}>()

</script>
