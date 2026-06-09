<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useSettings } from '~/composables/useSettings'
import type { SettingField } from '~/types/settings'

const { fields, loading, fetchSettings, saveSettings, testGroup, startDiscogsOauth } = useSettings()
const toast = useToast()
const route = useRoute()

// edits holds only changed keys (string values for the PUT payload)
const edits = reactive<Record<string, string>>({})
const saving = ref(false)
const testResults = reactive<Record<string, string>>({})

const GROUPS: { key: SettingField['group'], label: string, advanced?: boolean }[] = [
  { key: 'credentials', label: 'Credentials' },
  { key: 'enrichment', label: 'Enrichment' },
  { key: 'jellyfin', label: 'Jellyfin' },
  { key: 'library', label: 'Library' },
  { key: 'advanced', label: 'Advanced', advanced: true },
]

function fieldsFor(group: string) {
  return fields.value.filter(f => f.group === group)
}

function modelFor(f: SettingField) {
  if (f.key in edits) return edits[f.key]
  if (f.secret) return '' // password field starts blank; placeholder shows mask
  if (f.type === 'bool') return f.value
  return f.value ?? ''
}

function setField(f: SettingField, val: string | boolean) {
  edits[f.key] = typeof val === 'boolean' ? String(val) : val
}

async function onSave() {
  saving.value = true
  try {
    await saveSettings({ ...edits })
    Object.keys(edits).forEach(k => delete edits[k])
    toast.add({ title: 'Settings saved', color: 'success' })
  }
  catch (e) {
    toast.add({ title: 'Save failed', description: String(e), color: 'error' })
  }
  finally {
    saving.value = false
  }
}

async function onTest(group: string) {
  const r = await testGroup(group)
  testResults[group] = `${r.ok ? '✓' : '✗'} ${r.message}`
}

async function onConnectDiscogs() {
  try {
    const url = await startDiscogsOauth()
    window.open(url, '_blank')
  }
  catch (e) {
    toast.add({ title: 'Discogs OAuth failed', description: String(e), color: 'error' })
  }
}

const discogsStatus = computed(() => {
  const tok = fields.value.find(f => f.key === 'discogs_oauth_token')
  if (tok?.is_set) return 'Connected (OAuth)'
  const ck = fields.value.find(f => f.key === 'discogs_consumer_key')
  if (ck?.is_set) return 'Using key/secret'
  return 'Not configured'
})

onMounted(async () => {
  await fetchSettings()
  if (route.query.discogs === 'connected') toast.add({ title: 'Discogs connected', color: 'success' })
  if (route.query.discogs === 'error') toast.add({ title: 'Discogs OAuth error', color: 'error' })
})
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-semibold">Settings</h1>
      <UButton :loading="saving" @click="onSave">Save changes</UButton>
    </div>

    <div v-if="loading">Loading…</div>

    <div v-else class="space-y-8">
      <section v-for="g in GROUPS" :key="g.key">
        <h2 class="text-lg font-medium mb-3">{{ g.label }}</h2>
        <div class="space-y-3">
          <div v-for="f in fieldsFor(g.key)" :key="f.key" class="flex items-center gap-3">
            <label class="w-64 text-sm text-gray-600 dark:text-gray-400">{{ f.label }}</label>

            <USwitch
              v-if="f.type === 'bool'"
              :model-value="modelFor(f) === true || modelFor(f) === 'true'"
              @update:model-value="(v: boolean) => setField(f, v)"
            />
            <UInput
              v-else-if="f.secret"
              type="password"
              :placeholder="f.is_set ? f.masked : 'not set'"
              :model-value="(edits[f.key] ?? '')"
              class="flex-1"
              @update:model-value="(v: string) => setField(f, v)"
            />
            <UInput
              v-else
              :type="(f.type === 'int' || f.type === 'float') ? 'number' : 'text'"
              :model-value="String(modelFor(f) ?? '')"
              class="flex-1"
              @update:model-value="(v: string) => setField(f, v)"
            />
          </div>

          <!-- Per-group test / connect actions -->
          <div v-if="g.key === 'credentials'" class="flex flex-wrap gap-2 pt-2">
            <UButton size="xs" variant="soft" @click="onTest('lastfm')">Test Last.fm</UButton>
            <span class="text-xs self-center">{{ testResults['lastfm'] }}</span>
            <UButton size="xs" variant="soft" @click="onTest('openai')">Test OpenAI</UButton>
            <span class="text-xs self-center">{{ testResults['openai'] }}</span>
            <UButton size="xs" variant="soft" @click="onTest('discogs')">Test Discogs</UButton>
            <span class="text-xs self-center">{{ testResults['discogs'] }}</span>
            <UButton size="xs" color="primary" @click="onConnectDiscogs">Connect with Discogs</UButton>
            <span class="text-xs self-center">{{ discogsStatus }}</span>
          </div>
          <div v-if="g.key === 'jellyfin'" class="flex gap-2 pt-2">
            <UButton size="xs" variant="soft" @click="onTest('jellyfin')">Test Jellyfin</UButton>
            <span class="text-xs self-center">{{ testResults['jellyfin'] }}</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
