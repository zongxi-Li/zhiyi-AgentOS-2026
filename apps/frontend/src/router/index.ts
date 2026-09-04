import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { authApi } from '@/services/api/auth'
import { isDesktop } from '@/platform'
import LoginView from '@/views/LoginView.vue'
import SettingsView from '@/views/SettingsView.vue'
import UserView from '@/views/UserView.vue'
// Sidebar destinations are part of the desktop shell's primary workflow.
// Keep them in the entry graph so a Tauri WebView never blanks the outgoing
// view while waiting for a route chunk that may be stale or unavailable.
import HistoryView from '@/views/HistoryView.vue'
import RoleView from '@/views/RoleView.vue'
import ResourceCenterView from '@/views/ResourceCenterView.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Landing',
    component: () => import('@/views/LandingView.vue'),
    meta: {
      title: '首页',
      requiresAuth: false
    }
  },
  {
    path: '/login',
    name: 'Login',
    // Authentication is the recovery surface after logout and token expiry.
    // Keep it in the entry bundle so a missing/stale route chunk cannot leave
    // the user with no page to recover the session.
    component: LoginView,
    meta: {
      title: '登录',
      requiresAuth: false
    }
  },
  {
    path: '/user',
    name: 'User',
    component: UserView,
    meta: {
      title: '用户中心',
      requiresAuth: true
    }
  },
  {
    path: '/info',
    name: 'Info',
    component: () => import('@/views/InfoView.vue'),
    meta: {
      title: '信息入口',
      requiresAuth: true
    }
  },
  {
    path: '/history',
    name: 'History',
    component: HistoryView,
    meta: {
      title: '历史记录',
      requiresAuth: true
    }
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('@/views/ChatView.vue'),
    meta: {
      title: '对话',
      requiresAuth: true
    }
  },
  {
    path: '/roles',
    name: 'Roles',
    component: RoleView,
    meta: {
      title: '角色管理',
      requiresAuth: true
    }
  },
  {
    path: '/create-role',
    name: 'CreateRole',
    component: () => import('@/views/CreateRoleView.vue'),
    meta: {
      title: '创建角色',
      requiresAuth: true
    }
  },
  {
    path: '/settings',
    name: 'Settings',
    // Settings is the main route used to recover identity and client state.
    // It should remain available even when a deployed lazy chunk is stale.
    component: SettingsView,
    meta: {
      title: '设置',
      requiresAuth: true
    }
  },
  {
    path: '/rag',
    name: 'RAG',
    component: () => import('@/views/RagView.vue'),
    meta: {
      title: '知识库查询',
      requiresAuth: true
    }
  },
  {
    path: '/federated-models',
    name: 'FederatedModelManagement',
    component: () => import('@/views/FederatedModelManagementView.vue'),
    meta: {
      title: '联邦模型管理',
      requiresAuth: true
    }
  },
  {
    path: '/federated-learning',
    name: 'FederatedLearning',
    component: () => import('@/views/FederatedLearningView.vue'),
    meta: {
      title: '联邦学习管理',
      requiresAuth: true
    }
  },
  {
    path: '/federated-agent-workbench',
    name: 'FederatedAgentWorkbench',
    redirect: { path: '/chat', query: { workspace: 'agent' } }
  },
  {
    path: '/agentos-console',
    name: 'AgentOsConsole',
    component: () => import('@/views/AgentOsConsoleView.vue'),
    meta: {
      title: 'ACG 历史记录',
      requiresAuth: true
    }
  },
  {
    path: '/agentos/legal/contract-review',
    redirect: { path: '/chat', query: { workspace: 'agent' } }
  },
  {
    path: '/agentos/acg',
    name: 'AcgVisualization',
    component: () => import('@/views/AcgEntryView.vue'),
    meta: {
      title: 'ACG 动态群体智能引擎',
      requiresAuth: true
    }
  },
  {
    path: '/agentos/resources',
    name: 'ResourceCenter',
    component: ResourceCenterView,
    meta: {
      title: 'Resource Center',
      requiresAuth: true
    }
  },
  {
    path: '/agentos/missions/new',
    name: 'CreateMission',
    component: () => import('@/views/CreateMissionView.vue'),
    meta: {
      title: '新建工程',
      requiresAuth: true
    }
  },
  {
    path: '/agentos/missions/:missionId/workspace',
    name: 'MissionWorkspace',
    component: () => import('@/views/MissionWorkspaceView.vue'),
    meta: {
      title: 'Mission Project Workspace',
      requiresAuth: true
    }
  },
  {
    path: '/contract-clause-planner',
    name: 'ContractClausePlanner',
    redirect: {
      path: '/chat',
      query: { workspace: 'agent' }
    }
  },
  {
    path: '/voice-chat',
    name: 'VoiceChat',
    component: () => import('@/views/VoiceChatView.vue'),
    meta: {
      title: '语音讲解',
      requiresAuth: true
    }
  }
]

