<script setup lang="ts">
import type { ArchaeologyData } from '~/types/observatory'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { TooltipComponent, GridComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, BarChart, TooltipComponent, GridComponent, LegendComponent])

const props = defineProps<{ data: ArchaeologyData }>()

const colorMode = useColorMode()
const { formatDuration } = useDurationFormatter()

type TabView = 'forgotten' | 'compilations' | 'temporal'
const activeTab = ref<TabView>('forgotten')

// Temporal bias grouped bar chart
const temporalOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  const entries = props.data.temporal_bias.filter(e => e.decade >= 1950)

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: { seriesName: string; name: string; value: number }[]) => {
        let html = `<b>${params[0].name}s</b><br/>`
        for (const p of params) {
          html += `${p.seriesName}: ${p.value.toFixed(1)}%<br/>`
        }
        return html
      },
    },
    legend: {
      data: ['Library share', 'Playlist usage share'],
      textStyle: { color: isDark ? '#9ca3af' : '#4b5563' },
    },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: 'category' as const,
      data: entries.map(e => `${e.decade}`),
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280' },
    },
    yAxis: {
      type: 'value' as const,
      axisLabel: {
        color: isDark ? '#9ca3af' : '#6b7280',
        formatter: (v: number) => `${v}%`,
      },
      splitLine: { lineStyle: { color: isDark ? '#1f2937' : '#f3f4f6' } },
    },
    series: [
      {
        name: 'Library share',
        type: 'bar',
        data: entries.map(e => e.library_pct),
        itemStyle: { color: '#3b82f6', borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 20,
      },
      {
        name: 'Playlist usage share',
        type: 'bar',
        data: entries.map(e => e.usage_pct),
        itemStyle: { color: '#f59e0b', borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 20,
      },
    ],
  }
})

// Detect biggest nostalgia bias
const biggestBias = computed(() => {
  const biased = props.data.temporal_bias
    .filter(e => e.usage_pct > 0 && e.library_pct > 0)
    .map(e => ({
      decade: e.decade,
      diff: e.usage_pct - e.library_pct,
    }))
    .sort((a, b) => b.diff - a.diff)
  return biased.length > 0 ? biased[0] : null
})
</script>

<template>
  <ObservatorySection
    title="Collection Archaeology"
    description="Forgotten tracks, compilation culture, and listening nostalgia"
  >
    <!-- Tab buttons -->
    <div class="flex items-center gap-2 mb-4">
      <button
        v-for="tab in (['forgotten', 'compilations', 'temporal'] as TabView[])"
        :key="tab"
        class="px-3 py-1 text-sm font-medium rounded-md transition-colors"
        :class="activeTab === tab
          ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300'
          : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'"
        @click="activeTab = tab"
      >
        {{ tab === 'forgotten' ? 'Forgotten Tracks' : tab === 'compilations' ? 'Compilations' : 'Temporal Bias' }}
      </button>
    </div>

    <!-- Forgotten Tracks -->
    <div v-if="activeTab === 'forgotten'">
      <!-- Hero stat -->
      <div class="bg-gradient-to-r from-gray-900 to-gray-800 border border-gray-700 rounded-lg p-6 mb-4">
        <div class="flex items-baseline gap-3">
          <span class="text-4xl font-black text-amber-400 tabular-nums">
            {{ data.forgotten.forgotten_count.toLocaleString() }}
          </span>
          <span class="text-sm text-gray-400">
            forgotten tracks ({{ data.forgotten.forgotten_pct }}% of library)
          </span>
        </div>
        <p class="text-xs text-gray-500 mt-2">
          Tracks that exist in your archive but have never been selected for any generated playlist.
        </p>
      </div>

      <!-- Sample of forgotten tracks -->
      <div
        v-if="data.forgotten_sample.length > 0"
        class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4"
      >
        <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
          Random Forgotten Tracks
        </h3>
        <div class="space-y-1.5">
          <div
            v-for="(track, i) in data.forgotten_sample"
            :key="i"
            class="flex items-center justify-between text-sm py-1"
          >
            <div class="flex items-center gap-2 min-w-0">
              <span class="text-gray-900 dark:text-white font-medium truncate">{{ track.title }}</span>
              <span class="text-gray-400 dark:text-gray-500 text-xs truncate">&mdash; {{ track.artist }}</span>
            </div>
            <div class="flex items-center gap-3 shrink-0 ml-3">
              <span v-if="track.year" class="text-gray-400 text-xs tabular-nums">{{ track.year }}</span>
              <span class="text-gray-500 text-xs font-mono tabular-nums">{{ formatDuration(track.duration_ms) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Compilations -->
    <div v-if="activeTab === 'compilations'">
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <!-- Compilation stat -->
        <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
          <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
            Compilation Contamination
          </h3>
          <div class="flex items-baseline gap-2 mb-3">
            <span class="text-3xl font-bold text-gray-900 dark:text-white tabular-nums">
              {{ data.compilation.compilation_pct }}%
            </span>
            <span class="text-sm text-gray-500">compilation material</span>
          </div>
          <p class="text-xs text-gray-400">
            {{ data.compilation.compilation_tracks.toLocaleString() }} of {{ data.compilation.total_tracks.toLocaleString() }}
            tracks come from "Various Artists" albums.
          </p>
        </div>

        <!-- Artists discovered through compilations -->
        <div
          v-if="data.compilation_artists.length > 0"
          class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4"
        >
          <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
            Artists from Compilations
          </h3>
          <div class="space-y-1.5 max-h-72 overflow-y-auto">
            <div
              v-for="artist in data.compilation_artists"
              :key="artist.name"
              class="flex items-center justify-between text-sm py-1"
            >
              <span class="text-gray-900 dark:text-white font-medium truncate">{{ artist.name }}</span>
              <span class="text-gray-500 dark:text-gray-400 text-xs tabular-nums shrink-0 ml-3">
                {{ artist.track_count }} track{{ artist.track_count !== 1 ? 's' : '' }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Temporal Listening Bias -->
    <div v-if="activeTab === 'temporal'">
      <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
        <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
          Listening Nostalgia Bias
        </h3>
        <p class="text-xs text-gray-400 dark:text-gray-500 mb-3">
          Compare what decades your library contains vs what actually gets used in playlists
        </p>
        <VChart :option="temporalOption" style="height: 320px" autoresize />
      </div>

      <!-- Insight callout -->
      <div
        v-if="biggestBias && biggestBias.diff > 2"
        class="mt-4 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded-lg px-4 py-3"
      >
        <span class="text-sm text-amber-700 dark:text-amber-300">
          <span class="font-bold">{{ biggestBias.decade }}s music</span> is
          overrepresented in your playlists by
          <span class="font-bold">{{ biggestBias.diff.toFixed(1) }} percentage points</span>
          compared to its library share &mdash; your nostalgia decade.
        </span>
      </div>
    </div>
  </ObservatorySection>
</template>
