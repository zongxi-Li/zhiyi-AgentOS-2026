/** 写系统剪贴板：优先 Async Clipboard API，受限环境（桌面权限策略/非安全上下文）降级 execCommand。 */
export async function copyTextToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // 权限被拒或文档失焦时走降级路径，不让按钮变成「假成功」。
    }
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    if (!document.execCommand('copy')) throw new Error('execCommand copy returned false')
  } finally {
    textarea.remove()
  }
}
