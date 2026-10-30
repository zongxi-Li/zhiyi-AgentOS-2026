import { ref } from 'vue'

// Panel visibility is UI state; the terminal service owns the live sessions.
export const terminalVisible = ref(false)
export const terminalActiveId = ref<string | null>(null)
export function toggleDesktopTerminal() { terminalVisible.value = !terminalVisible.value }
