/**
 * 性能监控工具
 */

export interface PerformanceMetric {
  name: string
  duration: number
  timestamp: number
}

class PerformanceMonitor {
  private metrics: PerformanceMetric[] = []

  /**
   * 记录性能指标
   */
  record(name: string, duration: number) {
    this.metrics.push({
      name,
      duration,
      timestamp: Date.now()
    })

    // 只保留最近100条记录
    if (this.metrics.length > 100) {
      this.metrics.shift()
    }
  }

  /**
   * 获取性能指标
   */
  getMetrics(): PerformanceMetric[] {
    return [...this.metrics]
  }

  /**
   * 清除指标
   */
  clear() {
    this.metrics = []
  }

  /**
   * 获取平均响应时间
   */
  getAverageDuration(name?: string): number {
    const filtered = name
      ? this.metrics.filter(m => m.name === name)
      : this.metrics

    if (filtered.length === 0) return 0

    const sum = filtered.reduce((acc, m) => acc + m.duration, 0)
    return sum / filtered.length
  }
}

export const performanceMonitor = new PerformanceMonitor()

/**
 * 性能装饰器
 */
export function measurePerformance(name: string) {
  return function (target: any, propertyKey: string, descriptor: PropertyDescriptor) {
    const originalMethod = descriptor.value

    descriptor.value = async function (...args: any[]) {
      const start = performance.now()
      try {
        const result = await originalMethod.apply(this, args)
        const duration = performance.now() - start
        performanceMonitor.record(name, duration)
        return result
      } catch (error) {
        const duration = performance.now() - start
        performanceMonitor.record(`${name}_error`, duration)
        throw error
      }
    }

    return descriptor
  }
}

