<script setup lang="ts">
interface ProgressEvent {
  stage: 'parsing' | 'trajectory' | 'candidates' | 'matching' | 'composing' | 'jellyfin' | 'complete' | 'error'
  progress: number
  message: string
  phase?: string
  playlist?: GeneratedPlaylist
  jellyfin_id?: string
  error?: string
}

interface Track {
  id: string
  title: string
  artist_name: string
  album_name: string
  year: number
  duration_ms: number
}

interface GeneratedPlaylist {
  prompt: string
  title: string
  playlist_size: number
  tracks: Track[]
  jellyfin_playlist_id: string
  partial?: boolean
  warning?: string
}

interface LibraryStats {
  tracks: number
  artists: number
  albums: number
  genres: number
  lastfm_tags: number
  playlists: number
  artists_with_tags?: number
  artist_similarities?: number
  tracks_with_tags?: number
  tracks_with_embeddings?: number
}

const prompt = ref('')
const playlistSize = ref(30)
const isGenerating = ref(false)
const progress = ref(0)
const progressMessage = ref('')
const progressSteps = ref<{ message: string; done: boolean }[]>([])
const result = ref<GeneratedPlaylist | null>(null)
const error = ref<string | null>(null)

const stats = ref<LibraryStats | null>(null)
const isSyncing = ref(false)
const syncError = ref<string | null>(null)
const syncProgress = ref(0)
const syncMessage = ref('')
const syncCurrent = ref(0)
const syncTotal = ref(0)
const lastSyncTime = ref<Date | null>(null)
const showSettings = ref(false)
const syncingLastfm = ref(false)
const syncingEmbeddings = ref(false)

async function fetchStats() {
  try {
    const response = await fetch('/api/stats')
    if (response.ok) {
      stats.value = await response.json()
    }
  }
  catch {
    // Silently fail - stats are optional
  }
}

async function checkSyncStatus() {
  try {
    const response = await fetch('/api/sync/status')
    if (response.ok) {
      const status = await response.json()
      if (status.is_syncing) {
        isSyncing.value = true
        syncProgress.value = status.total > 0 ? Math.round((status.current / status.total) * 100) : 0
        syncMessage.value = status.message || 'Sync in progress...'
        syncCurrent.value = status.current || 0
        syncTotal.value = status.total || 0
        // Poll for updates while syncing
        setTimeout(checkSyncStatus, 1000)
      } else {
        isSyncing.value = false
      }
    }
  }
  catch {
    // Silently fail
  }
}

async function syncLibrary(fullSync: boolean = false) {
  if (isSyncing.value) return

  isSyncing.value = true
  syncError.value = null
  syncProgress.value = 0
  syncMessage.value = fullSync ? 'Starting full sync...' : 'Checking for new tracks...'
  syncCurrent.value = 0
  syncTotal.value = 0

  try {
    const response = await fetch(`/api/sync/jellyfin/stream?full=${fullSync}`, { method: 'POST' })
    
    // Handle 409 Conflict - sync already in progress
    if (response.status === 409) {
      const error = await response.json()
      syncMessage.value = error.detail?.message || 'Sync already in progress'
      syncCurrent.value = error.detail?.current || 0
      syncTotal.value = error.detail?.total || 0
      if (syncTotal.value > 0) {
        syncProgress.value = Math.round((syncCurrent.value / syncTotal.value) * 100)
      }
      // Start polling for status updates
      setTimeout(checkSyncStatus, 1000)
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
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const event = JSON.parse(line.slice(6))
            syncProgress.value = event.progress || 0
            syncMessage.value = event.message || ''
            if (event.current) syncCurrent.value = event.current
            if (event.total) syncTotal.value = event.total

            if (event.stage === 'complete') {
              lastSyncTime.value = new Date()
              await fetchStats()
            }
            if (event.stage === 'error') {
              syncError.value = event.error || 'Sync failed'
            }
          }
          catch {
            // Ignore parse errors
          }
        }
      }
    }
  }
  catch (e) {
    syncError.value = e instanceof Error ? e.message : 'Sync failed'
  }
  finally {
    isSyncing.value = false
  }
}

async function syncLastfm() {
  if (syncingLastfm.value) return
  syncingLastfm.value = true
  try {
    await fetch('/api/sync/lastfm/artists', { method: 'POST' })
    // Poll for updates
    setTimeout(fetchStats, 5000)
  } finally {
    syncingLastfm.value = false
  }
}

async function syncEmbeddings() {
  if (syncingEmbeddings.value) return
  syncingEmbeddings.value = true
  try {
    await fetch('/api/sync/embeddings', { method: 'POST' })
    // Poll for updates
    setTimeout(fetchStats, 5000)
  } finally {
    syncingEmbeddings.value = false
  }
}

onMounted(() => {
  fetchStats()
  checkSyncStatus()
})

const steps = [
  'Parsing prompt...',
  'Generating trajectory',
  'Gathering candidates...',
  'Matching tracks',
  'Composing playlist...',
  'Creating Jellyfin playlist...',
]

