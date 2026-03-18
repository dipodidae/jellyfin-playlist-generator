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
      // Silently fail — mappings are optional
    }
  }

  async function createPathMapping(mapping: { name: string, source_prefix: string, target_prefix: string }) {
    const response = await fetch('/api/path-mappings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(mapping),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || 'Failed to create mapping')
    }
    await fetchPathMappings()
  }

  async function deletePathMapping(name: string) {
    const response = await fetch(`/api/path-mappings/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || 'Failed to delete mapping')
    }
    await fetchPathMappings()
  }

  return { pathMappings, fetchPathMappings, createPathMapping, deletePathMapping }
}
