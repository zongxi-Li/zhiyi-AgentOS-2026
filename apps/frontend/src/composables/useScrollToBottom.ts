import { nextTick, Ref } from 'vue'

/**
 * 滚动到底部Hook
 */
export function useScrollToBottom(containerRef: Ref<HTMLElement | undefined>) {
  const scrollToBottom = async () => {
    await nextTick()
    if (containerRef.value) {
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  }

  const scrollToTop = async () => {
    await nextTick()
    if (containerRef.value) {
      containerRef.value.scrollTop = 0
    }
  }

  return {
    scrollToBottom,
    scrollToTop
  }
}

