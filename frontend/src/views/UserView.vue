<!-- 用户个人中心页面 — 头像上传、用户名/邮箱、注册日期及统计数据展示 -->
<template>
  <div class="user-view">
    <section class="page-header panel">
      <div class="page-title">
        <span class="title-icon"><el-icon><User /></el-icon></span>
        <div class="page-title-copy">
          <span class="page-kicker">ACCOUNT</span>
          <h1>个人中心</h1>
        </div>
      </div>
      <span class="account-status"><i aria-hidden="true"></i>账户信息</span>
    </section>

    <section class="profile-summary panel">
      <el-upload
        class="avatar-uploader"
        action="/api/upload/avatar"
        :show-file-list="false"
        :on-success="handleAvatarSuccess"
      >
        <el-avatar :src="userInfo.avatar" :size="52" class="user-avatar">
          <el-icon :size="25"><User /></el-icon>
        </el-avatar>
        <span class="avatar-edit" title="更换头像"><el-icon><Camera /></el-icon></span>
      </el-upload>
      <div class="identity">
        <strong>{{ userInfo.username }}</strong>
        <span>{{ userInfo.email || '未设置邮箱' }}</span>
      </div>
      <div class="registration">
        <el-icon><Calendar /></el-icon>
        <span>注册于 {{ formatDate(userInfo.createdAt) }}</span>
      </div>
    </section>

    <section class="stats-grid">
        <div class="stat-card panel conversations">
          <div class="stat-icon conversations">
            <el-icon><ChatDotRound /></el-icon>
          </div>
          <div class="stat-content">
            <div class="stat-value">{{ stats.conversations }}</div>
            <div class="stat-label">对话数</div>
          </div>
        </div>
        <div class="stat-card panel roles">
          <div class="stat-icon roles">
            <el-icon><UserFilled /></el-icon>
          </div>
          <div class="stat-content">
            <div class="stat-value">{{ stats.roles }}</div>
            <div class="stat-label">角色数</div>
          </div>
        </div>
        <div class="stat-card panel messages">
          <div class="stat-icon messages">
            <el-icon><Message /></el-icon>
          </div>
          <div class="stat-content">
            <div class="stat-value">{{ stats.messages }}</div>
            <div class="stat-label">消息数</div>
          </div>
        </div>
    </section>

    <section class="content-grid">
        <div class="content-card panel">
          <div class="card-header">
            <span class="section-icon"><el-icon><User /></el-icon></span>
            <div>
              <span class="card-kicker">PROFILE</span>
              <h2 class="card-title">个人信息</h2>
              <p class="card-subtitle">管理您的个人资料信息</p>
            </div>
          </div>
          <div class="card-body">
            <el-form :model="userInfo" label-position="top" class="profile-form">
              <el-form-item label="用户名">
                <el-input 
                  v-model="userInfo.username" 
                  disabled
                  class="custom-input"
                />
                <div class="form-hint">用户名不可修改</div>
              </el-form-item>
              
              <el-form-item label="邮箱地址">
                <el-input 
                  v-model="userInfo.email" 
                  placeholder="请输入邮箱地址"
                  class="custom-input"
                />
                <div class="form-hint">用于接收重要通知和找回密码</div>
              </el-form-item>

              <el-form-item>
                <el-button type="primary" @click="updateProfile">
                  <el-icon><Check /></el-icon>
                  <span>保存更改</span>
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </div>

        <div class="content-card panel">
          <div class="card-header">
            <span class="section-icon"><el-icon><Lock /></el-icon></span>
            <div>
              <span class="card-kicker">SECURITY</span>
              <h2 class="card-title">账户安全</h2>
              <p class="card-subtitle">修改密码和账户安全设置</p>
            </div>
          </div>
          <div class="card-body">
            <el-form :model="accountForm" label-position="top" class="security-form">
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
                <el-button @click="changePassword">
                  <el-icon><Lock /></el-icon>
                  <span>修改密码</span>
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { User, Camera, Calendar, ChatDotRound, UserFilled, Message, Check, Lock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { useRoleStore } from '@/stores/role'
import { useChatStore } from '@/stores/chat'
import { userApi } from '@/services/api/user'

const userStore = useUserStore()
const roleStore = useRoleStore()
const chatStore = useChatStore()

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

const formatDate = (date: Date | string | undefined) => {
  if (!date) return '未知'
  const d = new Date(date)
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
    // 更新store中的用户信息
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
  height: 100%;
  overflow-y: auto;
  background: var(--bg-app);
  padding: var(--page-padding-y) var(--page-padding-x);
}

.user-container {
  max-width: var(--page-content-max-width);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-xl);
}

