<!-- 个人中心页面 — 复刻"设置中心"式布局：左侧分组导航栏 + 右侧个人资料主区（居中身份、统计行、编辑卡片）。 -->
<template>
  <div class="user-view">
    <aside class="user-rail" aria-label="个人中心导航">
      <button class="back-to-app" type="button" @click="router.push('/chat')">
        <el-icon><ArrowLeft /></el-icon>
        <span>返回应用</span>
      </button>

      <div class="rail-search">
        <el-icon aria-hidden="true"><Search /></el-icon>
        <input v-model="searchTerm" type="search" placeholder="搜索个人中心..." aria-label="搜索个人中心" />
      </div>

      <nav class="rail-nav">
        <section class="rail-nav-section">
          <h2>个人</h2>
          <button
            v-for="item in visibleSections"
            :key="item.id"
            class="rail-nav-item"
            :class="{ active: activeSection === item.id }"
            type="button"
            @click="activeSection = item.id"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </button>
          <p v-if="!visibleSections.length" class="rail-empty">没有匹配项</p>
        </section>
        <section class="rail-nav-section">
          <h2>快捷</h2>
          <button class="rail-nav-item" type="button" @click="router.push('/settings')">
            <el-icon><Setting /></el-icon>
            <span>应用设置</span>
            <el-icon class="item-arrow"><ArrowLeft /></el-icon>
          </button>
        </section>
      </nav>

      <div class="rail-account">
        <el-avatar :size="32" class="rail-avatar">
          <el-icon><User /></el-icon>
        </el-avatar>
        <span class="rail-account-copy">
          <strong>{{ userInfo.username || '未登录' }}</strong>
          <small>{{ userInfo.email || '尚未设置邮箱' }}</small>
        </span>
      </div>
    </aside>

    <main v-if="activeSection === 'profile'" class="user-content">
      <header class="content-header">
        <div class="content-heading">
          <span class="content-eyebrow">PROFILE</span>
          <h1>个人资料</h1>
          <p>管理您的个人资料信息</p>
        </div>
        <div class="content-actions">
          <button class="ghost-action" type="button" @click="editing = !editing">
            <el-icon><Edit /></el-icon>
            <span>{{ editing ? '完成编辑' : '编辑' }}</span>
          </button>
          <span class="status-pill"><i aria-hidden="true"></i>账户信息</span>
        </div>
      </header>

      <section class="identity-hero">
        <el-upload
          class="avatar-uploader"
          action="/api/upload/avatar"
          :show-file-list="false"
          :on-success="handleAvatarSuccess"
        >
          <span class="hero-avatar">
            <el-icon :size="38"><User /></el-icon>
            <span class="avatar-edit" title="更换头像"><el-icon :size="11"><Camera /></el-icon></span>
          </span>
        </el-upload>
        <h2 class="hero-name">{{ userInfo.username || '—' }}</h2>
        <p class="hero-handle">
          <span>@{{ userInfo.email || '未设置邮箱' }}</span>
          <span class="hero-badge">{{ roleBadge }}</span>
        </p>
      </section>

      <section class="stats-row" aria-label="账户统计">
        <div class="stats-cell">
          <strong>{{ stats.conversations }}</strong>
          <span>对话数</span>
        </div>
        <div class="stats-cell">
          <strong>{{ stats.roles }}</strong>
          <span>角色数</span>
        </div>
        <div class="stats-cell">
          <strong>{{ stats.messages }}</strong>
          <span>消息数</span>
        </div>
        <div class="stats-cell">
          <strong>{{ registeredDays }}</strong>
          <span>已注册天数</span>
        </div>
      </section>

      <section class="detail-grid">
        <article class="detail-card">
          <header class="detail-card__header">
            <span class="card-kicker">ACCOUNT</span>
            <h3>账户信息</h3>
          </header>
          <dl class="insight-list">
            <div class="insight-row">
              <dt>用户名</dt>
              <dd>{{ userInfo.username || '—' }}</dd>
            </div>
            <div class="insight-row">
              <dt>邮箱地址</dt>
              <dd>{{ userInfo.email || '未设置' }}</dd>
            </div>
            <div class="insight-row">
              <dt>注册时间</dt>
              <dd>{{ formatDate(userInfo.createdAt) }}</dd>
            </div>
          </dl>
        </article>

        <article class="detail-card">
          <header class="detail-card__header">
            <span class="card-kicker">PROFILE</span>
            <h3>编辑资料</h3>
          </header>
          <div class="detail-card__body">
            <el-form :model="userInfo" label-position="top" class="user-form">
              <el-form-item label="用户名">
                <el-input v-model="userInfo.username" disabled class="custom-input" />
                <div class="form-hint">用户名不可修改</div>
              </el-form-item>
              <el-form-item label="邮箱地址">
                <el-input
                  v-model="userInfo.email"
                  :disabled="!editing"
                  placeholder="请输入邮箱地址"
                  class="custom-input"
                />
                <div class="form-hint">用于接收重要通知和找回密码</div>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :disabled="!editing" @click="updateProfile">
                  <el-icon><Check /></el-icon>
                  <span>保存更改</span>
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </article>
      </section>
    </main>

    <main v-else class="user-content">
      <header class="content-header">
        <div class="content-heading">
          <span class="content-eyebrow">SECURITY</span>
          <h1>账户安全</h1>
          <p>修改密码和账户安全设置</p>
        </div>
        <span class="status-pill"><i aria-hidden="true"></i>账户信息</span>
      </header>

      <section class="identity-hero security-hero">
        <span class="hero-avatar is-static">
          <el-icon :size="38"><Lock /></el-icon>
        </span>
        <h2 class="hero-name">密码与安全</h2>
        <p class="hero-handle">定期修改密码可以有效保护账户安全</p>
      </section>

      <section class="security-panel">
        <el-form :model="accountForm" label-position="top" class="user-form">
          <el-form-item label="当前密码">
            <el-input
              v-model="accountForm.currentPassword"
              type="password"
              placeholder="请输入当前密码"
              show-password
              class="custom-input"
            />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input
              v-model="accountForm.newPassword"
              type="password"
              placeholder="请输入新密码（至少8位）"
              show-password
              class="custom-input"
            />
            <div class="form-hint">密码长度至少8位，建议包含字母和数字</div>
          </el-form-item>
          <el-form-item label="确认新密码">
            <el-input
              v-model="accountForm.confirmPassword"
              type="password"
              placeholder="请再次输入新密码"
              show-password
              class="custom-input"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="changePassword">
              <el-icon><Lock /></el-icon>
              <span>修改密码</span>
            </el-button>
          </el-form-item>
        </el-form>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowLeft,
  Calendar,
  Camera,
  Check,
  Edit,
  Lock,
  Search,
  Setting,
  User
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { useRoleStore } from '@/stores/role'
import { useChatStore } from '@/stores/chat'
import { userApi } from '@/services/api/user'

