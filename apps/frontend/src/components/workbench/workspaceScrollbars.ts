/** One capture listener handles nested scroll surfaces, including Dockview renderers. */
export function createWorkspaceScrollbars() {
  const pending = new Map<HTMLElement, ReturnType<typeof setTimeout>>()
  const owners = new Set<HTMLElement>()
  const onScroll = (event: Event) => {
    if (!(event.target instanceof HTMLElement)) return
    const element = event.target
    owners.add(element)
    element.classList.add('workspace-scroll-owner', 'workspace-scroll-active')
    clearTimeout(pending.get(element))
    pending.set(element, setTimeout(() => {
      element.classList.remove('workspace-scroll-active')
      pending.delete(element)
      owners.delete(element)
    }, 900))
  }
  const clear = () => {
    for (const timer of pending.values()) clearTimeout(timer)
    pending.clear()
    for (const element of owners) element.classList.remove('workspace-scroll-owner', 'workspace-scroll-active')
    owners.clear()
  }
  return { onScroll, clear }
}
