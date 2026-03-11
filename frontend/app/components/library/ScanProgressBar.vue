<script setup lang="ts">
import type { ScanStats } from '~/types/library'

defineProps<{
  progressValue: number
  message: string
  stats: ScanStats
}>()
</script>

<template>
  <div class="space-y-2">
    <div class="flex items-center justify-between text-sm">
      <span class="text-gray-600 dark:text-gray-400">{{ message }}</span>
      <span class="text-gray-500">{{ progressValue }}%</span>
    </div>
    <UProgress :value="progressValue" size="sm" />
    <div class="grid grid-cols-2 gap-3 text-xs text-gray-500 md:grid-cols-4">
      <div>
        <span class="block">Files found</span>
        <span class="font-medium text-gray-900 dark:text-white">{{ stats.files_found.toLocaleString() }}</span>
      </div>
      <div>
        <span class="block">Skipped</span>
        <span class="font-medium text-gray-900 dark:text-white">{{ stats.files_skipped.toLocaleString() }}</span>
      </div>
      <div>
        <span class="block">Added / updated</span>
        <span class="font-medium text-gray-900 dark:text-white">{{ stats.tracks_added.toLocaleString() }} / {{ stats.tracks_updated.toLocaleString() }}</span>
      </div>
      <div>
        <span class="block">Errors</span>
        <span class="font-medium text-gray-900 dark:text-white">{{ stats.errors.toLocaleString() }}</span>
      </div>
    </div>
  </div>
</template>
