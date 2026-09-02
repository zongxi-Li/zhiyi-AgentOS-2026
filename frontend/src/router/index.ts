import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { authApi } from '@/services/api/auth'
import { isDesktop } from '@/platform'

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
    component: () => import('@/views/LoginView.vue'),
    meta: {
      title: '登录',
      requiresAuth: false
    }
  },
  {
    path: '/user',
    name: 'User',
    component: () => import('@/views/UserView.vue'),
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
    component: () => import('@/views/HistoryView.vue'),
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
    component: () => import('@/views/RoleView.vue'),
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
    component: () => import('@/views/SettingsView.vue'),
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
    component: () => import('@/views/ResourceCenterView.vue'),
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