const router = useRouter()
const userStore = useUserStore()
const roleStore = useRoleStore()
const chatStore = useChatStore()

const activeSection = ref<'profile' | 'security'>('profile')
const searchTerm = ref('')
const editing = ref(false)

const railSections = [
  { id: 'profile', label: '个人资料', icon: User },
  { id: 'security', label: '账户安全', icon: Lock }
] as const

const visibleSections = computed(() => {
  const keyword = searchTerm.value.trim().toLowerCase()
  if (!keyword) return railSections
  return railSections.filter(item => item.label.toLowerCase().includes(keyword))
})

const userInfo = ref({
  username: '',
  email: '',
  avatar: '',
  createdAt: new Date()
})

const accountForm = ref({
  currentPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const stats = computed(() => {
  return {
    conversations: chatStore.contextId ? 1 : 0,
    roles: roleStore.roles?.length || 0,
    messages: chatStore.messages?.length || 0
  }
})

const registeredDays = computed(() => {
  if (!userInfo.value.createdAt) return 0
  const created = new Date(userInfo.value.createdAt).getTime()
  if (Number.isNaN(created)) return 0
  return Math.max(1, Math.ceil((Date.now() - created) / 86400000))
})

const roleBadge = computed(() => {
  const name = userInfo.value.username?.trim().toLowerCase()
  return name === 'admin' ? '管理员' : '成员'
})

const formatDate = (date: Date | string | undefined) => {
  if (!date) return '未知'
  const d = new Date(date)
  if (Number.isNaN(d.getTime())) return '未知'
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })
}

const handleAvatarSuccess = (response: any) => {
  if (response && response.url) {
    userInfo.value.avatar = response.url
    ElMessage.success('头像上传成功')
  }
}