/* 用户信息头部卡片 */
.profile-header-card {
  position: relative;
  background: var(--surface-solid);
  border-radius: 20px;
  border: 1px solid var(--border-light);
  overflow: hidden;
  transition: all 0.3s ease;
}

.profile-background {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 120px;
  background: linear-gradient(135deg, rgba(79, 70, 229, 0.08) 0%, rgba(99, 102, 241, 0.05) 100%);
  z-index: 0;
}

.profile-content {
  position: relative;
  z-index: 1;
  padding: 32px;
}

.avatar-section {
  display: flex;
  align-items: center;
  gap: 24px;
}

.avatar-wrapper {
  position: relative;
  flex-shrink: 0;
}

.avatar-uploader {
  position: relative;
  cursor: pointer;
  
  :deep(.el-upload) {
    border: none;
    background: transparent;
  }
}

.user-avatar {
  border: 4px solid var(--surface-solid);
  transition: transform 0.3s ease;
}

.avatar-overlay {
  position: absolute;
  bottom: 0;
  right: 0;
  width: 36px;
  height: 36px;
  background: var(--primary-color);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  border: 3px solid var(--surface-solid);
  opacity: 0;
  transition: opacity 0.3s ease;
  cursor: pointer;
}

.avatar-wrapper:hover .avatar-overlay {
  opacity: 1;
}

.avatar-wrapper:hover .user-avatar {
  transform: scale(1.05);
}

.user-basic-info {
  flex: 1;
}

.username {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px 0;
  letter-spacing: -0.02em;
}

.user-email {
  font-size: 15px;
  color: var(--text-secondary);
  margin: 0 0 16px 0;
  font-weight: 400;
}

.user-meta {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  
  .el-icon {
    font-size: 14px;
  }
}

/* 统计卡片网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--page-gap);
}

.stat-card {
  background: var(--surface-solid);
  border: 1px solid var(--border-light);
  border-radius: 16px;
  padding: 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  transition: all 0.3s ease;
}

.stat-card:hover {
  border-color: var(--primary-color);
  transform: translateY(-2px);
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  flex-shrink: 0;
  
  &.conversations {
    background: color-mix(in srgb, var(--primary-color) 10%, transparent);
    color: var(--primary-color);
  }
  
  &.roles {
    background: rgba(16, 185, 129, 0.1);
    color: #10b981;
  }
  
  &.messages {
    background: rgba(59, 130, 246, 0.1);
    color: #3b82f6;
  }
}

.stat-content {
  flex: 1;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
  margin-bottom: 4px;
  letter-spacing: -0.01em;
}

.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}

/* 内容网格 */
.content-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: var(--page-gap);
}

.content-card {
  background: var(--surface-solid);
  border: 1px solid var(--border-light);
  border-radius: 20px;
  overflow: hidden;
  transition: all 0.3s ease;
}

.content-card:hover {
  border-color: var(--border-hover);
}

.card-header {
  padding: var(--space-xl) var(--space-xl) 0;
  border-bottom: 1px solid var(--border-light);
  margin-bottom: var(--space-xl);
}

.card-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px 0;
  letter-spacing: -0.01em;
}

.card-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 var(--space-lg) 0;
  font-weight: 400;
}

.card-body {
  padding: 0 var(--space-xl) var(--space-xl);
}

/* 表单样式 */
.profile-form,
.security-form {
  .el-form-item {
    margin-bottom: 24px;
  }
  
  :deep(.el-form-item__label) {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 8px;
    padding: 0;
  }
}

.custom-input {
  :deep(.el-input__wrapper) {
    border-radius: 10px;
    border: 1px solid var(--border-light);
    background: var(--bg-input);
    transition: all 0.2s ease;
    box-shadow: none;
  }
  
  :deep(.el-input__wrapper:hover) {
    border-color: var(--border-hover);
    background: var(--surface-solid);
  }
  
  :deep(.el-input__wrapper.is-focus) {
    border-color: var(--primary-color);
    background: var(--surface-solid);
    box-shadow: 0 0 0 3px var(--primary-fade);
  }
}

.form-hint {
  font-size: 12px;
  color: var(--text-disabled);
  margin-top: 6px;
  line-height: 1.4;
}

/* 按钮样式 */
.save-button {
  width: 100%;
  padding: 12px 24px;
  background: var(--primary-color);
  color: #ffffff;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: all 0.2s ease;
  font-family: inherit;
}

.save-button:hover {
  background: var(--primary-hover);
  transform: translateY(-1px);
}

