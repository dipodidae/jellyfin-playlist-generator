import { computed, ref } from 'vue'
import type { GeneratedPlaylist, ProgressEvent } from '~/types/playlist'

const STEPS = [
  'Parsing prompt...',
  'Generating trajectory',
  'Gathering candidates...',
  'Matching tracks',
  'Composing playlist...',
  'Saving playlist...',
]

const STAGE_INDEX: Record<string, number> = {
  parsing: 0,
  trajectory: 1,
  candidates: 2,
  matching: 3,
  composing: 4,
  saving: 5,
  complete: 6,
  error: -1,
}

function defaultProgressSteps() {
  return STEPS.map(message => ({ message, done: false }))
}

export function usePlaylistGeneration() {
  const prompt = ref('')
  const playlistSize = ref(30)
  const isGenerating = ref(false)
  const progress = ref(0)
  const progressMessage = ref('')
  const progressSteps = ref(defaultProgressSteps())
  const result = ref<GeneratedPlaylist | null>(null)
  const error = ref<string | null>(null)

  const canGenerate = computed(() => !!prompt.value.trim())
  const activeStepIndex = computed(() =>
    progressSteps.value.findIndex(s => !s.done),
  )

  function handleProgressEvent(event: ProgressEvent) {
    progress.value = event.progress
    progressMessage.value = event.message

    const stageIndex = STAGE_INDEX[event.stage] ?? -1

    if (stageIndex >= 0) {
      for (let i = 0; i < stageIndex; i++) {
        progressSteps.value[i].done = true
      }
    }

    if (event.stage === 'complete' && event.playlist) {
      result.value = event.playlist
      progressSteps.value.forEach(s => (s.done = true))
    }

    if (event.stage === 'error') {
      error.value = event.error ?? 'Generation failed'
    }
  }

  async function generatePlaylist() {
    if (!canGenerate.value || isGenerating.value) return

    isGenerating.value = true
    progress.value = 0
    progressMessage.value = 'Starting...'
    progressSteps.value = defaultProgressSteps()
    result.value = null
    error.value = null

    try {
      const response = await fetch('/api/generate-playlist/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: prompt.value, size: playlistSize.value }),
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data: ProgressEvent = JSON.parse(line.slice(6))
            handleProgressEvent(data)
          }
        }
      }
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : 'Unknown error'
    }
    finally {
      isGenerating.value = false
    }
  }

  function reset() {
    result.value = null
    error.value = null
    prompt.value = ''
    progress.value = 0
    progressMessage.value = ''
    progressSteps.value = defaultProgressSteps()
  }

  return {
    prompt,
    playlistSize,
    isGenerating,
    progress,
    progressMessage,
    progressSteps,
    result,
    error,
    canGenerate,
    activeStepIndex,
    generatePlaylist,
    reset,
  }
}