const updateProfile = async () => {
  if (!userInfo.value.email) {
    ElMessage.warning('请输入邮箱地址')
    return
  }

  if (!userStore.currentUser?.id) {
    ElMessage.error('用户信息不存在，请重新登录')
    return
  }

  try {
    await userApi.updateUser(userStore.currentUser.id, {
      username: userInfo.value.username,
      email: userInfo.value.email
    })
    await userStore.loadCurrentUser()
    ElMessage.success('个人信息已更新')
  } catch (error: any) {
    ElMessage.error('更新失败: ' + (error.message || '未知错误'))
  }
}

const changePassword = async () => {
  if (!accountForm.value.currentPassword || !accountForm.value.newPassword) {
    ElMessage.warning('请填写完整的密码信息')
    return
  }

  if (accountForm.value.newPassword !== accountForm.value.confirmPassword) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }

  if (accountForm.value.newPassword.length < 8) {
    ElMessage.warning('密码长度至少8位')
    return
  }

  if (!userStore.currentUser?.id) {
    ElMessage.error('用户信息不存在，请重新登录')
    return
  }

  try {
    await userApi.changePassword(userStore.currentUser.id, {
      currentPassword: accountForm.value.currentPassword,
      newPassword: accountForm.value.newPassword
    })
    accountForm.value = {
      currentPassword: '',
      newPassword: '',
      confirmPassword: ''
    }
    ElMessage.success('密码已修改')
  } catch (error: any) {
    const errorMessage = error.response?.data?.message || error.message || '未知错误'
    if (error.response?.status === 400) {
      ElMessage.error('当前密码错误，请重新输入')
    } else {
      ElMessage.error('修改失败: ' + errorMessage)
    }
  }
}

onMounted(async () => {
  await userStore.loadCurrentUser()
  if (userStore.currentUser) {
    userInfo.value = {
      username: userStore.currentUser.username || '',
      email: userStore.currentUser.email || '',
      avatar: '',
      createdAt: userStore.currentUser.createdAt || new Date()
    }
  }
})
</script>

<style scoped lang="scss">
.user-view {
  box-sizing: border-box;
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr);
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: var(--bg-app);
  color: var(--text-primary);
}

/* ── 左侧设置栏 ─────────────────────────────── */
.user-rail {
  min-width: 0;
  min-height: 0;
  padding: 20px 12px 14px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-light);
  background: color-mix(in srgb, var(--bg-sidebar) 78%, var(--bg-app));
}

.back-to-app,
.rail-nav-item {
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  cursor: pointer;
  transition: var(--transition);
}

.back-to-app {
  min-height: 34px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  border-radius: var(--radius-control);
  font-size: 12px;
}

.back-to-app:hover,
.back-to-app:focus-visible {
  color: var(--text-primary);
  background: var(--bg-input);
}

.back-to-app .el-icon {
  font-size: 15px;
}

.rail-search {
  height: 36px;
  margin: 16px 0 14px;
  padding: 0 11px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--bg-input) 88%, transparent);
  color: var(--text-muted);
}

.rail-search:focus-within {
  box-shadow: 0 0 0 1px var(--primary-color) inset;
  color: var(--primary-color);
}

.rail-search input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: 12px;
}

.rail-search input::placeholder {
  color: var(--text-muted);
}

.rail-nav {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  padding: 0 1px 12px;
}

.rail-nav-section {
  margin-bottom: 18px;
}

.rail-nav-section h2 {
  padding: 0 10px;
  margin: 0 0 7px;
  color: var(--text-muted);
  font: 600 11px/1.4 var(--font-sans);
  letter-spacing: 0.04em;
}

.rail-nav-item {
  width: 100%;
  min-height: 35px;
  padding: 0 10px;
  display: flex;
  align-items: center;
  gap: 9px;
  border-radius: 9px;
  text-align: left;
  font-size: 12px;
}

.rail-nav-item .el-icon {
  flex: 0 0 16px;
  color: var(--text-muted);
  font-size: 15px;
}

.rail-nav-item:hover,
.rail-nav-item:focus-visible {
  color: var(--text-primary);
  background: var(--bg-input);
}

.rail-nav-item:hover .el-icon,
.rail-nav-item:focus-visible .el-icon {
  color: var(--primary-color);
}

