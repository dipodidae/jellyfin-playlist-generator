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
    <!-- Stage header row -->
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex flex-wrap items-center gap-2">
        <!-- Pulsing dot — "now indexing" console feel -->
        <span class="inline-flex size-2 rounded-full bg-acid-400 animate-pulse shrink-0" />
        <span class="font-display font-semibold text-white text-sm">{{ scanStageText }}</span>
        <UBadge
          v-if="scanAttachmentText"
          color="neutral"
          variant="subtle"
          size="sm"
        >
          {{ scanAttachmentText }}
        </UBadge>
        <span v-if="scanElapsedText" class="text-xs text-(--ui-text-dimmed)">
          <UIcon name="i-lucide-timer" class="size-3 inline mr-0.5 align-middle" />
          {{ scanElapsedText }}
        </span>
      </div>
      <UBadge
        v-if="syncStatus.total > 0"
        color="neutral"
        variant="outline"
        size="sm"
        class="tabular"
      >
        {{ syncStatus.current.toLocaleString() }} / {{ syncStatus.total.toLocaleString() }}
      </UBadge>
    </div>

    <!-- Progress bar + stats -->
    <ScanProgressBar
      :progress-value="scanProgressValue"
      :message="scanMessage"
      :stats="currentSyncStats"
    />

    <!-- Recent scan activity log -->
    <div v-if="syncActivity.length" class="glass rounded-xl p-3 space-y-2.5">
      <div class="flex items-center gap-2 mb-1">
        <UIcon name="i-lucide-terminal" class="size-3.5 text-acid-400/70" />
        <span class="text-[11px] font-semibold uppercase tracking-widest text-(--ui-text-dimmed)">Scan activity</span>
      </div>
      <ScanActivityRow
        v-for="(event, index) in syncActivity"
        :key="`${event.created_at || index}-${event.stage}-${event.message}`"
        :event="event"
      />
    </div>
  </div>
</template>
