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

const GROUPS: { key: SettingField['group'], label: string, icon: string, advanced?: boolean }[] = [
  { key: 'credentials', label: 'Credentials', icon: 'i-lucide-key-round' },
  { key: 'enrichment', label: 'Enrichment', icon: 'i-lucide-sparkles' },
  { key: 'jellyfin', label: 'Jellyfin', icon: 'i-lucide-tv-2' },
  { key: 'library', label: 'Library', icon: 'i-lucide-library' },
  { key: 'advanced', label: 'Advanced', icon: 'i-lucide-sliders-horizontal', advanced: true },
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
  <div class="rise-in space-y-8 pb-20">

    <!-- Page header -->
    <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="font-display text-3xl font-bold tracking-tight text-white">
          Settings
        </h1>
        <p class="mt-1 text-sm text-(--ui-text-muted)">
          Configure API credentials, enrichment sources, and library behaviour.
        </p>
      </div>

      <!-- Sticky Save — also duplicated at bottom for long pages -->
      <UButton
        color="primary"
        size="md"
        icon="i-lucide-save"
        :loading="saving"
        :disabled="saving || Object.keys(edits).length === 0"
        class="glow-acid shrink-0 self-start"
        @click="onSave"
      >
        Save changes
      </UButton>
    </div>

    <!-- Loading skeleton -->
    <div v-if="loading" class="space-y-4">
      <div v-for="i in 4" :key="i" class="glass h-28 animate-pulse rounded-2xl" />
    </div>

    <!-- Setting groups -->
    <div v-else class="space-y-6">
      <SectionCard
        v-for="g in GROUPS"
        :key="g.key"
      >
        <!-- Section header -->
        <div class="flex items-center gap-2.5 pb-1">
          <span class="h-4 w-1 rounded-full bg-acid-400" />
          <UIcon :name="g.icon" class="size-4 text-acid-400" />
          <h2 class="font-display text-base font-semibold tracking-tight text-white">
            {{ g.label }}
          </h2>
          <UBadge
            v-if="g.advanced"
            label="Advanced"
            color="neutral"
            variant="subtle"
            size="xs"
            class="ml-auto"
          />
        </div>

        <!-- Fields grid: 1-col mobile → 2-col md+ -->
        <div class="grid grid-cols-1 gap-x-6 gap-y-4 md:grid-cols-2">
          <UFormField
            v-for="f in fieldsFor(g.key)"
            :key="f.key"
            :label="f.label"
            class="space-y-1"
          >
            <!-- Bool toggle -->
            <USwitch
              v-if="f.type === 'bool'"
              :model-value="modelFor(f) === true || modelFor(f) === 'true'"
              color="primary"
              @update:model-value="(v: boolean) => setField(f, v)"
            />

            <!-- Secret / password -->
            <UInput
              v-else-if="f.secret"
              type="password"
              :placeholder="f.is_set ? f.masked : 'not set'"
              :model-value="(edits[f.key] ?? '')"
              class="w-full"
              @update:model-value="(v: string) => setField(f, v)"
            />

            <!-- Numeric or text -->
            <UInput
              v-else
              :type="(f.type === 'int' || f.type === 'float') ? 'number' : 'text'"
              :model-value="String(modelFor(f) ?? '')"
              class="w-full"
              @update:model-value="(v: string) => setField(f, v)"
            />
          </UFormField>
        </div>

        <!-- Per-group action bar: Credentials -->
        <div v-if="g.key === 'credentials'" class="mt-2 flex flex-wrap items-center gap-2 border-t border-(--ui-border) pt-4">
          <span class="mr-1 text-xs font-semibold uppercase tracking-wider text-(--ui-text-dimmed)">Test</span>

          <UButton size="xs" variant="soft" icon="i-lucide-activity" @click="onTest('lastfm')">
            Last.fm
          </UButton>
          <span
            v-if="testResults['lastfm']"
            class="text-xs"
            :class="testResults['lastfm'].startsWith('✓') ? 'text-acid-400' : 'text-red-400'"
          >{{ testResults['lastfm'] }}</span>

          <UButton size="xs" variant="soft" icon="i-lucide-activity" @click="onTest('openai')">
            OpenAI
          </UButton>
          <span
            v-if="testResults['openai']"
            class="text-xs"
            :class="testResults['openai'].startsWith('✓') ? 'text-acid-400' : 'text-red-400'"
          >{{ testResults['openai'] }}</span>

          <UButton size="xs" variant="soft" icon="i-lucide-activity" @click="onTest('discogs')">
            Discogs
          </UButton>
          <span
            v-if="testResults['discogs']"
            class="text-xs"
            :class="testResults['discogs'].startsWith('✓') ? 'text-acid-400' : 'text-red-400'"
          >{{ testResults['discogs'] }}</span>

          <div class="ml-auto flex items-center gap-2">
            <UBadge
              :label="discogsStatus"
              :color="discogsStatus === 'Connected (OAuth)' ? 'primary' : discogsStatus === 'Using key/secret' ? 'warning' : 'neutral'"
              variant="subtle"
              size="xs"
            />
            <UButton
              size="xs"
              color="primary"
              variant="soft"
              icon="i-lucide-link"
              @click="onConnectDiscogs"
            >
              Connect with Discogs
            </UButton>
          </div>
        </div>

        <!-- Per-group action bar: Jellyfin -->
        <div v-if="g.key === 'jellyfin'" class="mt-2 flex flex-wrap items-center gap-2 border-t border-(--ui-border) pt-4">
          <UButton size="xs" variant="soft" icon="i-lucide-activity" @click="onTest('jellyfin')">
            Test Jellyfin
          </UButton>
          <span
            v-if="testResults['jellyfin']"
            class="text-xs"
            :class="testResults['jellyfin'].startsWith('✓') ? 'text-acid-400' : 'text-red-400'"
          >{{ testResults['jellyfin'] }}</span>
        </div>
      </SectionCard>
    </div>

    <!-- Bottom save bar (prominent for long forms) -->
    <div class="flex items-center justify-between rounded-2xl border border-(--ui-border) bg-(--ui-bg-elevated)/60 px-5 py-4 backdrop-blur-sm">
      <p class="text-sm text-(--ui-text-muted)">
        <span v-if="Object.keys(edits).length > 0" class="text-acid-400 font-semibold">
          {{ Object.keys(edits).length }} unsaved change{{ Object.keys(edits).length === 1 ? '' : 's' }}
        </span>
        <span v-else>All changes saved.</span>
      </p>
      <UButton
        color="primary"
        size="md"
        icon="i-lucide-save"
        :loading="saving"
        :disabled="saving || Object.keys(edits).length === 0"
        class="glow-acid"
        @click="onSave"
      >
        Save changes
      </UButton>
    </div>

  </div>
</template>
