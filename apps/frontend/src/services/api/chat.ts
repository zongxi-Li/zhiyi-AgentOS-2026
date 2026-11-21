import request from '@/utils/request'
import { AxiosError } from 'axios'
import type { ReasoningEffort, ThinkingMode } from '@/config/modelSettings'
import type { ContextMessage } from '@/features/chat/compaction'

export interface CompactResponse {
  contextUsage?: import('../../../../backend/src/shared/chat-stream/index.mjs').ContextUsage
  durable?: boolean
  projectionVersion?: number
  contextId: string
  status: 'unchanged' | 'pruned' | 'summarized' | 'no_safe_range' | 'failed_passthrough'
  messages: ContextMessage[]
  model: string
  contextWindowTokens: number
  contextFixedTokens?: number
  contextTokenMethod?: string
  metrics: Record<string, string | number | boolean>
}

export interface ChatRequest {
  text?: string
  message?: string
  roleId?: string
  contextId?: string
  workspaceMode?: 'agent' | 'chat'
  fileUrl?: string
  emotionTag?: string
  context?: Array<{ role: string; content: string }>
  model?: string
  baseUrl?: string
  apiKey?: string
  thinkingMode?: ThinkingMode
  reasoningEffort?: ReasoningEffort
  toolMode?: 'auto' | 'disabled'
}

export interface Source {
  title?: string
  filename?: string
  url?: string
  content?: string
  snippet?: string
  provider?: string
  citationId?: string
  retrievedAt?: string
}

export interface ReasoningStep {
  title: string
  description: string
}

export interface ChatResponse {
  text: string
  contextId: string
  confidence: number
  tokensUsed?: number
  animation?: any
  sources?: Source[]
  reasoningPath?: ReasoningStep[]
  modelInfo?: string
  metadata?: Record<string, any>
}

export type ChatApprovalDecision = 'allow_once' | 'allow_session' | 'deny'

export const chatApi = {
  async getContextUsage(contextId: string, model?: string, baseUrl?: string, roleId?: string | null) {
    const response = await request.get('/ai/chat/context/usage', {
      params: {context_id:contextId, model:model || undefined, base_url:baseUrl || undefined, role_id:roleId || undefined}, timeout:10000
    })
    return response.data as {contextUsage: import('../../../../backend/src/shared/chat-stream/index.mjs').ContextUsage | null}
  },
  async compactContext(payload: {
    context_id: string; context: ContextMessage[]; role_id?: string
    model?: string; base_url?: string; api_key?: string
  }, signal?: AbortSignal): Promise<CompactResponse> {
    const response = await request.post<CompactResponse>('/ai/chat/compact', payload, { signal, timeout: 130000 })
    return response.data
  },
  // 发送文本消息
  async sendMessage(chatRequest: ChatRequest): Promise<ChatResponse & { audioUrl?: string; animation?: any }> {
    const response = await request.post<ChatResponse & { audioUrl?: string; animation?: any }>('/chat/text', {
      text: chatRequest.text || chatRequest.message,
      roleId: chatRequest.roleId,
      contextId: chatRequest.contextId,
      workspaceMode: chatRequest.workspaceMode,
      fileUrl: chatRequest.fileUrl,
      context: chatRequest.context,
      model: chatRequest.model,
      baseUrl: chatRequest.baseUrl,
      apiKey: chatRequest.apiKey,
      thinkingMode: chatRequest.thinkingMode,
      reasoningEffort: chatRequest.reasoningEffort,
      tool_mode: chatRequest.toolMode || 'auto'
    })
    return response.data
  },

  async resolveApproval(
    approvalId: string,
    payload: {
      decision: ChatApprovalDecision
      sessionId: string
      invocationId?: string
      capabilityId?: string
      relativePath?: string
    }
  ) {
    // 过期/服务重启后失效属于审批终态，先交给业务层识别，避免全局拦截器弹“处理失败”。
    const response = await request.post(`/ai/chat/approvals/${encodeURIComponent(approvalId)}`, payload, {
      validateStatus: status => (status >= 200 && status < 300) || status === 404 || status === 409
    })
    const code = response.data?.detail?.code ?? response.data?.code
    if ((response.status === 404 && code === 'APPROVAL_NOT_FOUND')
        || (response.status === 409 && code === 'APPROVAL_EXPIRED')) {
      return {approvalId, status:'expired', decision:payload.decision}
    }
    const original = response.data?.detail?.approval
    if (response.status === 409 && code === 'APPROVAL_REPLAYED'
        && original?.approvalId === approvalId && original.sessionId === payload.sessionId
        && (payload.invocationId === undefined || original.invocationId === payload.invocationId)
        && (payload.capabilityId === undefined || original.capabilityId === payload.capabilityId)
        && (payload.relativePath === undefined || original.relativePath === payload.relativePath)
        && ['approved', 'denied', 'expired'].includes(original.status)) {
      // Reconcile an already-settled card with the original authority receipt.
      // This request's decision was not executed and must not replace that fact.
      return {approvalId, status:original.status as string}
    }
    if (response.status >= 400) {
      throw new AxiosError(response.data?.detail?.message || response.data?.message || '审批请求处理失败',
        code || 'APPROVAL_REQUEST_FAILED', response.config, response.request, response)
    }
    return response.data as { approvalId: string; status: string; decision: ChatApprovalDecision }
  },

  async cancelExecution(requestId: string) {
    const response = await request.post('/ai/chat/text/cancel', { requestId })
    return response.data as { requestId: string; cancelled: boolean }
  },

  // 获取对话历史
  async getHistory(contextId: string) {
    const response = await request.get(`/chat/history/${contextId}`)
    return response.data
  },

  // 清除对话历史
  async clearHistory(contextId: string) {
    await request.delete(`/chat/history/${contextId}`)
  }
}

