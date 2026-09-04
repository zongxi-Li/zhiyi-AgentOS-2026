<template>
  <el-avatar :size="size" :src="avatarSrc" :alt="alt">
    <slot>{{ fallbackInitial }}</slot>
  </el-avatar>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { userApi } from '@/services/api/user'
import { useUserStore } from '@/stores/user'

const props = withDefaults(defineProps<{
  size?: number
  fallback?: string
  alt?: string
}>(), {
  size: 28,
  fallback: '',
  alt: '用户头像'
})

const userStore = useUserStore()
const avatarSrc = ref('')
let avatarObjectUrl = ''
let requestVersion = 0

const fallbackInitial = computed(() => {
  if (props.fallback) return props.fallback
  return userStore.currentUser?.username?.trim().charAt(0).toUpperCase() || 'A'
})

const releaseAvatar = () => {
  if (!avatarObjectUrl) return
  URL.revokeObjectURL(avatarObjectUrl)
  avatarObjectUrl = ''
}

const syncAvatar = async () => {
  const version = ++requestVersion
  releaseAvatar()
  avatarSrc.value = ''

  const user = userStore.currentUser
  if (!user?.id || !user.avatar) return

  try {
    const blob = await userApi.getAvatar(user.id)
    if (version !== requestVersion) return
    avatarObjectUrl = URL.createObjectURL(blob)
    avatarSrc.value = avatarObjectUrl
  } catch (error) {
    if (version === requestVersion) {
      console.warn('头像同步失败', error)
    }
  }
}

watch(
  () => [userStore.currentUser?.id, userStore.currentUser?.avatar] as const,
  () => { void syncAvatar() },
  { immediate: true }
)

onBeforeUnmount(() => {
  requestVersion += 1
  releaseAvatar()
})
</script>
