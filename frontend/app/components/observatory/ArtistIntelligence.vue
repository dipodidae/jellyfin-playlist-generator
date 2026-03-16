<script setup lang="ts">
import type { ArtistCount, ArtistPlaytime, OneTrackArtists } from '~/types/observatory'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { TooltipComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, BarChart, TooltipComponent, GridComponent])

const props = defineProps<{
  byTracks: ArtistCount[]
  byPlaytime: ArtistPlaytime[]
  byAlbums: ArtistCount[]
  oneTrackArtists: OneTrackArtists
}>()

const colorMode = useColorMode()

type ArtistView = 'tracks' | 'playtime' | 'albums'
const viewMode = ref<ArtistView>('tracks')

const { formatDuration } = useDurationFormatter()

function formatHours(ms: number): string {
  const hours = ms / 1000 / 60 / 60
  if (hours >= 24) {
    const days = Math.floor(hours / 24)
    const rem = Math.round(hours % 24)
    return `${days}d ${rem}h`
  }
  return `${hours.toFixed(1)}h`
}

function buildBarOption(names: string[], values: number[], tooltipFormatter: (v: number) => string, color: string) {
  const isDark = colorMode.value === 'dark'
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: { name: string, value: number }[]) => {
        const p = params[0]
        return `<b>${p.name}</b><br/>${tooltipFormatter(p.value)}`
      },
    },
    grid: { left: 160, right: 30, top: 10, bottom: 20 },
    xAxis: {
      type: 'value' as const,
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280' },
      splitLine: { lineStyle: { color: isDark ? '#1f2937' : '#f3f4f6' } },
    },
    yAxis: {
      type: 'category' as const,
      data: [...names].reverse(),
      axisLabel: {
        color: isDark ? '#d1d5db' : '#374151',
        fontSize: 11,
        width: 140,
        overflow: 'truncate' as const,
      },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        type: 'bar',
        data: [...values].reverse(),
        itemStyle: {
          color,
          borderRadius: [0, 4, 4, 0],
        },
        barMaxWidth: 18,
      },
    ],
  }
}

const trackOption = computed(() =>
  buildBarOption(
    props.byTracks.map(a => a.name),
    props.byTracks.map(a => a.count),
    v => `${v.toLocaleString()} tracks`,
    '#3b82f6',
  ),
)

const playtimeOption = computed(() =>
  buildBarOption(
    props.byPlaytime.map(a => a.name),
    props.byPlaytime.map(a => a.duration_ms),
    v => formatHours(v),
    '#8b5cf6',
  ),
)

const albumOption = computed(() =>
  buildBarOption(
    props.byAlbums.map(a => a.name),
    props.byAlbums.map(a => a.count),
    v => `${v.toLocaleString()} albums`,
    '#10b981',
  ),
)

const currentOption = computed(() => {
  if (viewMode.value === 'playtime') return playtimeOption.value
  if (viewMode.value === 'albums') return albumOption.value
  return trackOption.value
})
</script>

<template>
  <ObservatorySection title="Artist Intelligence" description="Who dominates your collection?">
    <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
      <div class="flex items-center gap-2 mb-4">
        <button
          v-for="mode in (['tracks', 'playtime', 'albums'] as ArtistView[])"
          :key="mode"
          class="px-3 py-1 text-sm font-medium rounded-md transition-colors capitalize"
          :class="viewMode === mode
            ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300'
            : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'"
          @click="viewMode = mode"
        >
          By {{ mode }}
        </button>
      </div>
      <VChart :option="currentOption" :key="viewMode" style="height: 500px" autoresize />
    </div>

    <!-- One-track artists callout -->
    <div class="mt-4 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded-lg px-4 py-3">
      <span class="text-sm text-amber-700 dark:text-amber-300">
        <span class="font-bold">{{ oneTrackArtists.count.toLocaleString() }}</span> artists
        ({{ oneTrackArtists.percentage }}%) have only a single track in your library &mdash;
        compilation leftovers, forgotten discoveries, or one-off features.
      </span>
    </div>
  </ObservatorySection>
</template>
