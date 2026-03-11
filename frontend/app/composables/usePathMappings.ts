import { ref } from 'vue'
import type { PathMapping } from '~/types/library'

export function usePathMappings() {
  const pathMappings = ref<PathMapping[]>([])

  async function fetchPathMappings() {
    try {
      const response = await fetch('/api/path-mappings')
      if (response.ok) {
        pathMappings.value = await response.json()
      }
    }
    catch {
      // Silently fail
    }
  }

  return { pathMappings, fetchPathMappings }
}
