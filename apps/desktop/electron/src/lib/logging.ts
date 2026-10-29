import { appendFileSync, existsSync, renameSync, statSync, unlinkSync, mkdirSync } from 'node:fs'
import * as path from 'node:path'

export type LogLevel = 'info' | 'warn' | 'error'

export interface FileLogger {
  info(message: string, extra?: Record<string, unknown>): void
  warn(message: string, extra?: Record<string, unknown>): void
  error(message: string, extra?: Record<string, unknown>): void
  filePath: string
}

const MAX_LOG_BYTES = 5 * 1024 * 1024

/**
 * 主进程文件日志：userData/logs/<name>，超过 5MB 轮转保留一份 .1。
 * 同步追加（日志量低），任何 IO 异常吞掉——日志失败不允许拖垮宿主。
 */
export function createFileLogger(directory: string, fileName = 'main.log'): FileLogger {
  mkdirSync(directory, { recursive: true })
  const filePath = path.join(directory, fileName)
  const rotatedPath = `${filePath}.1`

  const rotateIfNeeded = (): void => {
    try {
      if (existsSync(filePath) && statSync(filePath).size > MAX_LOG_BYTES) {
        unlinkSync(rotatedPath)
        renameSync(filePath, rotatedPath)
      }
    } catch {
      // 轮转失败只影响日志体积，不影响功能。
    }
  }

  const write = (level: LogLevel, message: string, extra?: Record<string, unknown>): void => {
    const timestamp = new Date().toISOString()
    let line = `${timestamp} [${level}] ${message}`
    if (extra !== undefined) {
      try {
        line += ` ${JSON.stringify(extra)}`
      } catch {
        line += ' {"extra":"unserializable"}'
      }
    }
    try {
      rotateIfNeeded()
      appendFileSync(filePath, `${line}\n`, 'utf8')
    } catch {
      // 磁盘不可写等场景静默放弃。
    }
  }

  return {
    info: (message, extra) => write('info', message, extra),
    warn: (message, extra) => write('warn', message, extra),
    error: (message, extra) => write('error', message, extra),
    filePath
  }
}
