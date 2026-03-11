<script setup lang="ts">
import type { ScanEvent } from '~/types/library'
import { useStageLabel } from '~/composables/useStageLabel'

defineProps<{
  event: ScanEvent
}>()

const { stageLabel } = useStageLabel()
</script>

<template>
  <div class="flex items-start justify-between gap-3 text-sm">
    <div class="min-w-0">
      <div class="font-medium text-gray-900 dark:text-white">{{ stageLabel(event.stage) }}</div>
      <div class="truncate text-gray-500">{{ event.message }}</div>
    </div>
    <div class="shrink-0 text-xs text-gray-400">
      <span v-if="event.total > 0">{{ event.current.toLocaleString() }} / {{ event.total.toLocaleString() }}</span>
    </div>
  </div>
</template>
