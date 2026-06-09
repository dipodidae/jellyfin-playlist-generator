import { ref } from 'vue'
import type { SettingField, SettingsResponse, TestResult } from '~/types/settings'

export function useSettings() {
  const fields = ref<SettingField[]>([])
  const loading = ref(false)

  async function fetchSettings() {
    loading.value = true
    try {
      const res = await fetch('/api/settings')
      if (res.ok) {
        const data: SettingsResponse = await res.json()
        fields.value = data.fields
      }
    }
    finally {
      loading.value = false
    }
  }

  async function saveSettings(values: Record<string, string>) {
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    })
    if (!res.ok) throw new Error((await res.json()).detail ?? 'Save failed')
    await fetchSettings()
  }

  async function testGroup(group: string): Promise<TestResult> {
    const res = await fetch(`/api/settings/test/${group}`, { method: 'POST' })
    return res.json()
  }

  async function startDiscogsOauth(): Promise<string> {
    const res = await fetch('/api/settings/discogs/oauth/start', { method: 'POST' })
    if (!res.ok) throw new Error((await res.json()).detail ?? 'OAuth start failed')
    return (await res.json()).authorize_url
  }

  return { fields, loading, fetchSettings, saveSettings, testGroup, startDiscogsOauth }
}
