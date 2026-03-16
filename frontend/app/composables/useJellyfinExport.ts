import type { GeneratedPlaylist, JellyfinStatus, JellyfinExportResult } from '~/types/playlist'

export function useJellyfinExport() {
  const jellyfinAvailable = ref(false)
  const isExporting = ref(false)
  const exportError = ref<string | null>(null)
  const exportResult = ref<JellyfinExportResult | null>(null)

  async function checkAvailability() {
    try {
      const data = await $fetch<JellyfinStatus>('/api/jellyfin/status')
      jellyfinAvailable.value = data.available
    }
    catch {
      jellyfinAvailable.value = false
    }
  }

  async function exportToJellyfin(result: GeneratedPlaylist): Promise<JellyfinExportResult | null> {
    if (isExporting.value) return null

    isExporting.value = true
    exportError.value = null
    exportResult.value = null

    try {
      const trackIds = result.tracks.map(t => t.id)
      const data = await $fetch<JellyfinExportResult>('/api/export/jellyfin', {
        method: 'POST',
        body: {
          track_ids: trackIds,
          playlist_name: result.title || 'Generated Playlist',
        },
      })

      exportResult.value = data
      return data
    }
    catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Jellyfin export failed'
      exportError.value = message
      return null
    }
    finally {
      isExporting.value = false
    }
  }

  return {
    jellyfinAvailable,
    isExporting,
    exportError,
    exportResult,
    checkAvailability,
    exportToJellyfin,
  }
}