const router = createRouter({
  // Tauri's bundled WebView has no server fallback for deep links. Keep the
  // browser URL contract unchanged and use hashes only inside the desktop shell.
  history: isDesktop() ? createWebHashHistory() : createWebHistory(),
  routes
})

const ROUTE_CHUNK_RELOAD_KEY = 'kinlin:route-chunk-reload'
const isRouteChunkError = (error: unknown) => {
  const message = error instanceof Error ? error.message : String(error)
  return /Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk .* failed|ChunkLoadError/i.test(message)
}

// A long-lived tab can keep an old index while a deployment replaces hashed
// route chunks. Retry the failed navigation once so a normal click recovers
// without asking the user to refresh manually, while avoiding a reload loop
// when the chunk is genuinely unavailable.
router.onError((error, to, from) => {
  if (!isRouteChunkError(error)) return

  if (sessionStorage.getItem(ROUTE_CHUNK_RELOAD_KEY) === to.fullPath) {
    sessionStorage.removeItem(ROUTE_CHUNK_RELOAD_KEY)
    if (from.fullPath !== to.fullPath) {
      void router.replace(from.fullPath)
    }
    window.dispatchEvent(new CustomEvent('global-error', {
      detail: { message: '页面资源加载失败，已返回上一页，请稍后重试。' }
    }))
    return
  }

  sessionStorage.setItem(ROUTE_CHUNK_RELOAD_KEY, to.fullPath)
  window.location.reload()
})

router.afterEach((to) => {
  if (sessionStorage.getItem(ROUTE_CHUNK_RELOAD_KEY) === to.fullPath) {
    sessionStorage.removeItem(ROUTE_CHUNK_RELOAD_KEY)
  }
})

const clearAuthState = () => {
  localStorage.removeItem('token')
  localStorage.removeItem('userId')
}

const normalizeRedirect = (redirect?: string) => {
  if (!redirect) return '/chat'
  if (!redirect.startsWith('/') || redirect.startsWith('//')) return '/chat'
  return redirect
}

// Global route guard
router.beforeEach(async (to, _from, next) => {
  document.title = to.meta.title ? `${to.meta.title} - 知弈AgentOS` : '知弈AgentOS'

  const token = localStorage.getItem('token')
  const requiresAuth = Boolean(to.meta.requiresAuth)

  // The desktop shell opens on the authenticated product surface. Keep the
  // public landing page as the browser entry point, but never show it inside
  // the Tauri app before login.
  if (to.path === '/' && isDesktop()) {
    next({ path: '/login', replace: true })
    return
  }

  // Validate login state for protected routes
  if (requiresAuth) {
    if (!token) {
      next(`/login?redirect=${encodeURIComponent(to.fullPath)}`)
      return
    }

    try {
      const result = await authApi.verifyToken()
      if (!result.valid) {
        clearAuthState()
        next(`/login?redirect=${encodeURIComponent(to.fullPath)}`)
        return
      }
    } catch {
      clearAuthState()
      next('/login')
      return
    }
  }

  // 已登录时访问登录页，回到来源页（如果有）或默认聊天页。
  if (to.path === '/login' && token) {
    try {
      const result = await authApi.verifyToken()
      if (result.valid) {
        const redirect = normalizeRedirect(typeof to.query.redirect === 'string' ? to.query.redirect : undefined)
        next(redirect)
        return
      }
      clearAuthState()
    } catch {
      clearAuthState()
    }
  }

  next()
})

export default router


