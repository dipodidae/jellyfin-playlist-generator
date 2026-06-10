import { ref } from 'vue'

export interface FixStats {
  eligible: number
  matched: number
  updated: number
  skipped_no_jellyfin_match: number
  failed: number
  errors: string[]
}

export function useJellyfinTools() {
  const running = ref(false)
  const progress = ref(0)
  const message = ref('')
  const stats = ref<FixStats | null>(null)
  const error = ref<string | null>(null)

  async function fixReleaseDates() {
    running.value = true
    progress.value = 0
    stats.value = null
    error.value = null
    try {
      const res = await fetch('/api/jellyfin/fix-release-dates', { method: 'POST' })
      if (!res.body) throw new Error('No response stream')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() ?? ''
        for (const part of parts) {
          const line = part.split('\n').find(l => l.startsWith('data: '))
          if (!line) continue
          const evt = JSON.parse(line.slice(6))
          progress.value = evt.progress ?? progress.value
          message.value = evt.message ?? message.value
          if (evt.error) error.value = evt.error
          if (evt.stats) stats.value = evt.stats
        }
      }
    }
    catch (e) {
      error.value = String(e)
    }
    finally {
      running.value = false
    }
  }

  return { running, progress, message, stats, error, fixReleaseDates }
}
