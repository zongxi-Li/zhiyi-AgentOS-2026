<template>
  <main class="auth-view">
    <header class="auth-topbar">
      <a class="auth-brand" href="/" aria-label="知弈 AgentOS 首页">
        <span class="auth-brand__logo"><img src="/logo.png" alt="" aria-hidden="true" /></span>
        <span>知弈 <strong>AgentOS</strong></span>
      </a>
      <span class="auth-topbar__note">More Agents <i aria-hidden="true">·</i> More Possibilities</span>
    </header>

    <div class="auth-layout">
      <section class="auth-intro" aria-labelledby="auth-title">
        <p class="auth-eyebrow">DYNAMIC HETEROGENEOUS AGENT SWARM</p>
        <h1 id="auth-title">让复杂工作<br /><span>在协作中涌现答案</span></h1>
        <p class="auth-intro__lead">连接知识、模型与智能体，让每一个专业任务从规划到交付持续推进。</p>
        <div class="auth-intro__features" aria-label="产品能力">
          <span><b>01</b> 多智能体协作</span>
          <span><b>02</b> 动态任务规划</span>
          <span><b>03</b> 异构资源调度</span>
          <span><b>04</b> 自进化学习</span>
        </div>
      </section>

      <section class="auth-card" data-testid="auth-card" aria-labelledby="auth-card-title">
        <div class="auth-card__mark" aria-hidden="true"><img src="/logo.png" alt="" /></div>
        <div class="auth-card__heading">
          <h2 id="auth-card-title">欢迎回来</h2>
          <p>{{ activeTab === 'login' ? '登录知弈 AgentOS，开启智能之旅' : '创建你的知弈 AgentOS 工作空间' }}</p>
        </div>

        <el-tabs v-model="activeTab" class="auth-tabs" stretch>
          <el-tab-pane label="登录" name="login">
            <el-form ref="loginFormRef" :model="loginForm" :rules="loginRules" label-position="top" class="auth-form">
              <el-form-item label="用户名 / 邮箱 / 手机号" prop="username">
                <el-input v-model="loginForm.username" :prefix-icon="User" placeholder="请输入用户名、邮箱或手机号" autocomplete="username" />
              </el-form-item>
              <el-form-item label="密码" prop="password">
                <el-input v-model="loginForm.password" type="password" :prefix-icon="Lock" placeholder="请输入密码" autocomplete="current-password" show-password @keyup.enter="handleLogin" />
              </el-form-item>
              <div class="auth-form__options">
                <el-checkbox v-model="loginForm.remember">记住我</el-checkbox>
                <button class="text-action" type="button" @click="showUnavailable('忘记密码')">忘记密码？</button>
              </div>
              <el-button type="primary" class="auth-submit" data-testid="auth-submit" :loading="loading" @click="handleLogin">登录</el-button>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="注册" name="register">
            <el-form ref="registerFormRef" :model="registerForm" :rules="registerRules" label-position="top" class="auth-form">
              <el-form-item label="用户名" prop="username">
                <el-input v-model="registerForm.username" :prefix-icon="User" placeholder="设置用户名" autocomplete="username" />
              </el-form-item>
              <el-form-item label="邮箱" prop="email">
                <el-input v-model="registerForm.email" :prefix-icon="Message" placeholder="请输入邮箱" autocomplete="email" />
              </el-form-item>
              <el-form-item label="密码" prop="password">
                <el-input v-model="registerForm.password" type="password" :prefix-icon="Lock" placeholder="设置登录密码" autocomplete="new-password" show-password />
              </el-form-item>
              <el-form-item label="确认密码" prop="confirmPassword">
                <el-input v-model="registerForm.confirmPassword" type="password" :prefix-icon="Lock" placeholder="再次输入密码" autocomplete="new-password" show-password @keyup.enter="handleRegister" />
              </el-form-item>
              <el-button type="primary" class="auth-submit" data-testid="auth-submit" :loading="loading" @click="handleRegister">立即注册</el-button>
            </el-form>
          </el-tab-pane>
        </el-tabs>

        <div class="auth-divider"><span>或使用以下方式登录</span></div>
        <div class="auth-providers" aria-label="第三方登录">
          <button type="button" aria-label="微信登录" @click="showUnavailable('微信登录')"><el-icon><ChatDotRound /></el-icon></button>
          <button type="button" aria-label="GitHub 登录" @click="showUnavailable('GitHub 登录')"><el-icon><Connection /></el-icon></button>
          <button type="button" aria-label="企业账号登录" @click="showUnavailable('企业账号登录')"><el-icon><OfficeBuilding /></el-icon></button>
        </div>
        <p class="auth-switch">还没有账户？ <button type="button" @click="activeTab = 'register'">立即注册</button></p>
        <p class="auth-legal">登录即表示你同意遵守平台使用规范与隐私政策。</p>
      </section>
    </div>

    <footer class="auth-footer"><span>© 2025 知弈 AgentOS</span><span>智能协作 · 共创未来</span></footer>
  </main>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotRound, Connection, Lock, Message, OfficeBuilding, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { authApi } from '@/services/api/auth'

