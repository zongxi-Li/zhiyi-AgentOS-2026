import { renderMarkdown } from '@/utils/markdown'

/** Copilot uses the shared Markdown structure; emphasis belongs to the author. */
export function renderCopilotMarkdown(source: string): string {
  return renderMarkdown(source)
}
