<script setup lang="ts">
const showSettings = ref(false)
const showExportModal = ref(false)

const libraryStats = useLibraryStats()
const sync = useLibrarySync({ onCompleted: libraryStats.fetchStats })
const enrichment = useLibraryEnrichment({ onCompleted: libraryStats.fetchStats })
const playlist = usePlaylistGeneration()
const mappings = usePathMappings()
const exporter = usePlaylistExport()

onMounted(async () => {
  await Promise.all([
    libraryStats.fetchStats(),
    sync.restoreStatus(),
    sync.fetchHistory(),
    mappings.fetchPathMappings(),
  ])
})

async function handleExportConfirm() {
  if (!playlist.result.value) return
  const success = await exporter.exportPlaylist(playlist.result.value, mappings.pathMappings.value)
  if (success) showExportModal.value = false
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
        :show-settings="showSettings"
        @toggle-settings="showSettings = !showSettings"
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
        v-if="showSettings && libraryStats.stats.value"
        :stats="libraryStats.stats.value"
        :is-syncing="sync.isSyncing.value"
        :syncing-lastfm="enrichment.syncingLastfm.value"
        :syncing-embeddings="enrichment.syncingEmbeddings.value"
        :syncing-profiles="enrichment.syncingProfiles.value"
        @full-sync="sync.startScan(true)"
        @sync-lastfm="enrichment.syncLastfm()"
        @sync-embeddings="enrichment.syncEmbeddings()"
        @sync-profiles="enrichment.syncProfiles()"
        @refresh-stats="libraryStats.fetchStats()"
      />
    </div>

    <!-- Duplicate sync error alert (below status bar) -->
    <UAlert
      v-if="sync.syncError.value"
      color="red"
      icon="i-heroicons-exclamation-triangle"
      :description="sync.syncError.value"
      class="mb-4"
    />

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
      @export="showExportModal = true"
      @reset="playlist.reset()"
    />

    <!-- Export modal -->
    <PlaylistExportModal
      v-if="playlist.result.value"
      :model-value="showExportModal"
      :export-mode="exporter.exportMode.value"
      :selected-mapping="exporter.selectedMapping.value"
      :path-mappings="mappings.pathMappings.value"
      :is-exporting="exporter.isExporting.value"
      :can-export="exporter.canExport.value"
      @update:model-value="showExportModal = $event"
      @update:export-mode="exporter.exportMode.value = $event"
      @update:selected-mapping="exporter.selectedMapping.value = $event"
      @confirm="handleExportConfirm"
    />

    <!-- Recent scan jobs -->
    <RecentScanJobs
      v-if="sync.recentScanJobs.value.length"
      :jobs="sync.recentScanJobs.value"
    />
  </div>
</template>
