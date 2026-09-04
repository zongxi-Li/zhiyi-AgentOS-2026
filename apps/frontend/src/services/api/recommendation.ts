import request from '@/utils/request'

export interface RecommendationItem {
  text: string
  reason: string
  targetAction: 'fill_input' | 'fill_query'
  confidence: number
  scope: 'chat' | 'rag' | 'workbench' | string
}

export interface RecommendationContextRequest {
  roleName?: string
  scope?: 'chat' | 'rag' | 'workbench' | string
  scene?: string
  currentInput?: string
  currentOutput?: string
  conversationHistory?: string[]
}

export const recommendationApi = {
  async getRecommendations(
    conversationHistory: string[] = [],
    roleName?: string
  ): Promise<string[]> {
    const params: Record<string, string> = {}
    if (roleName) {
      params.roleName = roleName
    }
    const response = await request.post<string[]>(
      '/recommendations/questions',
      conversationHistory,
      { params }
    )
    return response.data
  },

  async getContextualRecommendations(
    payload: RecommendationContextRequest
  ): Promise<RecommendationItem[]> {
    const response = await request.post<RecommendationItem[]>(
      '/recommendations/contextual',
      payload
    )
    return response.data || []
  }
}
