import { computed, ref } from 'vue'
import type { LibraryStats } from '~/types/library'

export function useLibraryStats() {
  const stats = ref<LibraryStats | null>(null)

  const hasLibraryData = computed(() => (stats.value?.tracks ?? 0) > 0)

  async function fetchStats() {
    try {
      const response = await fetch('/api/stats')
      if (response.ok) {
        stats.value = await response.json()
      }
    }
    catch {
      // Silently fail — stats are optional
    }
  }

  return { stats, hasLibraryData, fetchStats }
}
