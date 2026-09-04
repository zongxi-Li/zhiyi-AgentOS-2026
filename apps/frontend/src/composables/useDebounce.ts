import { ref, watch, type Ref } from 'vue'

/**
 * 防抖Hook
 */
export function useDebounce<T>(value: Ref<T>, delay: number = 300) {
  const debouncedValue = ref(value.value) as Ref<T>

  let timeoutId: ReturnType<typeof setTimeout>

  watch(value, (newValue) => {
    clearTimeout(timeoutId)
    timeoutId = setTimeout(() => {
      debouncedValue.value = newValue
    }, delay)
  })

  return debouncedValue
}