.rail-nav-item.active {
  color: var(--text-primary);
  background: color-mix(in srgb, var(--primary-color) 12%, var(--bg-card));
  box-shadow: inset 2px 0 0 var(--primary-color);
}

.rail-nav-item.active .el-icon {
  color: var(--primary-color);
}

.rail-nav-item .item-arrow {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 12px;
  transform: rotate(180deg);
}

.rail-empty {
  padding: 10px;
  margin: 0;
  color: var(--text-muted);
  font-size: 11px;
}

.rail-account {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 10px;
  border: 1px solid var(--border-light);
  border-radius: 12px;
  background: color-mix(in srgb, var(--bg-card) 88%, transparent);
}

.rail-avatar {
  flex: 0 0 auto;
  color: var(--primary-color);
  background: var(--primary-fade);
}

.rail-account-copy {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.rail-account-copy strong {
  overflow: hidden;
  color: var(--text-primary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rail-account-copy small {
  overflow: hidden;
  color: var(--text-muted);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 右侧主区 ───────────────────────────────── */
.user-content {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  padding: 26px clamp(20px, 4vw, 56px) 44px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.content-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.content-eyebrow {
  display: block;
  margin-bottom: 4px;
  color: var(--primary-color);
  font: 600 10px var(--font-mono, monospace);
  letter-spacing: 0.12em;
}

.content-heading h1 {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-serif);
  font-size: clamp(22px, 2vw, 28px);
  font-weight: 650;
  letter-spacing: -0.02em;
}

.content-heading p {
  margin: 5px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.content-actions {
  display: flex;
  align-items: center;
  gap: 9px;
}

.ghost-action {
  min-height: 32px;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border-light);
  border-radius: 9px;
  color: var(--text-secondary);
  background: transparent;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: var(--transition);
}

.ghost-action:hover,
.ghost-action:focus-visible {
  color: var(--text-primary);
  border-color: var(--border-hover);
  background: var(--bg-input);
}

.status-pill {
  height: 32px;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid color-mix(in srgb, var(--primary-color) 20%, var(--border-light));
  border-radius: 999px;
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--primary-fade) 60%, transparent);
  font-size: 11px;
}

.status-pill i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
}

/* ── 居中身份区 ─────────────────────────────── */
.identity-hero {
  padding: 20px 0 6px;
  display: grid;
  justify-items: center;
  gap: 7px;
  text-align: center;
}

.avatar-uploader :deep(.el-upload) {
  border: 0;
  background: transparent;
}

.hero-avatar {
  position: relative;
  width: 92px;
  height: 92px;
  display: grid;
  place-items: center;
  overflow: visible;
  color: var(--primary-color);
  background: var(--primary-fade);
  border: 1px solid color-mix(in srgb, var(--primary-color) 26%, var(--border-light));
  border-radius: 50%;
  transition: border-color 180ms var(--ease-out);
}

.avatar-uploader {
  cursor: pointer;
  border-radius: 50%;
}

.avatar-uploader:hover .hero-avatar {
  border-color: var(--primary-color);
}

.avatar-edit {
  position: absolute;
  right: 0;
  bottom: 2px;
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  color: #fff;
  background: var(--primary-color);
  border: 3px solid var(--bg-app);
  border-radius: 50%;
}

.hero-avatar.is-static {
  cursor: default;
}

.hero-name {
  margin: 6px 0 0;
  color: var(--text-primary);
  font-family: var(--font-serif);
  font-size: 26px;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.hero-handle {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--text-secondary);
  font-size: 12px;
}

.hero-badge {
  height: 22px;
  padding: 0 9px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  color: var(--primary-color);
  background: var(--primary-fade);
  border: 1px solid var(--primary-line);
  font-size: 10px;
  font-weight: 600;
}

/* ── 统计行 ─────────────────────────────────── */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid var(--border-light);
  border-radius: 14px;
  background: color-mix(in srgb, var(--surface-solid) 92%, transparent);
}

.stats-cell {
  min-height: 84px;
  box-sizing: border-box;
  padding: 16px 18px;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 4px;
  border-right: 1px solid var(--border-light);
  transition: background-color 180ms var(--ease-out);
}

.stats-cell:hover {
  background: var(--bg-input);
}

.stats-cell:last-child {
  border-right: 0;
}

