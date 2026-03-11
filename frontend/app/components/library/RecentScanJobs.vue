<script setup lang="ts">
import type { ScanStatus } from '~/types/library'
import { useStageLabel } from '~/composables/useStageLabel'

defineProps<{
  jobs: ScanStatus[]
}>()

const { stageLabel } = useStageLabel()
</script>

<template>
  <SectionCard>
    <div class="flex items-center justify-between mb-1">
      <h3 class="text-sm font-semibold text-gray-900 dark:text-white">Recent scans</h3>
      <span class="text-xs text-gray-500">Latest {{ jobs.length }}</span>
    </div>
    <div class="space-y-2">
      <div
        v-for="job in jobs"
        :key="job.job_id || job.started_at || job.message"
        class="flex items-center justify-between gap-4 rounded border border-gray-200 dark:border-gray-800 px-3 py-2 text-sm"
      >
        <div class="min-w-0">
          <div class="font-medium text-gray-900 dark:text-white">
            {{ job.scan_type === 'full' ? 'Full scan' : 'Incremental scan' }}
          </div>
          <div class="truncate text-gray-500">
            {{ stageLabel(job.stage) }} · {{ job.message || 'No message' }}
          </div>
        </div>
        <div class="shrink-0 text-right">
          <div class="text-gray-900 dark:text-white">{{ job.progress }}%</div>
          <div class="text-xs text-gray-500">{{ job.status }}</div>
        </div>
      </div>
    </div>
  </SectionCard>
</template>
