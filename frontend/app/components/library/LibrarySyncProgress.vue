<script setup lang="ts">
import type { ScanEvent, ScanStats, ScanStatus } from '~/types/library'

defineProps<{
  syncStatus: ScanStatus
  syncActivity: ScanEvent[]
  scanStageText: string
  scanAttachmentText: string
  scanElapsedText: string
  scanMessage: string
  scanProgressValue: number
  currentSyncStats: ScanStats
}>()
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2 text-sm">
      <div class="flex items-center gap-2">
        <span class="font-medium text-gray-900 dark:text-white">{{ scanStageText }}</span>
        <span v-if="scanAttachmentText" class="text-xs text-gray-500">{{ scanAttachmentText }}</span>
        <span v-if="scanElapsedText" class="text-xs text-gray-500">Elapsed {{ scanElapsedText }}</span>
      </div>
      <span v-if="syncStatus.total > 0" class="text-gray-500">
        {{ syncStatus.current.toLocaleString() }} / {{ syncStatus.total.toLocaleString() }}
      </span>
    </div>

    <ScanProgressBar
      :progress-value="scanProgressValue"
      :message="scanMessage"
      :stats="currentSyncStats"
    />

    <div v-if="syncActivity.length" class="rounded border border-gray-200 dark:border-gray-800 p-3">
      <div class="mb-2 text-xs font-medium uppercase tracking-wide text-gray-500">Recent scan activity</div>
      <div class="space-y-2">
        <ScanActivityRow
          v-for="(event, index) in syncActivity"
          :key="`${event.created_at || index}-${event.stage}-${event.message}`"
          :event="event"
        />
      </div>
    </div>
  </div>
</template>
