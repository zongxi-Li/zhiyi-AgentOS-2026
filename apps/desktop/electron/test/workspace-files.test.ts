import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import * as path from 'node:path'
import { WorkspaceFiles } from '../src/lib/workspace-files.ts'

test('native editor: selected folders, hidden entries, conditional save, restore and rejected conflict', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'zhiyi-editor-'))
  assert.ok(path.resolve(root).startsWith(path.join(tmpdir(), 'zhiyi-editor-')))
  try {
    const folder = path.join(root, '用户项目')
    await mkdir(folder); await mkdir(path.join(folder, '.git'))
    await writeFile(path.join(folder, 'note.md'), '原始\r\ntext')
    await writeFile(path.join(folder, 'binary.bin'), Buffer.from([0, 1]))
    await writeFile(path.join(root, 'outside.txt'), 'sentinel')
    const settings = path.join(root, 'folders.json')
    const files = new WorkspaceFiles(settings)
    const selected = await files.select(folder)
    const listing = await files.list(selected.id, '.')
    assert.ok(listing.entries.some(entry => entry.name === '.git'))
    const original = await files.read(selected.id, 'note.md')
    assert.equal(original.content, '原始\r\ntext')
    await files.save(selected.id, 'note.md', '真实保存\r\n完成', original.version)
    assert.equal(await readFile(path.join(folder, 'note.md'), 'utf8'), '真实保存\r\n完成')
    await assert.rejects(files.save(selected.id, 'note.md', 'stale overwrite', original.version), /FILE_CONFLICT/)
    await assert.rejects(files.read(selected.id, '../outside.txt'))
    await assert.rejects(files.read('unselected', 'note.md'))
    await assert.rejects(files.read(selected.id, 'binary.bin'), /二进制/)
    const observed = await files.read(selected.id, 'note.md')
    const competing = await Promise.allSettled([
      files.save(selected.id, 'note.md', 'first writer', observed.version),
      files.save(selected.id, 'note.md', 'second writer', observed.version)
    ])
    assert.equal(competing.filter(result => result.status === 'fulfilled').length, 1)
    assert.equal(competing.filter(result => result.status === 'rejected').length, 1)
    assert.deepEqual(await new WorkspaceFiles(settings).current(), selected)
    assert.equal(await readFile(path.join(root, 'outside.txt'), 'utf8'), 'sentinel')
  } finally { await rm(root, {recursive: true, force: true}) }
})