const router = useRouter()
const route = useRoute()
const activeTab = ref('login')
const loading = ref(false)
const loginFormRef = ref<FormInstance>()
const registerFormRef = ref<FormInstance>()
const loginForm = reactive({ username: '', password: '', remember: false })
const registerForm = reactive({ username: '', email: '', password: '', confirmPassword: '' })

const loginRules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
  ]
}

const registerRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, message: '用户名长度不能少于3位', trigger: 'blur' }
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== registerForm.password) callback(new Error('两次输入密码不一致'))
        else callback()
      },
      trigger: 'blur'
    }
  ]
}

const showUnavailable = (feature: string) => ElMessage.info(`${feature}功能即将开放`)

const handleLogin = async () => {
  if (!loginFormRef.value) return
  await loginFormRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      const response = await authApi.login({ username: loginForm.username, password: loginForm.password })
      if (response.token) {
        localStorage.setItem('token', response.token)
        localStorage.setItem('userId', response.userId?.toString() || '')
        ElMessage.success(response.message || '登录成功')
        const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/chat'
        const safeRedirect = redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/chat'
        await router.push(safeRedirect)
      } else {
        ElMessage.error(response.message || '登录失败')
      }
    } catch (error: any) {
      ElMessage.error(error.response?.data?.message || error.message || '登录失败')
    } finally {
      loading.value = false
    }
  })
}

