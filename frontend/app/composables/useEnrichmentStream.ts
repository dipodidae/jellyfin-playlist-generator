import { ref } from 'vue'

export interface EnrichmentProgress {
  progress?: number
  message?: string
  current: number
  total: number
  done?: boolean
  error?: string
  stats?: Record<string, unknown>
}

export function useEnrichmentStream(options?: { onCompleted?: () => void }) {
  const isRunning = ref(false)
  const progress = ref(0)
  const message = ref('')
  const error = ref<string | null>(null)
  const lastStats = ref<Record<string, unknown> | null>(null)
  const status = ref<'idle' | 'running' | 'success' | 'error'>('idle')
  const lastFinishedMessage = ref('')
  const operationLabel = ref('Operation')

  let abortController: AbortController | null = null

  async function run(endpoint: string, label: string = 'Operation'): Promise<void> {
    if (isRunning.value) return

    isRunning.value = true
    progress.value = 0
    message.value = ''
    error.value = null
    lastStats.value = null
    status.value = 'running'
    lastFinishedMessage.value = ''
    operationLabel.value = label

    abortController = new AbortController()
    let sawTerminalEvent = false

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        signal: abortController.signal,
      })

      if (!response.ok || !response.body) {
        const responseText = await response.text().catch(() => '')
        error.value = responseText || `Request failed: ${response.status}`
        status.value = 'error'
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event: EnrichmentProgress = JSON.parse(line.slice(6))
            progress.value = event.progress ?? 0
            message.value = event.message ?? ''
            if (event.error) {
              error.value = event.error
              status.value = 'error'
            }
            if (event.stats) {
              lastStats.value = event.stats
            }
            if (event.done) {
              sawTerminalEvent = true
              if (!event.error) {
                status.value = 'success'
                lastFinishedMessage.value = event.message ?? `${label} complete`
                options?.onCompleted?.()
              }
              break
            }
          }
          catch {
            // Ignore malformed SSE lines
          }
        }
      }
    }
    catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') {
        error.value = err.message
        status.value = 'error'
      }
      else if (err instanceof Error && err.name === 'AbortError') {
        error.value = `${label} was canceled before it finished.`
        status.value = 'error'
      }
    }
    finally {
      if (!sawTerminalEvent && !error.value) {
        error.value = `${label} ended unexpectedly before reporting completion.`
        status.value = 'error'
      }
      isRunning.value = false
      abortController = null
    }
  }

  function cancel() {
    abortController?.abort()
  }

  return {
    isRunning,
    progress,
    message,
    error,
    lastStats,
    status,
    lastFinishedMessage,
    operationLabel,
    run,
    cancel,
  }
}
