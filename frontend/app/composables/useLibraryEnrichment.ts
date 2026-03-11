import { ref } from 'vue'

export function useLibraryEnrichment(options?: { onCompleted?: () => void }) {
  const syncingLastfm = ref(false)
  const syncingEmbeddings = ref(false)
  const syncingProfiles = ref(false)

  async function runJob(endpoint: string, loading: ReturnType<typeof ref<boolean>>) {
    if (loading.value) return
    loading.value = true
    try {
      await fetch(endpoint, { method: 'POST' })
      setTimeout(() => options?.onCompleted?.(), 5000)
    }
    finally {
      loading.value = false
    }
  }

  function syncLastfm() {
    return runJob('/api/enrich/lastfm', syncingLastfm)
  }

  function syncEmbeddings() {
    return runJob('/api/enrich/embeddings', syncingEmbeddings)
  }

  function syncProfiles() {
    return runJob('/api/enrich/profiles', syncingProfiles)
  }

  return { syncingLastfm, syncingEmbeddings, syncingProfiles, syncLastfm, syncEmbeddings, syncProfiles }
}
