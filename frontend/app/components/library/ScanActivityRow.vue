<script setup lang="ts">
import type { ScanEvent } from '~/types/library'
import { useStageLabel } from '~/composables/useStageLabel'

defineProps<{
  event: ScanEvent
}>()

const { stageLabel } = useStageLabel()
</script>

<template>
  <div class="flex items-start justify-between gap-3 text-sm min-w-0">
    <div class="min-w-0 flex items-start gap-2">
      <UIcon name="i-lucide-chevron-right" class="size-3.5 mt-0.5 text-acid-400/60 shrink-0" />
      <div class="min-w-0">
        <div class="font-medium text-white leading-snug">{{ stageLabel(event.stage) }}</div>
        <div class="truncate text-(--ui-text-muted) text-xs mt-0.5">{{ event.message }}</div>
      </div>
    </div>
    <div class="shrink-0 text-xs text-(--ui-text-dimmed) tabular whitespace-nowrap">
      <span v-if="event.total > 0">{{ event.current.toLocaleString() }}&thinsp;/&thinsp;{{ event.total.toLocaleString() }}</span>
    </div>
  </div>
</template>
