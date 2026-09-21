// 任务标题的纯文本化：Objective 常带 Markdown（# 标题 / **强调** / 链接 / 行内代码），
// 标题存储与列表展示不做富文本渲染，只保留可读文字，避免工作台出现裸语法符号。
export const plainMissionTitle = (raw: string | undefined | null, fallback = '未命名工程'): string => {
  const text = String(raw || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!\[([^\]]*)]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)]\([^)]*\)/g, '$1')
    .replace(/^\s*#{1,6}\s+/gm, '')
    .replace(/(^|\s)#{1,6}(\s)/g, '$1$2')
    .replace(/[*_~]{1,3}([^*_~]+)[*_~]{1,3}/g, '$1')
    .replace(/^>\s?/gm, '')
    .replace(/\s+/g, ' ')
    .trim()
  return text || fallback
}
