import type { ObservatoryData } from '~/types/observatory'

export function useObservatory() {
  const data = ref<ObservatoryData | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchStats(forceRefresh = false) {
    loading.value = true
    error.value = null

    try {
      const url = forceRefresh ? '/api/observatory/stats?refresh=true' : '/api/observatory/stats'
      const response = await fetch(url)

      if (!response.ok) {
        throw new Error(`Failed to load observatory stats (${response.status})`)
      }

      data.value = await response.json()
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : 'Unknown error'
    }
    finally {
      loading.value = false
    }
  }

  return {
    data,
    loading,
    error,
    fetchStats,
  }
}
