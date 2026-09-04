/**
 * 全局错误处理工具
 */
export class ErrorHandler {
  /**
   * 显示全局错误
   */
  static showGlobalError(message: string, duration: number = 5000) {
    const event = new CustomEvent('global-error', {
      detail: { message, duration }
    })
    window.dispatchEvent(event)
  }

  /**
   * 清除全局错误
   */
  static clearGlobalError() {
    const event = new CustomEvent('global-error', {
      detail: { message: '', clear: true }
    })
    window.dispatchEvent(event)
  }

  /**
   * 处理API错误
   */
  static handleApiError(error: any, defaultMessage: string = '操作失败') {
    let errorMessage = defaultMessage

    if (error.response) {
      // 服务器返回了错误响应
      const data = error.response.data
      if (data) {
        errorMessage = data.message || data.error || data.msg || errorMessage
      } else {
        errorMessage = `服务器错误: ${error.response.status}`
      }
    } else if (error.request) {
      // 请求已发出但没有收到响应
      errorMessage = '无法连接到服务器，请检查网络连接'
    } else {
      // 其他错误
      errorMessage = error.message || errorMessage
    }

    // 如果是500错误，显示全局错误提示
    if (error.response?.status === 500) {
      this.showGlobalError(errorMessage)
    }

    return errorMessage
  }
}

