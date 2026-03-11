import { computed, ref } from 'vue'
import type { GeneratedPlaylist } from '~/types/playlist'
import type { PathMapping } from '~/types/library'

export function usePlaylistExport() {
  const exportMode = ref<'absolute' | 'relative' | 'mapped'>('absolute')
  const selectedMapping = ref<string | null>(null)
  const isExporting = ref(false)
  const exportError = ref<string | null>(null)

  const canExport = computed(
    () => exportMode.value !== 'mapped' || !!selectedMapping.value,
  )

  async function exportPlaylist(result: GeneratedPlaylist, pathMappings: PathMapping[]) {
    if (isExporting.value || !canExport.value) return

    isExporting.value = true
    exportError.value = null

    try {
      const trackIds = result.tracks.map(t => t.id)
      const response = await fetch('/api/export/m3u', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          track_ids: trackIds,
          mode: exportMode.value,
          mapping_name: exportMode.value === 'mapped' ? selectedMapping.value : null,
          playlist_name: result.title,
        }),
      })

      if (!response.ok) throw new Error('Export failed')

      const data = await response.json()

      const blob = new Blob([data.content], { type: 'audio/x-mpegurl' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${result.title || 'playlist'}.m3u`
      a.click()
      URL.revokeObjectURL(url)

      return true
    }
    catch (e) {
      exportError.value = e instanceof Error ? e.message : 'Export failed'
      return false
    }
    finally {
      isExporting.value = false
    }
  }

  return { exportMode, selectedMapping, isExporting, exportError, canExport, exportPlaylist }
}
