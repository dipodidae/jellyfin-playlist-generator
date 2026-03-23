<script setup lang="ts">
const showExportModal = ref(false)
const toast = useToast()

const libraryStats = useLibraryStats()
const sync = useLibrarySync({ onCompleted: libraryStats.fetchStats })
const playlist = usePlaylistGeneration()
const mappings = usePathMappings()
const exporter = usePlaylistExport()
const jellyfin = useJellyfinExport()

onMounted(async () => {
  await Promise.all([
    libraryStats.fetchStats(),
    sync.restoreStatus(),
    sync.fetchHistory(),
    mappings.fetchPathMappings(),
    jellyfin.checkAvailability(),
  ])
})

async function handleExportConfirm() {
  if (!playlist.result.value) return
  const success = await exporter.exportPlaylist(playlist.result.value, mappings.pathMappings.value)
  if (success) showExportModal.value = false
}

async function handleCreateMapping(mapping: { name: string, source_prefix: string, target_prefix: string }) {
  try {
    await mappings.createPathMapping(mapping)
    toast.add({ title: 'Path mapping created', color: 'success' })
  }
  catch (e) {
    toast.add({ title: 'Failed to create mapping', description: e instanceof Error ? e.message : 'Unknown error', color: 'error' })
  }
}

async function handleDeleteMapping(name: string) {
  try {
    await mappings.deletePathMapping(name)
    // Clear selection if deleted mapping was selected
    if (exporter.selectedMapping.value === name) {
      exporter.selectedMapping.value = null
    }
    toast.add({ title: 'Path mapping deleted', color: 'success' })
  }
  catch (e) {
    toast.add({ title: 'Failed to delete mapping', description: e instanceof Error ? e.message : 'Unknown error', color: 'error' })
  }
}

async function handleJellyfinExport() {
  if (!playlist.result.value) return

  const result = await jellyfin.exportToJellyfin(playlist.result.value)

  if (result?.success) {
    const desc = result.matched_count < result.total_count
      ? `${result.matched_count}/${result.total_count} tracks matched. ${result.unmatched_tracks.map(t => t.title).join(', ')} could not be found.`
      : `All ${result.matched_count} tracks added.`

    toast.add({
      title: 'Playlist pushed to Jellyfin',
      description: desc,
      color: 'success',
    })
  }
  else {
    toast.add({
      title: 'Jellyfin export failed',
      description: jellyfin.exportError.value || 'Unknown error',
      color: 'error',
    })
  }
}
</script>

<template>
  <div class="space-y-8">
    <!-- Library status bar -->
    <div class="p-4 bg-gray-100 dark:bg-gray-900 rounded-lg space-y-3">
      <LibraryStatusBar
        :stats="libraryStats.stats.value"
        :is-syncing="sync.isSyncing.value"
        :last-sync-time="sync.lastSyncTime.value"
        @scan="sync.startScan(false)"
      />

      <LibrarySyncProgress
        v-if="sync.syncStatus.value"
        :sync-status="sync.syncStatus.value"
        :sync-activity="sync.syncActivity.value"
        :scan-stage-text="sync.scanStageText.value"
        :scan-attachment-text="sync.scanAttachmentText.value"
        :scan-elapsed-text="sync.scanElapsedText.value"
        :scan-message="sync.scanMessage.value"
        :scan-progress-value="sync.scanProgressValue.value"
        :current-sync-stats="sync.currentSyncStats.value"
      />

      <AppErrorAlert
        v-if="sync.syncError.value"
        :description="sync.syncError.value"
      />

      <LibrarySettingsPanel
        v-if="libraryStats.stats.value"
        :stats="libraryStats.stats.value"
        :is-syncing="sync.isSyncing.value"
        @full-sync="sync.startScan(true)"
        @refresh-stats="libraryStats.fetchStats()"
      />

      <!-- Cold-start quality warning -->
      <div
        v-if="libraryStats.stats.value?.cold_start?.recommendation"
        class="mt-2 flex items-center gap-2 rounded px-3 py-2 text-xs"
        :class="libraryStats.stats.value.cold_start.quality_level === 'low'
          ? 'bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300'
          : 'bg-yellow-50 dark:bg-yellow-950 text-yellow-700 dark:text-yellow-300'"
      >
        <span class="shrink-0">{{ libraryStats.stats.value.cold_start.quality_level === 'low' ? '⚠️' : 'ℹ️' }}</span>
        <span>{{ libraryStats.stats.value.cold_start.recommendation }}</span>
      </div>
    </div>

    <!-- Empty library state -->
    <EmptyLibraryState
      v-if="libraryStats.stats.value && libraryStats.stats.value.tracks === 0 && !playlist.isGenerating.value && !playlist.result.value && !sync.isSyncing.value"
      :is-syncing="sync.isSyncing.value"
      @scan="sync.startScan(false)"
    />

    <!-- Prompt form -->
    <PlaylistPromptForm
      v-if="(!libraryStats.stats.value || libraryStats.hasLibraryData.value) && !playlist.isGenerating.value && !playlist.result.value"
      :model-value="playlist.prompt.value"
      :playlist-size="playlist.playlistSize.value"
      :can-generate="playlist.canGenerate.value"
      :has-library-data="libraryStats.hasLibraryData.value"
      @update:model-value="playlist.prompt.value = $event"
      @update:playlist-size="playlist.playlistSize.value = $event"
      @submit="playlist.generatePlaylist()"
    />

    <!-- Generation progress -->
    <PlaylistGenerationProgress
      v-if="playlist.isGenerating.value"
      :prompt="playlist.prompt.value"
      :progress="playlist.progress.value"
      :progress-steps="playlist.progressSteps.value"
    />

    <!-- Generation error -->
    <AppErrorAlert
      v-if="playlist.error.value"
      title="Generation Failed"
      :description="playlist.error.value"
    />

    <!-- Playlist result -->
    <PlaylistResultPanel
      v-if="playlist.result.value"
      :result="playlist.result.value"
      :has-library-data="libraryStats.hasLibraryData.value"
      :jellyfin-available="jellyfin.jellyfinAvailable.value"
      :is-jellyfin-exporting="jellyfin.isExporting.value"
      @export="showExportModal = true"
      @jellyfin="handleJellyfinExport"
      @reset="playlist.reset()"
      @update:title="(title: string) => { if (playlist.result.value) playlist.result.value.title = title }"
      @remove-track="(trackId: string) => { if (playlist.result.value) playlist.result.value.tracks = playlist.result.value.tracks.filter(t => t.id !== trackId) }"
    />

    <!-- Export modal -->
    <PlaylistExportModal
      v-if="playlist.result.value"
      :open="showExportModal"
      :export-mode="exporter.exportMode.value"
      :selected-mapping="exporter.selectedMapping.value"
      :path-mappings="mappings.pathMappings.value"
      :is-exporting="exporter.isExporting.value"
      :can-export="exporter.canExport.value"
      :export-error="exporter.exportError.value"
      @update:open="showExportModal = $event"
      @update:export-mode="exporter.exportMode.value = $event"
      @update:selected-mapping="exporter.selectedMapping.value = $event"
      @confirm="handleExportConfirm"
      @create-mapping="handleCreateMapping"
      @delete-mapping="handleDeleteMapping"
    />

    <!-- Recent scan jobs -->
    <RecentScanJobs
      v-if="sync.recentScanJobs.value.length"
      :jobs="sync.recentScanJobs.value"
    />
  </div>
</template>
