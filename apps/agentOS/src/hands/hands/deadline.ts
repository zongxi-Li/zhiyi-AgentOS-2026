/** An absent deadline arms no timer. Long explicit deadlines cannot overflow Node timers. */
export function armDeadline(milliseconds: number | undefined, expire: () => void): () => void {
  if (milliseconds === undefined) return () => {}
  if (!Number.isFinite(milliseconds) || milliseconds <= 0) throw new RangeError('Invalid command deadline')
  const end = performance.now() + milliseconds
  let timer: ReturnType<typeof setTimeout> | undefined
  let cancelled = false
  const tick = () => {
    if (cancelled) return
    const left = end - performance.now()
    if (left <= 0) expire()
    else timer = setTimeout(tick, Math.min(left, 2_147_483_647))
  }
  tick()
  return () => { cancelled = true; clearTimeout(timer) }
}
