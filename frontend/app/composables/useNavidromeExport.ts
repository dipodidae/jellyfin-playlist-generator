import type { GeneratedPlaylist, NavidromeStatus, NavidromeExportResult } from '~/types/playlist'

/**
 * Push a generated playlist to Navidrome over Subsonic.
 *
 * Separate from useJellyfinExport rather than folded into it: Navidrome is what
 * Symfonium and the other Subsonic clients speak, and a Navidrome playlist
 * carries a comment and a public flag that Jellyfin has no field for. The two
 * can also be configured independently — one being down must not disable the
 * other's button.
 */
export function useNavidromeExport() {
  const navidromeAvailable = ref(false)
  const isExporting = ref(false)
  const exportError = ref<string | null>(null)
  const exportResult = ref<NavidromeExportResult | null>(null)

  async function checkAvailability() {
    try {
      const data = await $fetch<NavidromeStatus>('/api/navidrome/status')
      navidromeAvailable.value = data.available
    }
    catch {
      navidromeAvailable.value = false
    }
  }

  async function exportToNavidrome(result: GeneratedPlaylist): Promise<NavidromeExportResult | null> {
    if (isExporting.value) return null

    isExporting.value = true
    exportError.value = null
    exportResult.value = null

    try {
      const data = await $fetch<NavidromeExportResult>('/api/export/navidrome', {
        method: 'POST',
        body: {
          track_ids: result.tracks.map(t => t.id),
          playlist_name: result.title || 'Generated Playlist',
          // The prompt becomes the playlist's comment in Navidrome — the one
          // place a generated playlist's provenance survives alongside it.
          prompt: result.prompt,
        },
      })

      exportResult.value = data
      return data
    }
    catch (e: unknown) {
      // FastAPI puts the real reason in `data.detail`; the bare Error message
      // is just the status line, which tells the user nothing actionable.
      const detail = (e as { data?: { detail?: string } })?.data?.detail
      exportError.value = detail || (e instanceof Error ? e.message : 'Navidrome export failed')
      return null
    }
    finally {
      isExporting.value = false
    }
  }

  return {
    navidromeAvailable,
    isExporting,
    exportError,
    exportResult,
    checkAvailability,
    exportToNavidrome,
  }
}