.save-button:active {
  transform: translateY(0);
}

.save-button.secondary {
  background: var(--surface-solid);
  color: var(--primary-color);
  border: 1px solid var(--primary-color);
}

.save-button.secondary:hover {
  background: var(--primary-fade);
  border-color: var(--primary-hover);
}

/* 响应式设计 */
@media (max-width: 768px) {
  .user-view {
    padding: var(--space-lg) var(--space-md);
  }

  .profile-content {
    padding: var(--space-xl);
  }

  .avatar-section {
    flex-direction: column;
    align-items: center;
    text-align: center;
  }

  .content-grid {
    grid-template-columns: 1fr;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }
}

/* 去除深层次阴影和渐变 */
:deep(.el-card) {
  box-shadow: none !important;
  border: 1px solid var(--border-light) !important;
}

:deep(.el-card__header) {
  border-bottom: 1px solid var(--border-light) !important;
  padding: 20px 24px !important;
}

:deep(.el-tabs__header) {
  border-bottom: 1px solid var(--border-light) !important;
  margin: 0 0 24px 0 !important;
}

:deep(.el-tabs__item) {
  font-weight: 500 !important;
  color: var(--text-secondary) !important;
  padding: 0 20px !important;
  
  &.is-active {
    color: var(--primary-color) !important;
    font-weight: 600 !important;
  }
}

:deep(.el-upload) {
  border: none !important;
}

/* 与管理页面统一为紧凑、连续的工作区。 */
.user-view {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  color: var(--text-primary);
}

.panel {
  background: color-mix(in srgb, var(--bg-card) 90%, transparent);
  border: 1px solid var(--border-light);
  border-radius: 7px;
  box-shadow: none;
}

.page-header {
  box-sizing: border-box;
  min-height: 50px;
  padding: 7px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.page-title,
.profile-summary,
.registration,
.card-header {
  display: flex;
  align-items: center;
}

.page-title {
  gap: 9px;
}

.page-title h1 {
  margin: 0;
  font-size: 18px;
  line-height: 1.2;
}

.title-icon,
.section-icon {
  display: grid;
  place-items: center;
  color: var(--primary-color);
  background: var(--primary-fade);
  border: 1px solid var(--primary-line);
  border-radius: 6px;
}

.title-icon {
  width: 28px;
  height: 28px;
}

.account-status {
  height: 28px;
  padding: 0 9px;
  display: inline-flex;
  align-items: center;
  color: var(--primary-color);
  background: var(--primary-fade);
  border-radius: 999px;
  font-size: 11px;
}

.profile-summary {
  min-height: 76px;
  box-sizing: border-box;
  padding: 10px 12px;
  gap: 12px;
}

.avatar-uploader {
  position: relative;
  flex: 0 0 auto;
}

.user-avatar {
  border: 1px solid var(--primary-line);
  background: var(--primary-fade);
  color: var(--primary-color);
}

.avatar-edit {
  position: absolute;
  right: -2px;
  bottom: 1px;
  width: 19px;
  height: 19px;
  display: grid;
  place-items: center;
  color: #fff;
  background: var(--primary-color);
  border: 2px solid var(--bg-card);
  border-radius: 50%;
  font-size: 10px;
}

.identity {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.identity strong {
  font-size: 15px;
}

.identity span,
.registration {
  color: var(--text-secondary);
  font-size: 12px;
}

.identity span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.registration {
  margin-left: auto;
  gap: 6px;
  white-space: nowrap;
}

.stats-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.stat-card {
  position: relative;
  min-height: 72px;
  box-sizing: border-box;
  padding: 10px 12px;
  gap: 10px;
  border-radius: 7px;
  overflow: hidden;
  transition: border-color 0.2s ease;
}

.stat-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 2px;
  background: var(--primary-color);
}

.stat-card.roles::before {
  background: #4d8f72;
}

.stat-card.messages::before {
  background: #b38a3e;
}

.stat-card:hover {
  border-color: var(--border-hover);
  transform: none;
}

.stat-icon {
  width: 34px;
  height: 34px;
  border-radius: 6px;
  font-size: 17px;
}

.stat-value {
  margin: 0 0 2px;
  font-size: 18px;
}

.stat-label {
  font-size: 11px;
}

.content-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  align-items: start;
}

.content-card {
  border-radius: 7px;
  transition: border-color 0.2s ease;
}

.card-header {
  min-height: 54px;
  box-sizing: border-box;
  padding: 9px 12px;
  margin: 0;
  gap: 9px;
}

.section-icon {
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
}

.card-title {
  margin: 0;
  font-size: 15px;
  letter-spacing: 0;
}

