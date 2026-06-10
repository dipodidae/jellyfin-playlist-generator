<script setup lang="ts">
import type { ScanStats } from '~/types/library'

defineProps<{
  progressValue: number
  message: string
  stats: ScanStats
}>()
</script>

<template>
  <div class="space-y-2.5">
    <!-- Progress header -->
    <div class="flex items-center justify-between text-xs">
      <span class="text-(--ui-text-muted) truncate pr-3">{{ message }}</span>
      <span class="tabular font-semibold text-acid-300 shrink-0">{{ progressValue }}%</span>
    </div>

    <!-- Acid-accented progress bar -->
    <UProgress
      :model-value="progressValue"
      :max="100"
      size="xs"
      color="primary"
      :ui="{ base: 'bg-(--ui-bg-accented)' }"
    />

    <!-- Stats row -->
    <div class="grid grid-cols-2 gap-2.5 text-xs md:grid-cols-4">
      <div class="rounded-lg border border-(--ui-border) bg-(--ui-bg-elevated)/40 px-2.5 py-1.5">
        <span class="block text-(--ui-text-dimmed) mb-0.5">Files found</span>
        <span class="tabular font-semibold text-white">{{ stats.files_found.toLocaleString() }}</span>
      </div>
      <div class="rounded-lg border border-(--ui-border) bg-(--ui-bg-elevated)/40 px-2.5 py-1.5">
        <span class="block text-(--ui-text-dimmed) mb-0.5">Skipped</span>
        <span class="tabular font-semibold text-white">{{ stats.files_skipped.toLocaleString() }}</span>
      </div>
      <div class="rounded-lg border border-(--ui-border) bg-(--ui-bg-elevated)/40 px-2.5 py-1.5">
        <span class="block text-(--ui-text-dimmed) mb-0.5">Added / updated</span>
        <span class="tabular font-semibold text-white">{{ stats.tracks_added.toLocaleString() }} / {{ stats.tracks_updated.toLocaleString() }}</span>
      </div>
      <div class="rounded-lg border border-(--ui-border) bg-(--ui-bg-elevated)/40 px-2.5 py-1.5">
        <span class="block text-(--ui-text-dimmed) mb-0.5">Errors</span>
        <span class="tabular font-semibold" :class="stats.errors > 0 ? 'text-red-400' : 'text-white'">{{ stats.errors.toLocaleString() }}</span>
      </div>
    </div>
  </div>
</template>
