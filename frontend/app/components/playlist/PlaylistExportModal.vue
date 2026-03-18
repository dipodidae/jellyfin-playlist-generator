<script setup lang="ts">
import type { PathMapping } from '~/types/library'

const props = defineProps<{
  open: boolean
  exportMode: 'absolute' | 'mapped'
  selectedMapping: string | null
  pathMappings: PathMapping[]
  isExporting: boolean
  canExport: boolean
  exportError: string | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'update:exportMode': [value: 'absolute' | 'mapped']
  'update:selectedMapping': [value: string | null]
  confirm: []
  createMapping: [mapping: { name: string, source_prefix: string, target_prefix: string }]
  deleteMapping: [name: string]
}>()

const exportItems = [
  { label: 'Absolute paths', value: 'absolute', description: 'Full file paths as stored on disk' },
  { label: 'Mapped paths', value: 'mapped', description: 'Apply a path prefix replacement for your media server' },
]

const mappingItems = computed(() =>
  props.pathMappings.map(m => ({
    label: `${m.name}: ${m.source_prefix} → ${m.target_prefix}`,
    value: m.name,
  })),
)

// New mapping form
const showNewMapping = ref(false)
const newMapping = reactive({
  name: '',
  source_prefix: '',
  target_prefix: '',
})

function handleCreateMapping() {
  if (!newMapping.name || !newMapping.source_prefix || !newMapping.target_prefix) return
  emit('createMapping', { ...newMapping })
  newMapping.name = ''
  newMapping.source_prefix = ''
  newMapping.target_prefix = ''
  showNewMapping.value = false
}
</script>

<template>
  <UModal
    :open="open"
    title="Export Playlist"
    @update:open="emit('update:open', $event)"
  >
    <template #body>
      <div class="space-y-4">
        <!-- Error alert -->
        <UAlert
          v-if="exportError"
          color="error"
          icon="i-lucide-alert-circle"
          title="Export failed"
          :description="exportError"
        />

        <!-- Export mode -->
        <div>
          <label class="block text-sm font-medium mb-2">Export Mode</label>
          <URadioGroup
            :model-value="exportMode"
            :items="exportItems"
            @update:model-value="emit('update:exportMode', $event as 'absolute' | 'mapped')"
          />
        </div>

        <!-- Path mapping selection -->
        <div v-if="exportMode === 'mapped'" class="space-y-3">
          <label class="block text-sm font-medium">Path Mapping</label>

          <USelect
            v-if="mappingItems.length > 0"
            :model-value="selectedMapping"
            :items="mappingItems"
            placeholder="Select a mapping..."
            @update:model-value="emit('update:selectedMapping', $event as string)"
          />

          <!-- Existing mappings list with delete -->
          <div v-if="pathMappings.length > 0" class="space-y-1">
            <div
              v-for="m in pathMappings"
              :key="m.name"
              class="flex items-center justify-between rounded px-2 py-1 text-xs bg-elevated"
            >
              <span class="truncate">
                <span class="font-medium">{{ m.name }}</span>
                <span class="text-muted ml-1">{{ m.source_prefix }} → {{ m.target_prefix }}</span>
              </span>
              <UButton
                variant="ghost"
                color="error"
                size="xs"
                icon="i-lucide-trash-2"
                @click="emit('deleteMapping', m.name)"
              />
            </div>
          </div>

          <!-- Add new mapping -->
          <div v-if="!showNewMapping">
            <UButton
              variant="link"
              size="xs"
              icon="i-lucide-plus"
              @click="showNewMapping = true"
            >
              Add path mapping
            </UButton>
          </div>
          <div v-else class="space-y-2 rounded-lg border border-default p-3">
            <UInput v-model="newMapping.name" placeholder="Name (e.g. jellyfin)" size="sm" />
            <UInput v-model="newMapping.source_prefix" placeholder="Source prefix (e.g. /mnt/music)" size="sm" />
            <UInput v-model="newMapping.target_prefix" placeholder="Target prefix (e.g. /data/music)" size="sm" />
            <div class="flex gap-2">
              <UButton
                size="xs"
                :disabled="!newMapping.name || !newMapping.source_prefix || !newMapping.target_prefix"
                @click="handleCreateMapping"
              >
                Save
              </UButton>
              <UButton size="xs" variant="ghost" @click="showNewMapping = false">
                Cancel
              </UButton>
            </div>
          </div>

          <p v-if="pathMappings.length === 0 && !showNewMapping" class="text-sm text-muted">
            No path mappings configured. Add one to map local paths to your media server's paths.
          </p>
        </div>
      </div>
    </template>

    <template #footer>
      <div class="flex justify-end gap-2">
        <UButton variant="ghost" @click="emit('update:open', false)">
          Cancel
        </UButton>
        <UButton
          :loading="isExporting"
          :disabled="!canExport"
          @click="emit('confirm')"
        >
          Download M3U
        </UButton>
      </div>
    </template>
  </UModal>
</template>
