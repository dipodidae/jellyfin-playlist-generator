<script setup lang="ts">
import type { CollectionOverviewStats, DominantDecade } from '~/types/observatory'

const props = defineProps<{
  stats: CollectionOverviewStats
  dominantDecade: DominantDecade | null
  oldestYear: number | null
  newestYear: number | null
}>()

const { formatDuration } = useDurationFormatter()

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 4) return `${(bytes / 1024 ** 4).toFixed(1)} TB`
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024).toFixed(1)} KB`
}

function formatPlaytime(ms: number): string {
  const totalHours = ms / 1000 / 60 / 60
  const days = Math.floor(totalHours / 24)
  const hours = Math.round(totalHours % 24)
  if (days > 0) return `${days.toLocaleString()} days, ${hours} hours`
  return `${hours} hours`
}

function formatNumber(n: number): string {
  return n.toLocaleString()
}

const statCards = computed(() => [
  { label: 'Total Tracks', value: formatNumber(props.stats.total_tracks), icon: 'i-heroicons-musical-note' },
  { label: 'Total Artists', value: formatNumber(props.stats.total_artists), icon: 'i-heroicons-user-group' },
  { label: 'Total Albums', value: formatNumber(props.stats.total_albums), icon: 'i-heroicons-square-3-stack-3d' },
  { label: 'Total Playtime', value: formatPlaytime(props.stats.total_duration_ms), icon: 'i-heroicons-clock' },
  { label: 'Avg Track Length', value: formatDuration(props.stats.avg_duration_ms), icon: 'i-heroicons-bars-3-bottom-left' },
  { label: 'Median Track Length', value: formatDuration(props.stats.median_duration_ms), icon: 'i-heroicons-bars-3-center-left' },
  { label: 'Avg Tracks / Artist', value: String(props.stats.avg_tracks_per_artist), icon: 'i-heroicons-chart-bar' },
  { label: 'Avg Tracks / Album', value: String(props.stats.avg_tracks_per_album), icon: 'i-heroicons-rectangle-stack' },
  { label: 'Library Size', value: formatBytes(props.stats.total_file_size_bytes), icon: 'i-heroicons-circle-stack' },
  { label: 'Total Files', value: formatNumber(props.stats.total_files), icon: 'i-heroicons-document' },
])
</script>

<template>
  <ObservatorySection title="Collection Overview" description="High-level view of your music archive">
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      <div
        v-for="card in statCards"
        :key="card.label"
        class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4"
      >
        <div class="flex items-center gap-2 mb-2">
          <UIcon :name="card.icon" class="size-4 text-gray-400" />
          <span class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">{{ card.label }}</span>
        </div>
        <div class="text-xl font-bold text-gray-900 dark:text-white">
          {{ card.value }}
        </div>
      </div>
    </div>

    <!-- Insight callouts -->
    <div class="mt-4 flex flex-wrap gap-3">
      <div
        v-if="props.dominantDecade"
        class="bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg px-4 py-2 text-sm"
      >
        <span class="text-blue-700 dark:text-blue-300">
          {{ props.dominantDecade.percentage }}% of your library is from the {{ props.dominantDecade.decade }}s
        </span>
      </div>
      <div
        v-if="props.oldestYear && props.newestYear"
        class="bg-purple-50 dark:bg-purple-950/30 border border-purple-200 dark:border-purple-800 rounded-lg px-4 py-2 text-sm"
      >
        <span class="text-purple-700 dark:text-purple-300">
          Your collection spans {{ props.newestYear - props.oldestYear }} years ({{ props.oldestYear }}&ndash;{{ props.newestYear }})
        </span>
      </div>
    </div>
  </ObservatorySection>
</template>
