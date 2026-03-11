<script setup lang="ts">
import type { PathMapping } from '~/types/library'

defineProps<{
  modelValue: boolean
  exportMode: 'absolute' | 'relative' | 'mapped'
  selectedMapping: string | null
  pathMappings: PathMapping[]
  isExporting: boolean
  canExport: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'update:exportMode': [value: 'absolute' | 'relative' | 'mapped']
  'update:selectedMapping': [value: string | null]
  confirm: []
}>()

const exportOptions = [
  { label: 'Absolute paths', value: 'absolute', description: 'Full file paths as stored' },
  { label: 'Relative paths', value: 'relative', description: 'Relative to M3U file location' },
  { label: 'Mapped paths', value: 'mapped', description: 'Apply service-specific path mapping' },
]
</script>

<template>
  <UModal :open="modelValue" @update:open="emit('update:modelValue', $event)">
    <UCard>
      <template #header>
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-semibold">Export Playlist</h3>
          <UButton
            variant="ghost"
            icon="i-heroicons-x-mark"
            @click="emit('update:modelValue', false)"
          />
        </div>
      </template>

      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Export Mode
          </label>
          <URadioGroup
            :model-value="exportMode"
            :options="exportOptions"
            @update:model-value="emit('update:exportMode', $event)"
          />
        </div>

        <div v-if="exportMode === 'mapped'" class="space-y-2">
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">
            Path Mapping
          </label>
          <USelect
            :model-value="selectedMapping"
            :options="pathMappings.map(m => ({ label: `${m.name}: ${m.source_prefix} → ${m.target_prefix}`, value: m.name }))"
            placeholder="Select a mapping..."
            @update:model-value="emit('update:selectedMapping', $event)"
          />
          <p v-if="pathMappings.length === 0" class="text-sm text-gray-500">
            No path mappings configured. Add mappings in settings.
          </p>
        </div>
      </div>

      <template #footer>
        <div class="flex justify-end gap-2">
          <UButton variant="ghost" @click="emit('update:modelValue', false)">
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
    </UCard>
  </UModal>
</template>
