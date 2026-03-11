<script setup lang="ts">
import type { LibraryStats } from '~/types/library'

defineProps<{
  stats: LibraryStats | null
  isSyncing: boolean
  lastSyncTime: Date | null
}>()

const emit = defineEmits<{
  scan: []
}>()
</script>

<template>
  <div class="flex items-center justify-between">
    <div class="flex items-center gap-4">
      <div v-if="stats" class="text-sm text-gray-600 dark:text-gray-400">
        <span class="font-medium text-gray-900 dark:text-white">{{ stats.tracks.toLocaleString() }}</span> tracks
        ·
        <span class="font-medium text-gray-900 dark:text-white">{{ stats.artists.toLocaleString() }}</span> artists
        ·
        <span class="font-medium text-gray-900 dark:text-white">{{ (stats.track_files ?? stats.tracks).toLocaleString() }}</span> files
      </div>
      <div v-else class="text-sm text-gray-500">
        No library synced
      </div>
    </div>
    <div class="flex items-center gap-2">
      <span v-if="lastSyncTime && !isSyncing" class="text-xs text-gray-400">
        Last sync: {{ lastSyncTime.toLocaleTimeString() }}
      </span>
      <UButton
        :loading="isSyncing"
        :disabled="isSyncing"
        variant="soft"
        size="sm"
        @click="emit('scan')"
      >
        {{ isSyncing ? 'Scanning...' : 'Scan Library' }}
      </UButton>
    </div>
  </div>
</template>
