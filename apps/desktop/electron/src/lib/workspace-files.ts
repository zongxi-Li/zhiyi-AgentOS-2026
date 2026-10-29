/** Human-operated editor files. This is not an Agent execution backend. */
import { createHash, randomUUID } from 'node:crypto'
import { promises as fs } from 'node:fs'
import * as path from 'node:path'

const MAX_TEXT_BYTES = 16 * 1024 * 1024
export class WorkspaceFiles {
  private roots = new Map<string, string>()
  private currentId: string | null = null
  private saves = new Map<string, Promise<unknown>>()
  private readonly settingsPath: string
  constructor(settingsPath: string) { this.settingsPath = settingsPath }

  async current() {
    if (!this.currentId) {
      try {
        const saved = JSON.parse(await fs.readFile(this.settingsPath, 'utf8'))
        if (Array.isArray(saved.roots)) {
          for (const entry of saved.roots) if (typeof entry.id === 'string' && typeof entry.root === 'string') this.roots.set(entry.id, entry.root)
          if (this.roots.has(saved.currentId)) this.currentId = saved.currentId
        }
      } catch { /* First use or unavailable previous folder: the picker remains available. */ }
    }
    return this.currentId ? { id: this.currentId, root: this.roots.get(this.currentId)! } : null
  }

  /** Only Main's successful native folder dialog may call this. */
  async select(directory: string) {
    const root = await fs.realpath(directory)
    if (!(await fs.stat(root)).isDirectory()) throw new Error('请选择文件夹')
    const id = [...this.roots].find(([, value]) => value === root)?.[0] || randomUUID()
    this.roots.set(id, root); this.currentId = id
    await fs.writeFile(this.settingsPath, JSON.stringify({ currentId: id, roots: [...this.roots].map(([id, root]) => ({ id, root })) }), 'utf8')
    return { id, root }
  }

  private async resolve(id: unknown, relative: unknown) {
    await this.current()
    if (typeof id !== 'string' || !this.roots.has(id) || typeof relative !== 'string' || relative.includes('\0') || path.isAbsolute(relative)) throw new Error('请先打开文件夹')
    const root = await fs.realpath(this.roots.get(id)!)
    const target = await fs.realpath(path.resolve(root, relative))
    const offset = path.relative(root, target)
    if (offset === '..' || offset.startsWith('..' + path.sep) || path.isAbsolute(offset)) throw new Error('文件位于所选文件夹之外，请直接打开其所在文件夹')
    return { root, target }
  }

  async list(id: unknown, relative: unknown) {
    const {root, target} = await this.resolve(id, relative)
    const entries = await fs.readdir(target, {withFileTypes: true})
    return { workspaceRoot: root, path: relative as string, entries: entries.filter(entry => entry.isFile() || entry.isDirectory()).map(entry => ({
      name: entry.name, path: path.relative(root, path.join(target, entry.name)).split(path.sep).join('/'), type: entry.isDirectory() ? 'directory' as const : 'file' as const
    })) }
  }

  private async snapshot(target: string) {
    const stat = await fs.stat(target)
    if (!stat.isFile()) throw new Error('所选路径不是文件')
    if (stat.size > MAX_TEXT_BYTES) throw new Error('文本编辑器支持最大 16 MiB 文件')
    const bytes = await fs.readFile(target)
    if (bytes.length > MAX_TEXT_BYTES) throw new Error('文件过大')
    if (bytes.includes(0)) throw new Error('二进制文件暂不支持文本编辑')
    let content: string
    try { content = new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(bytes) }
    catch { throw new Error('当前支持 UTF-8 文本文件') }
    return { content, version: createHash('sha256').update(bytes).digest('hex') }
  }

  async read(id: unknown, relative: unknown) {
    const {root, target} = await this.resolve(id, relative)
    return {workspaceRoot: root, path: relative as string, ...await this.snapshot(target)}
  }

  async save(id: unknown, relative: unknown, content: unknown, expectedVersion: unknown) {
    if (typeof content !== 'string' || content.includes('\0') || Buffer.byteLength(content, 'utf8') > MAX_TEXT_BYTES || typeof expectedVersion !== 'string') throw new Error('无效的文本保存请求')
    const {target} = await this.resolve(id, relative)
    const previous = this.saves.get(target) || Promise.resolve()
    const pending = previous.catch(() => undefined).then(async () => {
      if ((await this.snapshot(target)).version !== expectedVersion) throw new Error('FILE_CONFLICT: 磁盘文件已变化，请重新读取后合并')
      const temporary = path.join(path.dirname(target), `.zhiyi-save-${randomUUID()}.tmp`)
      try {
        await fs.writeFile(temporary, content, {encoding: 'utf8', flag: 'wx'})
        if ((await this.snapshot(target)).version !== expectedVersion) throw new Error('FILE_CONFLICT: 磁盘文件已变化')
        await fs.rename(temporary, target)
      } finally { await fs.unlink(temporary).catch(() => undefined) }
      return {path: relative as string, version: createHash('sha256').update(content, 'utf8').digest('hex')}
    })
    this.saves.set(target, pending)
    try { return await pending }
    finally { if (this.saves.get(target) === pending) this.saves.delete(target) }
  }
}
