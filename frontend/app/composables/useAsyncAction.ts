import { ref } from 'vue'

export function useAsyncAction<T = void>(
  action: () => Promise<T>,
  options?: { onCompleted?: (result: T) => void },
) {
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function execute() {
    if (loading.value) return
    loading.value = true
    error.value = null
    try {
      const result = await action()
      options?.onCompleted?.(result)
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : 'Unknown error'
    }
    finally {
      loading.value = false
    }
  }

  return { loading, error, execute }
}
