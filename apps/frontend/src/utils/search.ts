/**
 * 搜索工具函数
 */

export interface SearchableItem {
  content: string
  [key: string]: any
}

/**
 * 在消息列表中搜索
 */
export function searchMessages(
  messages: SearchableItem[],
  keyword: string
): SearchableItem[] {
  if (!keyword || keyword.trim() === '') {
    return messages
  }

  const lowerKeyword = keyword.toLowerCase()
  return messages.filter(msg => {
    const content = msg.content || ''
    return content.toLowerCase().includes(lowerKeyword)
  })
}

/**
 * 高亮搜索关键词
 */
export function highlightKeyword(text: string, keyword: string): string {
  if (!keyword || keyword.trim() === '') {
    return text
  }

  const regex = new RegExp(`(${keyword})`, 'gi')
  return text.replace(regex, '<mark>$1</mark>')
}

/**
 * 搜索对话历史
 */
export function searchConversations(
  conversations: any[],
  keyword: string
): any[] {
  if (!keyword || keyword.trim() === '') {
    return conversations
  }

  const lowerKeyword = keyword.toLowerCase()
  return conversations.filter(conv => {
    return (
      conv.contextId?.toLowerCase().includes(lowerKeyword) ||
      conv.createdAt?.toLowerCase().includes(lowerKeyword)
    )
  })
}

