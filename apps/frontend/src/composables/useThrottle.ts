import { ref, watch, type Ref } from 'vue'

/**
 * 节流Hook
 */
export function useThrottle<T>(value: Ref<T>, delay: number = 300) {
  const throttledValue = ref(value.value) as Ref<T>

  let lastTime = 0

  watch(value, (newValue) => {
    const now = Date.now()
    if (now - lastTime >= delay) {
      throttledValue.value = newValue
      lastTime = now
    }
  })

  return throttledValue
}

