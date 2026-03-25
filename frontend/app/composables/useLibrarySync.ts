import { computed, onBeforeUnmount, ref } from 'vue'
import type { ScanEvent, ScanStats, ScanStatus } from '~/types/library'
import { useStageLabel } from '~/composables/useStageLabel'

const { stageLabel } = useStageLabel()

function emptyScanStats(): ScanStats {
  return {
    files_found: 0,
    files_scanned: 0,
    files_skipped: 0,
    tracks_added: 0,
    tracks_updated: 0,
    files_missing: 0,
    errors: 0,
  }
}

export function useLibrarySync(options?: { onCompleted?: () => void }) {
  const isSyncing = ref(false)
  const syncError = ref<string | null>(null)
  const syncStatus = ref<ScanStatus | null>(null)
  const syncActivity = ref<ScanEvent[]>([])
  const recentScanJobs = ref<ScanStatus[]>([])
  const lastSyncTime = ref<Date | null>(null)

  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let clearStatusTimer: ReturnType<typeof setTimeout> | null = null

  const currentSyncStats = computed(() => syncStatus.value?.stats ?? emptyScanStats())
  const scanProgressValue = computed(() => syncStatus.value?.progress ?? 0)
  const scanMessage = computed(() => syncStatus.value?.message ?? '')
  const scanStageText = computed(() => stageLabel(syncStatus.value?.stage ?? 'idle'))
  const scanAttachmentText = computed(() => {
    if (!syncStatus.value) return ''
    return syncStatus.value.is_live ? 'Live updates' : 'Recovered snapshot'
  })
  const scanElapsedText = computed(() => {
    if (!syncStatus.value?.started_at) return ''
    const started = new Date(syncStatus.value.started_at).getTime()
    // Use completed_at if available, otherwise current time if still running
    const end = (syncStatus.value.completed_at && !syncStatus.value.is_running)
      ? new Date(syncStatus.value.completed_at).getTime()
      : Date.now()
    const seconds = Math.max(0, Math.floor((end - started) / 1000))
    const minutes = Math.floor(seconds / 60)
    const remainder = seconds % 60
    return `${minutes}:${remainder.toString().padStart(2, '0')}`
  })

  function addScanActivity(event: ScanEvent) {
    const nextEvent = {
      ...event,
      created_at: event.created_at ?? new Date().toISOString(),
    }
    const last = syncActivity.value[syncActivity.value.length - 1]
    if (
      last
      && last.stage === nextEvent.stage
      && last.message === nextEvent.message
      && last.current === nextEvent.current
      && last.total === nextEvent.total
    ) {
      return
    }
    syncActivity.value = [...syncActivity.value, nextEvent].slice(-12)
  }

  function applyScanStatus(status: ScanStatus, source: 'stream' | 'snapshot') {
    // When scan is complete, ensure completed_at and is_running are set correctly
    let finalStatus = { ...status }

    if (status.stage === 'complete' && !status.completed_at) {
      // If backend sent complete event but missing completed_at, use current time
      finalStatus.completed_at = new Date().toISOString()
    }

    if (status.stage === 'complete' || status.status === 'completed') {
      // Ensure is_running is false when scan is done
      finalStatus.is_running = false

      // Clear status after a delay so the progress bar disappears
      if (clearStatusTimer) {
        clearTimeout(clearStatusTimer)
      }
      clearStatusTimer = setTimeout(() => {
        if (!isSyncing.value) {
          syncStatus.value = null
        }
      }, 5000)
    }

    syncStatus.value = {
      ...finalStatus,
      stats: finalStatus.stats ?? emptyScanStats(),
      source,
      is_live: source === 'stream',
    }
    isSyncing.value = finalStatus.is_running
    syncError.value = finalStatus.error ?? null

    if (finalStatus.message) {
      addScanActivity({
        stage: finalStatus.stage,
        event_type: finalStatus.status,
        message: finalStatus.message,
        current: finalStatus.current,
        total: finalStatus.total,
        created_at: finalStatus.updated_at ?? finalStatus.started_at,
      })
    }

    if (!finalStatus.is_running && finalStatus.completed_at) {
      lastSyncTime.value = new Date(finalStatus.completed_at)
    }
  }

  function resetPollTimer() {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  function schedulePoll() {
    resetPollTimer()
    pollTimer = setTimeout(checkSyncStatus, 1000)
  }

  async function checkSyncStatus() {
    try {
      const response = await fetch('/api/scan/status')
      if (response.ok) {
        const status: ScanStatus = await response.json()
        if (status.is_running) {
          applyScanStatus(status, 'snapshot')
          schedulePoll()
        }
        else {
          isSyncing.value = false
          if (status.job_id) {
            applyScanStatus(status, 'snapshot')
          }
        }
      }
    }
    catch {
      // Silently fail
    }
  }

  async function fetchHistory() {
    try {
      const response = await fetch('/api/scan/jobs/history?limit=6')
      if (response.ok) {
        recentScanJobs.value = await response.json()
      }
    }
    catch {
      // Silently fail
    }
  }

  async function startScan(fullSync: boolean = false) {
    if (isSyncing.value) return

    isSyncing.value = true
    syncError.value = null
    syncActivity.value = []

    applyScanStatus({
      is_running: true,
      operation: 'scan',
      job_id: null,
      status: 'running',
      scan_type: fullSync ? 'full' : 'incremental',
      stage: 'starting',
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: null,
      current: 0,
      total: 0,
      progress: 0,
      message: fullSync ? 'Starting full scan...' : 'Starting incremental scan...',
      error: null,
      stats: emptyScanStats(),
      source: 'stream',
      is_live: true,
    }, 'stream')

    try {
      const response = await fetch(`/api/scan/stream?full=${fullSync}`, { method: 'POST' })

      if (response.status === 409) {
        const conflict = await response.json()
        if (conflict.detail) {
          applyScanStatus(conflict.detail, 'snapshot')
        }
        schedulePoll()
        return
      }

      if (!response.ok) {
        throw new Error(`Sync failed: ${response.statusText}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event: ScanStatus = JSON.parse(line.slice(6))
              applyScanStatus(event, 'stream')

              if (event.stage === 'complete') {
                options?.onCompleted?.()
                await fetchHistory()
              }
              if (event.stage === 'error') {
                syncError.value = event.error ?? 'Sync failed'
              }
            }
            catch {
              // Skip malformed SSE lines
            }
          }
        }
      }

      // Flush any remaining data left in the buffer after the stream closes
      if (buffer.trim()) {
        for (const line of buffer.split('\n\n')) {
          if (line.startsWith('data: ')) {
            try {
              const event: ScanStatus = JSON.parse(line.slice(6))
              applyScanStatus(event, 'stream')

              if (event.stage === 'complete') {
                options?.onCompleted?.()
                await fetchHistory()
              }
              if (event.stage === 'error') {
                syncError.value = event.error ?? 'Sync failed'
              }
            }
            catch {
              // Skip malformed SSE lines
            }
          }
        }
      }
    }
    catch (e) {
      syncError.value = e instanceof Error ? e.message : 'Sync failed'
    }
    finally {
      if (syncStatus.value?.is_running) {
        schedulePoll()
      }
      else {
        isSyncing.value = false
      }
    }
  }

  async function restoreStatus() {
    await checkSyncStatus()
  }

  onBeforeUnmount(() => {
    resetPollTimer()
    if (clearStatusTimer) {
      clearTimeout(clearStatusTimer)
    }
  })

  return {
    isSyncing,
    syncError,
    syncStatus,
    syncActivity,
    recentScanJobs,
    lastSyncTime,
    currentSyncStats,
    scanProgressValue,
    scanMessage,
    scanStageText,
    scanAttachmentText,
    scanElapsedText,
    startScan,
    restoreStatus,
    fetchHistory,
    stageLabel,
  }
}
