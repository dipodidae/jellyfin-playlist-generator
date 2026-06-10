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
  { label: 'Total Tracks', value: formatNumber(props.stats.total_tracks), icon: 'i-lucide-music' },
  { label: 'Total Artists', value: formatNumber(props.stats.total_artists), icon: 'i-lucide-users' },
  { label: 'Total Albums', value: formatNumber(props.stats.total_albums), icon: 'i-lucide-disc-3' },
  { label: 'Total Playtime', value: formatPlaytime(props.stats.total_duration_ms), icon: 'i-lucide-clock' },
  { label: 'Avg Track Length', value: formatDuration(props.stats.avg_duration_ms), icon: 'i-lucide-align-left' },
  { label: 'Median Track Length', value: formatDuration(props.stats.median_duration_ms), icon: 'i-lucide-align-center' },
  { label: 'Avg Tracks / Artist', value: String(props.stats.avg_tracks_per_artist), icon: 'i-lucide-bar-chart-2' },
  { label: 'Avg Tracks / Album', value: String(props.stats.avg_tracks_per_album), icon: 'i-lucide-layers' },
  { label: 'Library Size', value: formatBytes(props.stats.total_file_size_bytes), icon: 'i-lucide-database' },
  { label: 'Total Files', value: formatNumber(props.stats.total_files), icon: 'i-lucide-file-audio' },
])
</script>

<template>
  <ObservatorySection title="Collection Overview" description="High-level view of your music archive">
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      <div
        v-for="card in statCards"
        :key="card.label"
        class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4 hover:border-acid-400/30 transition-colors"
      >
        <div class="flex items-center gap-1.5 mb-2">
          <UIcon :name="card.icon" class="size-3.5 text-acid-400/70 shrink-0" />
          <span class="text-[10px] font-medium text-dimmed uppercase tracking-widest truncate">{{ card.label }}</span>
        </div>
        <div class="text-xl font-bold font-display tabular text-highlighted">
          {{ card.value }}
        </div>
      </div>
    </div>

    <!-- Insight callouts -->
    <div class="mt-4 flex flex-wrap gap-3">
      <div
        v-if="props.dominantDecade"
        class="bg-acid-400/8 border border-acid-400/20 rounded-lg px-4 py-2 text-sm"
      >
        <span class="text-acid-300">
          <span class="font-semibold">{{ props.dominantDecade.percentage }}%</span> of your library is from the {{ props.dominantDecade.decade }}s
        </span>
      </div>
      <div
        v-if="props.oldestYear && props.newestYear"
        class="bg-[#7a3df0]/8 border border-[#7a3df0]/25 rounded-lg px-4 py-2 text-sm"
      >
        <span class="text-[#a78bfa]">
          Your collection spans <span class="font-semibold">{{ props.newestYear - props.oldestYear }} years</span>
          ({{ props.oldestYear }}&ndash;{{ props.newestYear }})
        </span>
      </div>
    </div>
  </ObservatorySection>
</template>
