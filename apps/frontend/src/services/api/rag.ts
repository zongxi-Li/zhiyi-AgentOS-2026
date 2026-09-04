import request from '@/utils/request'

export interface RagQuery {
  query: string
  top_k?: number
  context_id?: string
}

export interface RagResponse {
  answer: string
  sources: Array<{
    title?: string
    url?: string
    content?: string
  }>
  confidence: number
}

export const ragApi = {
  // RAG查询
  async query(query: string, topK: number = 5, contextId?: string, roleId?: string): Promise<RagResponse> {
    const response = await request.post<RagResponse>('/rag/query', {
      query,
      top_k: topK,
      context_id: contextId,
      role_id: roleId
    })
    return response.data
  },

  // 上传文档
  async uploadDocument(file: File, roleId?: string): Promise<{ document_id: string }> {
    const formData = new FormData()
    formData.append('file', file)
    if (roleId) {
      formData.append('role_id', roleId)
    }
    
    const response = await request.post<{ document_id: string }>('/rag/documents', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
    return response.data
  },

  // 获取文档列表
  async listDocuments(roleId?: string): Promise<{ documents: Array<{ doc_id: string; filename: string; upload_time: string; role_id?: string; metadata: any }>; count: number }> {
    const params = roleId ? { role_id: roleId } : {}
    const response = await request.get('/rag/documents', { params })
    return response.data
  },

  // 删除文档
  async deleteDocument(docId: string): Promise<{ message: string; doc_id: string }> {
    const response = await request.delete(`/rag/documents/${docId}`)
    return response.data
  }
}