const handleRegister = async () => {
  if (!registerFormRef.value) return
  await registerFormRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      const response = await authApi.register({ username: registerForm.username, email: registerForm.email, password: registerForm.password })
      if (response.token || response.message) {
        ElMessage.success(response.message || '注册成功，请登录')
        activeTab.value = 'login'
        loginForm.username = registerForm.username
      } else {
        ElMessage.error(response.message || '注册失败')
      }
    } catch (error: any) {
      ElMessage.error(error.response?.data?.message || error.message || '注册失败')
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped lang="scss">
.auth-view {
  --auth-ink: #102a56;
  --auth-muted: #6c85ad;
  --auth-blue: #249ef0;
  --auth-purple: #6654f4;
  position: relative;
  min-height: 100vh;
  min-height: 100dvh;
  overflow: hidden;
  color: var(--auth-ink);
  background: #dcecff url('/bg.jpeg') center / cover fixed no-repeat;
}
.auth-view::before { content: ''; position: fixed; inset: 0; pointer-events: none; background: linear-gradient(90deg, rgba(246,251,255,.9) 0%, rgba(246,251,255,.6) 37%, rgba(236,246,255,.08) 77%), linear-gradient(180deg, rgba(255,255,255,.25), transparent 50%); }
.auth-topbar, .auth-layout, .auth-footer { position: relative; z-index: 1; }
.auth-topbar { width: min(100% - 96px, 1920px); min-height: 88px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; }
.auth-brand { display: inline-flex; align-items: center; gap: 12px; color: var(--auth-ink); font-size: 21px; font-weight: 650; letter-spacing: -.02em; text-decoration: none; }
.auth-brand strong { font-weight: 500; }
.auth-brand__logo { width: 36px; height: 36px; display: block; }
.auth-brand__logo img { width: 100%; height: 100%; display: block; object-fit: contain; }
.auth-topbar__note { color: #7b96bd; font-size: 11px; letter-spacing: .11em; }
.auth-topbar__note i { padding: 0 10px; color: var(--auth-blue); font-style: normal; }
.auth-layout { width: min(100% - 96px, 1420px); min-height: calc(100vh - 130px); min-height: calc(100dvh - 130px); margin: 0 auto; display: grid; grid-template-columns: minmax(360px, 1fr) minmax(420px, 520px); align-items: center; gap: clamp(70px, 11vw, 190px); padding-bottom: 44px; box-sizing: border-box; }
.auth-intro { margin-top: -5vh; }
.auth-eyebrow { margin: 0 0 22px; color: #6c8fbe; font-size: 11px; font-weight: 700; letter-spacing: .25em; }
.auth-intro h1 { margin: 0; color: var(--auth-ink); font-size: clamp(46px, 4.5vw, 75px); font-weight: 520; line-height: 1.05; letter-spacing: -.065em; }
.auth-intro h1 span { color: #23508d; font-weight: 450; }
.auth-intro__lead { max-width: 520px; margin: 24px 0 0; color: var(--auth-muted); font-size: 16px; line-height: 1.8; }
.auth-intro__features { max-width: 510px; margin-top: 48px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 15px 30px; color: #53729e; font-size: 13px; }
.auth-intro__features b { margin-right: 10px; color: var(--auth-blue); font-size: 10px; letter-spacing: .08em; }
.auth-card { width: 100%; box-sizing: border-box; padding: 36px 44px 28px; border: 1px solid rgba(255,255,255,.78); border-radius: 24px; background: rgba(249,252,255,.72); box-shadow: 0 24px 70px rgba(68,111,181,.16), inset 0 1px 0 rgba(255,255,255,.86); backdrop-filter: blur(18px); }
.auth-card__mark { width: 44px; height: 44px; margin-bottom: 22px; display: grid; place-items: center; border-radius: 50%; background: linear-gradient(145deg, #d9f1ff, #b8dcff); box-shadow: 0 8px 18px rgba(36,143,240,.14); }
.auth-card__mark img { width: 29px; height: 29px; object-fit: contain; }
.auth-card__heading h2 { margin: 0; color: var(--auth-ink); font-size: 30px; font-weight: 650; letter-spacing: -.04em; }
.auth-card__heading p { margin: 8px 0 26px; color: var(--auth-muted); font-size: 13px; }
.auth-tabs :deep(.el-tabs__header) { margin-bottom: 24px; }
.auth-tabs :deep(.el-tabs__nav-wrap::after) { background: rgba(114,149,194,.2); }
.auth-tabs :deep(.el-tabs__item) { min-height: 44px; color: #7891b5; font-size: 14px; font-weight: 650; }
.auth-tabs :deep(.el-tabs__item.is-active) { color: var(--auth-ink); }
.auth-tabs :deep(.el-tabs__active-bar) { height: 3px; border-radius: 999px; background: linear-gradient(90deg, var(--auth-blue), var(--auth-purple)); }
.auth-form :deep(.el-form-item) { margin-bottom: 17px; }
.auth-form :deep(.el-form-item__label) { padding-bottom: 6px; color: #55739f; font-size: 12px; line-height: 1.2; }
.auth-form :deep(.el-input__wrapper) { min-height: 48px; padding: 0 15px; border: 1px solid rgba(150,180,220,.32); border-radius: 12px; background: rgba(255,255,255,.5); box-shadow: none; transition: border-color 180ms ease, box-shadow 180ms ease, background-color 180ms ease; }
.auth-form :deep(.el-input__wrapper:hover) { border-color: rgba(36,143,240,.5); }
.auth-form :deep(.el-input__wrapper.is-focus) { border-color: var(--auth-blue); background: rgba(255,255,255,.82); box-shadow: 0 0 0 3px rgba(36,143,240,.12); }
.auth-form :deep(.el-input__inner) { color: var(--auth-ink); font-size: 13px; }
.auth-form :deep(.el-input__inner::placeholder) { color: #99acc6; }
.auth-form :deep(.el-input__prefix) { color: #7695be; }
.auth-form__options { min-height: 34px; display: flex; align-items: center; justify-content: space-between; }
.auth-form__options :deep(.el-checkbox__label) { color: #6884ac; font-size: 12px; }
.text-action, .auth-switch button { border: 0; color: #256ef1; background: transparent; font: inherit; cursor: pointer; }
.text-action { padding: 8px 0; font-size: 12px; }
.auth-submit { width: 100%; min-height: 50px; margin-top: 10px; border: 0; border-radius: 999px; color: white; background: linear-gradient(105deg, var(--auth-blue), var(--auth-purple)); box-shadow: 0 12px 25px rgba(74,107,237,.28); font-size: 14px; font-weight: 700; letter-spacing: .08em; transition: transform 180ms ease, box-shadow 180ms ease; }
.auth-submit:hover { transform: translateY(-1px); box-shadow: 0 16px 30px rgba(74,107,237,.36); }
.auth-divider { display: flex; align-items: center; gap: 12px; margin: 25px 0 18px; color: #8da3c1; font-size: 11px; }
.auth-divider::before, .auth-divider::after { content: ''; height: 1px; flex: 1; background: rgba(114,149,194,.2); }
.auth-providers { display: flex; justify-content: center; gap: 20px; }
.auth-providers button { width: 44px; height: 44px; display: grid; place-items: center; border: 1px solid rgba(255,255,255,.8); border-radius: 50%; color: #2e75dd; background: rgba(255,255,255,.48); font-size: 19px; cursor: pointer; transition: transform 180ms ease, background-color 180ms ease; }
.auth-providers button:hover { transform: translateY(-2px); background: rgba(255,255,255,.82); }
.auth-switch { margin: 21px 0 0; color: #7790b2; font-size: 12px; text-align: center; }
.auth-switch button { padding: 4px; font-weight: 700; }
.auth-legal { margin: 19px 0 0; color: #a1b2c9; font-size: 10px; line-height: 1.6; text-align: center; }
.auth-footer { width: min(100% - 96px, 1920px); margin: -2px auto 0; padding-bottom: 20px; display: flex; justify-content: space-between; color: #6f8bae; font-size: 10px; letter-spacing: .05em; }
.auth-brand:focus-visible, .text-action:focus-visible, .auth-switch button:focus-visible, .auth-providers button:focus-visible, .auth-submit:focus-visible { outline: 3px solid rgba(36,143,240,.42); outline-offset: 3px; }
@media (max-width: 940px) { .auth-layout { width: min(100% - 56px, 680px); display: block; padding-top: 7vh; } .auth-intro { display: none; } .auth-card { max-width: 520px; margin: 0 auto; } }
@media (max-width: 560px) { .auth-view { overflow-y: auto; } .auth-topbar { width: calc(100% - 40px); min-height: 72px; } .auth-brand { font-size: 18px; } .auth-brand__logo { width: 32px; height: 32px; } .auth-topbar__note { display: none; } .auth-layout { width: calc(100% - 32px); min-height: auto; padding-top: 4vh; padding-bottom: 28px; } .auth-card { padding: 28px 22px 24px; border-radius: 20px; } .auth-card__heading h2 { font-size: 27px; } .auth-footer { width: calc(100% - 32px); padding-bottom: 16px; font-size: 9px; } }
@media (prefers-reduced-motion: reduce) { .auth-form :deep(.el-input__wrapper), .auth-submit, .auth-providers button { transition: none; } }
</style>