async function generatePlaylist() {
  if (!prompt.value.trim() || isGenerating.value) return

  isGenerating.value = true
  progress.value = 0
  progressMessage.value = 'Starting...'
  progressSteps.value = steps.map(s => ({ message: s, done: false }))
  result.value = null
  error.value = null

  try {
    const response = await fetch('/api/generate-playlist/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: prompt.value,
        size: playlistSize.value,
      }),
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
      buffer = lines.pop() || ''

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

function handleProgressEvent(event: ProgressEvent) {
  progress.value = event.progress
  progressMessage.value = event.message

  const stageIndex = {
    parsing: 0,
    trajectory: 1,
    candidates: 2,
    matching: 3,
    composing: 4,
    jellyfin: 5,
    complete: 6,
    error: -1,
  }[event.stage]

  if (stageIndex >= 0) {
    for (let i = 0; i < stageIndex; i++) {
      progressSteps.value[i].done = true
    }
  }

  if (event.stage === 'complete' && event.playlist) {
    result.value = event.playlist
    progressSteps.value.forEach(s => s.done = true)
  }

  if (event.stage === 'error') {
    error.value = event.error || 'Generation failed'
  }
}

function formatDuration(ms: number): string {
  const minutes = Math.floor(ms / 60000)
  const seconds = Math.floor((ms % 60000) / 1000)
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}
</script>

<template>
  <div class="space-y-8">
    <!-- Library Status Bar -->
    <div class="p-4 bg-gray-100 dark:bg-gray-900 rounded-lg space-y-3">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-4">
          <div v-if="stats" class="text-sm text-gray-600 dark:text-gray-400">
            <span class="font-medium text-gray-900 dark:text-white">{{ stats.tracks.toLocaleString() }}</span> tracks
            ·
            <span class="font-medium text-gray-900 dark:text-white">{{ stats.artists.toLocaleString() }}</span> artists
            ·
            <span class="font-medium text-gray-900 dark:text-white">{{ stats.tracks_with_embeddings?.toLocaleString() || 0 }}</span> embedded
          </div>
          <div v-else class="text-sm text-gray-500">
            No library synced
          </div>
        </div>
        <div class="flex items-center gap-2">
          <span v-if="lastSyncTime && !isSyncing" class="text-xs text-gray-400">
            Last sync: {{ lastSyncTime.toLocaleTimeString() }}
          </span>
          <UButton
            variant="ghost"
            size="sm"
            icon="i-heroicons-cog-6-tooth"
            @click="showSettings = !showSettings"
          />
          <UButton
            :loading="isSyncing"
            :disabled="isSyncing"
            variant="soft"
            size="sm"
            icon="i-heroicons-arrow-path"
            @click="syncLibrary(false)"
          >
            {{ isSyncing ? 'Syncing...' : 'Sync Library' }}
          </UButton>
        </div>
      </div>

      <!-- Sync Progress -->
      <div v-if="isSyncing" class="space-y-2">
        <div class="flex items-center justify-between text-sm">
          <span class="text-gray-600 dark:text-gray-400">{{ syncMessage }}</span>
          <span v-if="syncTotal > 0" class="text-gray-500">
            {{ syncCurrent.toLocaleString() }} / {{ syncTotal.toLocaleString() }}
          </span>
        </div>
        <UProgress :value="syncProgress" size="sm" />
      </div>

      <!-- Sync Error -->
      <div v-if="syncError" class="text-sm text-red-500">
        {{ syncError }}
      </div>

      <!-- Expanded Settings Panel -->
      <div v-if="showSettings && stats" class="pt-3 border-t border-gray-200 dark:border-gray-800 space-y-3">
        <div class="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p class="text-gray-500">Last.fm Tags</p>
            <p class="font-medium text-gray-900 dark:text-white">
              {{ stats.lastfm_tags.toLocaleString() }} tags
              · {{ stats.artists_with_tags?.toLocaleString() || 0 }}/{{ stats.artists }} artists enriched
            </p>
          </div>
          <div>
            <p class="text-gray-500">Artist Similarity</p>
            <p class="font-medium text-gray-900 dark:text-white">
              {{ stats.artist_similarities?.toLocaleString() || 0 }} connections
            </p>
          </div>
          <div>
            <p class="text-gray-500">Track Embeddings</p>
            <p class="font-medium text-gray-900 dark:text-white">
              {{ stats.tracks_with_embeddings?.toLocaleString() || 0 }}/{{ stats.tracks }} tracks
            </p>
          </div>
          <div>
            <p class="text-gray-500">Genres</p>
            <p class="font-medium text-gray-900 dark:text-white">
              {{ stats.genres.toLocaleString() }}
            </p>
          </div>
        </div>

        <div class="flex flex-wrap gap-2 pt-2">
          <UButton
            :loading="isSyncing"
            :disabled="isSyncing"
            variant="outline"
            size="xs"
            @click="syncLibrary(true)"
          >
            Full Sync
          </UButton>
          <UButton
            :loading="syncingLastfm"
            :disabled="syncingLastfm"
            variant="outline"
            size="xs"
            @click="syncLastfm"
          >
            Enrich from Last.fm
          </UButton>
          <UButton
            :loading="syncingEmbeddings"
            :disabled="syncingEmbeddings"
            variant="outline"
            size="xs"
            @click="syncEmbeddings"
          >
            Generate Embeddings
          </UButton>
          <UButton
            variant="outline"
            size="xs"
            @click="fetchStats"
          >
            Refresh Stats
          </UButton>
        </div>
      </div>
    </div>

    <UAlert
      v-if="syncError"
      color="red"
      icon="i-heroicons-exclamation-triangle"
      :description="syncError"
      class="mb-4"
    />

    <!-- Empty State -->
    <div v-if="stats && stats.tracks === 0 && !isGenerating && !result" class="text-center py-12">
      <UIcon name="i-heroicons-musical-note" class="w-12 h-12 text-gray-400 mx-auto mb-4" />
      <h2 class="text-lg font-medium text-gray-900 dark:text-white mb-2">No tracks in library</h2>
      <p class="text-gray-500 mb-4">Sync your Jellyfin library to get started</p>
      <UButton @click="syncLibrary(false)" :loading="isSyncing">
        Sync from Jellyfin
      </UButton>
    </div>

    <!-- Input Form -->
    <div v-if="(!stats || stats.tracks > 0) && !isGenerating && !result" class="space-y-6">
      <div>
        <UTextarea
          v-model="prompt"
          placeholder="driving through fog at 3am"
          :rows="3"
          size="xl"
          autofocus
          class="w-full"
        />
      </div>

      <div class="flex items-center gap-4">
        <label class="text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">
          Playlist size:
        </label>
        <USlider
          v-model="playlistSize"
          :min="10"
          :max="100"
          :step="5"
          class="flex-1"
        />
        <span class="text-sm font-medium text-gray-900 dark:text-white w-16 text-right">
          {{ playlistSize }} tracks
        </span>
      </div>

      <UButton
        size="lg"
        :disabled="!prompt.trim()"
        class="w-full justify-center"
        @click="generatePlaylist"
      >
        Generate Playlist
      </UButton>
    </div>

    <!-- Progress View -->
    <div v-if="isGenerating" class="space-y-6">
      <div class="text-center">
        <p class="text-lg font-medium text-gray-900 dark:text-white mb-2">
          "{{ prompt }}"
        </p>
      </div>

      <UProgress :value="progress" size="lg" />

      <div class="space-y-2">
        <div
          v-for="(step, index) in progressSteps"
          :key="index"
          class="flex items-center gap-2 text-sm"
        >
          <UIcon
            v-if="step.done"
            name="i-heroicons-check-circle"
            class="w-5 h-5 text-green-500"
          />
          <UIcon
            v-else-if="index === progressSteps.findIndex(s => !s.done)"
            name="i-heroicons-arrow-path"
            class="w-5 h-5 text-blue-500 animate-spin"
          />
          <UIcon
            v-else
            name="i-heroicons-circle-stack"
            class="w-5 h-5 text-gray-300 dark:text-gray-600"
          />
          <span :class="step.done ? 'text-gray-500' : 'text-gray-900 dark:text-white'">
            {{ step.message }}
          </span>
        </div>
      </div>
    </div>

    <!-- Error View -->
    <UAlert
      v-if="error"
      color="red"
      icon="i-heroicons-exclamation-triangle"
      title="Generation Failed"
      :description="error"
    />

    <!-- Result View -->
    <div v-if="result" class="space-y-6">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-xl font-semibold text-gray-900 dark:text-white">
            {{ result.title }}
          </h2>
          <p class="text-sm text-gray-500">
            "{{ result.prompt }}" · {{ result.tracks.length }} tracks
            <span v-if="result.jellyfin_playlist_id" class="ml-2">
              ·
              <a
                :href="`https://jellyfin.4eva.me/web/index.html#!/details?id=${result.jellyfin_playlist_id}`"
                target="_blank"
                class="text-primary-500 hover:underline"
              >
                Open in Jellyfin →
              </a>
            </span>
          </p>
        </div>
        <UButton
          variant="outline"
          @click="result = null; prompt = ''"
        >
          New Playlist
        </UButton>
      </div>

      <UAlert
        v-if="result.warning"
        color="yellow"
        icon="i-heroicons-exclamation-triangle"
        :description="result.warning"
      />

      <div class="divide-y divide-gray-200 dark:divide-gray-800 rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
        <div
          v-for="(track, index) in result.tracks"
          :key="track.id"
          class="flex items-center gap-4 p-3 hover:bg-gray-50 dark:hover:bg-gray-900"
        >
          <span class="text-sm text-gray-400 w-6 text-right">{{ index + 1 }}</span>
          <div class="flex-1 min-w-0">
            <p class="font-medium text-gray-900 dark:text-white truncate">
              {{ track.title }}
            </p>
            <p class="text-sm text-gray-500 truncate">
              {{ track.artist_name }} · {{ track.album_name }}
            </p>
          </div>
          <span class="text-sm text-gray-400">
            {{ formatDuration(track.duration_ms) }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