.stats-cell strong {
  color: var(--text-primary);
  font: 700 22px/1.1 var(--font-sans);
  letter-spacing: -0.02em;
}

.stats-cell span {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 500;
}

/* ── 详情卡片 ───────────────────────────────── */
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  align-items: start;
}

.detail-card {
  overflow: hidden;
  border: 1px solid var(--border-light);
  border-radius: 14px;
  background: color-mix(in srgb, var(--surface-solid) 92%, transparent);
  transition: border-color 180ms var(--ease-out);
}

.detail-card:hover {
  border-color: var(--border-hover);
}

.detail-card__header {
  min-height: 58px;
  box-sizing: border-box;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-light);
}

.card-kicker {
  display: block;
  margin-bottom: 3px;
  color: var(--primary-color);
  font: 600 9px var(--font-mono, monospace);
  letter-spacing: 0.12em;
}

.detail-card__header h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.01em;
}

.insight-list {
  margin: 0;
  padding: 6px 18px 12px;
}

.insight-row {
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid color-mix(in srgb, var(--border-light) 60%, transparent);
}

.insight-row:last-child {
  border-bottom: 0;
}

.insight-row dt {
  color: var(--text-secondary);
  font-size: 12px;
}

.insight-row dd {
  margin: 0;
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-card__body {
  padding: 16px 18px 18px;
}

/* ── 表单 ───────────────────────────────────── */
.user-form .el-form-item {
  margin-bottom: 15px;
}

.user-form .el-form-item:last-child {
  margin-top: 2px;
  margin-bottom: 0;
}

.user-form :deep(.el-form-item__label) {
  margin-bottom: 6px;
  padding: 0;
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 650;
  line-height: 18px;
}

.custom-input :deep(.el-input__wrapper) {
  min-height: 38px;
  box-sizing: border-box;
  border: 1px solid var(--border-light);
  border-radius: 9px;
  background: var(--bg-input);
  box-shadow: none;
  transition: border-color 180ms var(--ease-out), background-color 180ms var(--ease-out), box-shadow 180ms var(--ease-out);
}

.custom-input :deep(.el-input__inner) {
  color: var(--text-primary);
  font-size: 12px;
}

.custom-input :deep(.el-input__inner::placeholder) {
  color: var(--text-disabled);
}

.custom-input :deep(.el-input__wrapper:hover) {
  border-color: var(--border-hover);
  background: var(--surface-solid);
}

.custom-input :deep(.el-input__wrapper.is-focus) {
  border-color: var(--primary-color);
  background: var(--surface-solid);
  box-shadow: 0 0 0 3px var(--primary-fade);
}

.custom-input :deep(.el-input.is-disabled .el-input__wrapper) {
  border-color: var(--border-light);
  background: var(--bg-input);
}

.form-hint {
  margin-top: 5px;
  color: var(--text-disabled);
  font-size: 11px;
  line-height: 1.45;
}

.user-form :deep(.el-button) {
  min-width: 108px;
  height: 34px;
  padding: 0 14px;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 650;
}

.user-form :deep(.el-button--primary) {
  border-color: var(--primary-color);
  background: var(--primary-color);
}

.user-form :deep(.el-button--primary:not(:disabled):hover) {
  border-color: var(--primary-hover);
  background: var(--primary-hover);
}

.user-form :deep(.el-button:focus-visible) {
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}

.user-form :deep(.el-button.is-disabled) {
  color: var(--text-disabled);
  background: var(--bg-input);
  border-color: var(--border-light);
}

/* ── 安全面板 ───────────────────────────────── */
.security-hero .hero-name {
  font-size: 22px;
}

.security-panel {
  max-width: 560px;
  width: 100%;
  margin: 0 auto;
  padding: 20px 22px 22px;
  border: 1px solid var(--border-light);
  border-radius: 14px;
  background: color-mix(in srgb, var(--surface-solid) 92%, transparent);
}

/* ── 响应式 ─────────────────────────────────── */
@media (max-width: 900px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .user-view {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }

  .user-rail {
    min-height: auto;
    padding: 12px;
    border-right: 0;
    border-bottom: 1px solid var(--border-light);
  }

  .rail-account {
    display: none;
  }

  .stats-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .stats-cell:nth-child(2n) {
    border-right: 0;
  }

  .stats-cell:nth-child(-n + 2) {
    border-bottom: 1px solid var(--border-light);
  }
}
</style>
