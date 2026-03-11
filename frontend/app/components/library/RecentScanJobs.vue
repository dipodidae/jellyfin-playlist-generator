<script setup lang="ts">
import type { ScanStatus } from '~/types/library'
import { useStageLabel } from '~/composables/useStageLabel'

defineProps<{
  jobs: ScanStatus[]
}>()

const { stageLabel } = useStageLabel()

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function formatDuration(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return ''
  const ms = (end ? new Date(end) : new Date()).getTime() - new Date(start).getTime()
  const s = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(s / 60)
  return m > 0 ? `${m}m ${s % 60}s` : `${s}s`
}
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
          <div class="flex items-center gap-2">
            <span class="font-medium text-gray-900 dark:text-white">
              {{ job.scan_type === 'full' ? 'Full scan' : 'Incremental scan' }}
            </span>
            <UTooltip
              v-if="job.started_at"
              :text="`Started: ${new Date(job.started_at).toLocaleString()}${job.completed_at ? '\nFinished: ' + new Date(job.completed_at).toLocaleString() : ''}`"
            >
              <span class="text-xs text-gray-400 cursor-default">
                {{ relativeTime(job.started_at) }}
                <span v-if="job.completed_at || job.status !== 'running'" class="ml-1">
                  · {{ formatDuration(job.started_at, job.completed_at) }}
                </span>
              </span>
            </UTooltip>
          </div>
          <div class="truncate text-gray-500 text-xs mt-0.5">
            {{ stageLabel(job.stage) }} · {{ job.message || 'No message' }}
          </div>
        </div>
        <div class="shrink-0 text-right">
          <div class="text-gray-900 dark:text-white text-sm">{{ job.progress }}%</div>
          <div
            class="text-xs"
            :class="{
              'text-green-500': job.status === 'completed',
              'text-red-500': job.status === 'failed',
              'text-blue-500': job.status === 'running',
              'text-gray-500': job.status !== 'completed' && job.status !== 'failed' && job.status !== 'running',
            }"
          >
            {{ job.status }}
          </div>
        </div>
      </div>
    </div>
  </SectionCard>
</template>