.card-subtitle {
  margin: 2px 0 0;
  font-size: 11px;
}

.card-body {
  padding: 12px;
}

.profile-form .el-form-item,
.security-form .el-form-item {
  margin-bottom: 14px;
}

.profile-form .el-form-item:last-child,
.security-form .el-form-item:last-child {
  margin: 2px 0 0;
}

.profile-form :deep(.el-form-item__label),
.security-form :deep(.el-form-item__label) {
  margin-bottom: 5px;
  font-size: 12px;
  line-height: 18px;
}

.custom-input :deep(.el-input__wrapper) {
  min-height: 32px;
  border-radius: 6px;
}

.form-hint {
  margin-top: 4px;
  font-size: 11px;
}

.card-body :deep(.el-button) {
  height: 30px;
  min-width: 96px;
  padding: 0 12px;
  border-radius: 6px;
  font-size: 12px;
}

@media (max-width: 760px) {
  .user-view {
    padding: var(--space-md);
    gap: var(--space-md);
  }

  .profile-summary {
    flex-wrap: wrap;
  }

  .registration {
    width: 100%;
    margin-left: 64px;
  }

  .stats-grid,
  .content-grid {
    grid-template-columns: 1fr;
  }
}
</style>

<style scoped lang="scss">
/* Account surface: a quiet, grouped settings layout inspired by Apple HIG. */
.user-view {
  box-sizing: border-box;
  min-height: 100%;
  padding: clamp(24px, 4vw, 48px) clamp(20px, 5vw, 72px) 64px;
  gap: 14px;
  background: var(--bg-app);
}

.user-view > * {
  width: min(100%, 1180px);
  margin-right: auto;
  margin-left: auto;
}

.panel {
  border: 1px solid color-mix(in srgb, var(--border-light) 88%, transparent);
  border-radius: 16px;
  background: color-mix(in srgb, var(--surface-solid) 92%, transparent);
  box-shadow: none;
}

.page-header {
  min-height: 68px;
  box-sizing: border-box;
  padding: 0 4px 16px;
  border: 0;
  border-bottom: 1px solid var(--border-light);
  border-radius: 0;
  background: transparent;
}

.page-title { gap: 12px; }

.title-icon {
  width: 38px;
  height: 38px;
  border: 0;
  border-radius: 12px;
  color: var(--primary-color);
  background: var(--primary-fade);
  font-size: 18px;
}

.page-title-copy { display: grid; gap: 3px; }
.page-kicker,
.card-kicker {
  color: var(--primary-color);
  font: 10px var(--font-mono, monospace);
  letter-spacing: .1em;
}

.page-title h1 {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-serif);
  font-size: clamp(24px, 2vw, 30px);
  font-weight: 650;
  letter-spacing: -.025em;
}

.account-status {
  height: 30px;
  padding: 0 11px;
  gap: 6px;
  border: 1px solid color-mix(in srgb, var(--primary-color) 20%, var(--border-light));
  border-radius: 999px;
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--primary-fade) 60%, transparent);
  font-size: 11px;
}

.account-status i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
}

.profile-summary {
  min-height: 112px;
  box-sizing: border-box;
  padding: 20px 22px;
  gap: 15px;
  background: var(--surface-solid);
}

.avatar-uploader :deep(.el-upload) { border: 0; background: transparent; }

.user-avatar {
  width: 68px !important;
  height: 68px !important;
  border: 1px solid color-mix(in srgb, var(--primary-color) 24%, var(--border-light));
  color: var(--primary-color);
  background: var(--primary-fade);
  font-size: 27px;
}

.avatar-edit {
  right: -3px;
  bottom: 1px;
  width: 23px;
  height: 23px;
  border: 2px solid var(--surface-solid);
  color: var(--surface-solid);
  background: var(--primary-color);
  font-size: 11px;
}

.avatar-uploader:hover .user-avatar { transform: none; border-color: var(--primary-color); }
.identity { gap: 5px; }
.identity strong { color: var(--text-primary); font-size: 18px; font-weight: 700; letter-spacing: -.015em; }
.identity span { color: var(--text-secondary); font-size: 12px; }
.registration { gap: 7px; color: var(--text-secondary); font-size: 11px; }
.registration .el-icon { color: var(--text-muted); }

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
  overflow: hidden;
  border: 1px solid var(--border-light);
  border-radius: 16px;
  background: var(--surface-solid);
}

.stat-card {
  min-height: 82px;
  box-sizing: border-box;
  padding: 16px 20px;
  border: 0;
  border-right: 1px solid var(--border-light);
  border-radius: 0;
  gap: 12px;
  background: transparent;
  transition: background-color 180ms var(--ease-out);
}

