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

type BadgeColor = 'success' | 'error' | 'info' | 'neutral'

function statusColor(status: string): BadgeColor {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'running') return 'info'
  return 'neutral'
}

function statusIcon(status: string): string {
  if (status === 'completed') return 'i-lucide-circle-check'
  if (status === 'failed') return 'i-lucide-circle-x'
  if (status === 'running') return 'i-lucide-loader'
  return 'i-lucide-circle-dashed'
}
</script>

<template>
  <SectionCard>
    <div class="flex items-center justify-between mb-3">
      <div class="flex items-center gap-2">
        <UIcon name="i-lucide-history" class="size-4 text-acid-400" />
        <h3 class="font-display text-sm font-semibold text-white">Recent scans</h3>
      </div>
      <span class="text-xs text-(--ui-text-dimmed)">Latest {{ jobs.length }}</span>
    </div>

    <div class="space-y-2">
      <div
        v-for="job in jobs"
        :key="job.job_id || job.started_at || job.message"
        class="flex items-center justify-between gap-4 rounded-xl border border-(--ui-border) bg-(--ui-bg-elevated)/40 px-3 py-2.5"
      >
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-medium text-sm text-white">
              {{ job.scan_type === 'full' ? 'Full scan' : 'Incremental scan' }}
            </span>
            <UTooltip
              v-if="job.started_at"
              :text="`Started: ${new Date(job.started_at).toLocaleString()}${job.completed_at ? '\nFinished: ' + new Date(job.completed_at).toLocaleString() : ''}`"
            >
              <span class="text-xs text-(--ui-text-dimmed) tabular cursor-default">
                {{ relativeTime(job.started_at) }}
                <span v-if="job.completed_at || job.status !== 'running'" class="ml-1">
                  · {{ formatDuration(job.started_at, job.completed_at) }}
                </span>
              </span>
            </UTooltip>
          </div>
          <div class="truncate text-(--ui-text-muted) text-xs mt-0.5">
            {{ stageLabel(job.stage) }} · {{ job.message || 'No message' }}
          </div>
        </div>

        <div class="shrink-0 flex flex-col items-end gap-1">
          <span class="tabular text-sm font-semibold text-white">{{ job.progress }}%</span>
          <UBadge
            :color="statusColor(job.status)"
            variant="subtle"
            size="xs"
            :icon="statusIcon(job.status)"
            :ui="{ icon: job.status === 'running' ? 'animate-spin' : '' }"
          >
            {{ job.status }}
          </UBadge>
        </div>
      </div>
    </div>
  </SectionCard>
</template>
