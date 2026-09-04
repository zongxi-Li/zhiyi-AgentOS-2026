import request from '@/utils/request'

export interface VoiceChatRequest {
  audio: File
  roleId?: string
  contextId?: string
}

export interface VoiceChatResponse {
  text: string
  contextId: string
  confidence: number
  recognizedText?: string
}

export const voiceApi = {
  // 发送语音消息
  async sendVoiceMessage(voiceRequest: VoiceChatRequest): Promise<VoiceChatResponse> {
    const formData = new FormData()
    formData.append('audio', voiceRequest.audio)
    if (voiceRequest.roleId) {
      formData.append('roleId', voiceRequest.roleId)
    }
    if (voiceRequest.contextId) {
      formData.append('contextId', voiceRequest.contextId)
    }

    try {
      // 使用/ai前缀，通过Java后端代理到Python服务
      const response = await request.post<VoiceChatResponse>('/ai/voice/chat', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      })
      return response.data
    } catch (error: any) {
      console.error('语音消息发送失败:', error)
      throw error
    }
  },

  // 文本转语音
  async textToSpeech(
    text: string, 
    voice: string = 'default', 
    speed: number = 1.0, 
    pitch: number = 1.0
  ): Promise<Blob> {
    try {
      console.log('调用TTS API:', { text: text.substring(0, 50), voice, speed, pitch })
      
      // 使用/ai前缀，通过Java后端代理到Python服务
      const response = await request.post(
        '/ai/voice/tts',
        {
          text,
          voice,
          speed,
          pitch
        },
        {
          responseType: 'blob'
        }
      )
      
      console.log('TTS响应:', {
        status: response.status,
        size: response.data?.size,
        type: response.data?.type
      })
      
      // 检查返回的数据
      if (!response.data || response.data.size === 0) {
        throw new Error('TTS返回的音频数据为空')
      }
      
      return response.data
    } catch (error: any) {
      console.error('TTS请求失败:', error)
      console.error('错误详情:', {
        message: error.message,
        response: error.response?.data,
        status: error.response?.status
      })
      throw error
    }
  }
}