.stat-card:last-child { border-right: 0; }
.stat-card::before { display: none; }
.stat-card:hover { border-color: var(--border-light); background: var(--bg-input); transform: none; }

.stat-icon,
.stat-icon.conversations,
.stat-icon.roles,
.stat-icon.messages {
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 10px;
  color: var(--primary-color);
  background: var(--primary-fade);
  font-size: 18px;
}

.stat-content { min-width: 0; }
.stat-value { margin: 0 0 3px; color: var(--text-primary); font: 700 20px/1 var(--font-sans); letter-spacing: -.02em; }
.stat-label { color: var(--text-secondary); font-size: 11px; font-weight: 500; }

.content-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  align-items: start;
}

.content-card {
  overflow: hidden;
  border-radius: 16px;
  background: var(--surface-solid);
  transition: border-color 180ms var(--ease-out);
}

.content-card:hover { border-color: var(--border-hover); }

.card-header {
  min-height: 76px;
  box-sizing: border-box;
  padding: 18px 22px;
  gap: 12px;
  border-bottom: 1px solid var(--border-light);
}

.section-icon {
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 10px;
  color: var(--primary-color);
  background: var(--primary-fade);
  font-size: 17px;
}

.card-kicker { display: block; margin-bottom: 3px; font-size: 9px; }
.card-title { margin: 0; color: var(--text-primary); font-size: 16px; font-weight: 650; letter-spacing: -.01em; }
.card-subtitle { margin: 3px 0 0; color: var(--text-secondary); font-size: 11px; }
.card-body { padding: 20px 22px 22px; }

.profile-form .el-form-item,
.security-form .el-form-item { margin-bottom: 17px; }
.profile-form .el-form-item:last-child,
.security-form .el-form-item:last-child { margin-top: 2px; margin-bottom: 0; }

.profile-form :deep(.el-form-item__label),
.security-form :deep(.el-form-item__label) {
  margin-bottom: 7px;
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

.custom-input :deep(.el-input__inner) { color: var(--text-primary); font-size: 12px; }
.custom-input :deep(.el-input__inner::placeholder) { color: var(--text-disabled); }
.custom-input :deep(.el-input__wrapper:hover) { border-color: var(--border-hover); background: var(--surface-solid); }
.custom-input :deep(.el-input__wrapper.is-focus) { border-color: var(--primary-color); background: var(--surface-solid); box-shadow: 0 0 0 3px var(--primary-fade); }
.custom-input :deep(.el-input.is-disabled .el-input__wrapper) { border-color: var(--border-light); background: var(--bg-input); }

.form-hint { margin-top: 5px; color: var(--text-disabled); font-size: 11px; line-height: 1.45; }

.card-body :deep(.el-button) {
  min-width: 104px;
  height: 36px;
  padding: 0 14px;
  border: 1px solid var(--border-light);
  border-radius: 9px;
  color: var(--text-secondary);
  background: var(--surface-solid);
  font-size: 12px;
  font-weight: 650;
  box-shadow: none;
  transition: background-color 180ms var(--ease-out), border-color 180ms var(--ease-out), color 180ms var(--ease-out);
}

.card-body :deep(.el-button:hover) { border-color: var(--border-hover); color: var(--text-primary); background: var(--bg-input); }
.card-body :deep(.el-button--primary) { border-color: var(--primary-color); color: #fff; background: var(--primary-color); }
.card-body :deep(.el-button--primary:hover) { border-color: var(--primary-hover); color: #fff; background: var(--primary-hover); }
.card-body :deep(.el-button:focus-visible) { outline: 2px solid var(--primary-color); outline-offset: 2px; }

@media (max-width: 900px) {
  .content-grid { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .user-view { padding: 20px 14px 40px; gap: 12px; }
  .page-header { align-items: flex-start; min-height: 62px; }
  .page-title h1 { font-size: 23px; }
  .account-status { height: 28px; padding: 0 8px; font-size: 10px; }
  .profile-summary { align-items: flex-start; flex-wrap: wrap; padding: 16px; }
  .user-avatar { width: 56px !important; height: 56px !important; }
  .registration { width: 100%; margin-left: 71px; }
  .stats-grid { grid-template-columns: 1fr; }
  .stat-card { min-height: 68px; border-right: 0; border-bottom: 1px solid var(--border-light); }
  .stat-card:last-child { border-bottom: 0; }
  .card-header, .card-body { padding-right: 16px; padding-left: 16px; }
}
</style>


