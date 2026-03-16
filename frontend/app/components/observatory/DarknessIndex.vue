<script setup lang="ts">
import type { DarknessIndexData } from '~/types/observatory'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
import { TooltipComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, BarChart, PieChart, TooltipComponent, GridComponent])

const props = defineProps<{ data: DarknessIndexData }>()

const colorMode = useColorMode()

// Keyword bar chart
const keywordOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  const keywords = props.data.keyword_counts.slice(0, 20)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: { name: string; value: number }[]) => {
        return `<b>"${params[0].name}"</b> appears in ${params[0].value.toLocaleString()} track titles`
      },
    },
    grid: { left: 90, right: 30, top: 10, bottom: 20 },
    xAxis: {
      type: 'value' as const,
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280' },
      splitLine: { lineStyle: { color: isDark ? '#1f2937' : '#f3f4f6' } },
    },
    yAxis: {
      type: 'category' as const,
      data: [...keywords].reverse().map(k => k.word),
      axisLabel: {
        color: isDark ? '#d1d5db' : '#374151',
        fontSize: 11,
      },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        type: 'bar',
        data: [...keywords].reverse().map(k => k.count),
        itemStyle: {
          color: '#dc2626',
          borderRadius: [0, 4, 4, 0],
        },
        barMaxWidth: 16,
      },
    ],
  }
})

// Profile darkness distribution donut
const profileOption = computed(() => {
  const dist = props.data.profile_distribution
  if (!dist) return null
  const isDark = colorMode.value === 'dark'

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: { name: string; value: number; percent: number }) => {
        return `<b>${params.name}</b><br/>${params.value.toLocaleString()} tracks (${params.percent}%)`
      },
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['50%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 6,
          borderColor: isDark ? '#111827' : '#ffffff',
          borderWidth: 2,
        },
        label: {
          show: true,
          color: isDark ? '#d1d5db' : '#374151',
          fontSize: 11,
        },
        data: [
          { value: dist.very_dark, name: 'Very Dark', itemStyle: { color: '#450a0a' } },
          { value: dist.dark, name: 'Dark', itemStyle: { color: '#991b1b' } },
          { value: dist.neutral, name: 'Neutral', itemStyle: { color: '#6b7280' } },
          { value: dist.light, name: 'Light', itemStyle: { color: '#60a5fa' } },
          { value: dist.very_light, name: 'Very Light', itemStyle: { color: '#bfdbfe' } },
        ],
      },
    ],
  }
})
</script>

<template>
  <ObservatorySection
    title="Darkness Index"
    description="How dark is your musical soul?"
  >
    <!-- Hero stat -->
    <div class="bg-gradient-to-r from-red-950 to-gray-900 border border-red-900/50 rounded-lg p-6 mb-4">
      <div class="flex items-baseline gap-3">
        <span class="text-4xl font-black text-red-400 tabular-nums">
          {{ data.total_dark_title_tracks.toLocaleString() }}
        </span>
        <span class="text-sm text-red-300/70">
          darkness-coded tracks ({{ data.dark_title_pct }}% of library)
        </span>
      </div>
      <p class="text-xs text-gray-500 mt-2">
        Tracks containing words like death, black, blood, doom, evil, night, shadow...
      </p>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- Keyword breakdown -->
      <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
        <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
          Dark Keywords in Titles
        </h3>
        <VChart :option="keywordOption" style="height: 400px" autoresize />
      </div>

      <!-- Profile-based darkness -->
      <div class="space-y-4">
        <div
          v-if="data.profile_distribution"
          class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4"
        >
          <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
            Semantic Darkness Profile
          </h3>
          <p class="text-xs text-gray-400 dark:text-gray-500 mb-3">
            Based on AI-computed darkness scores (0-1 scale). Average: <span class="font-bold text-red-400">{{ data.profile_distribution.avg_darkness.toFixed(2) }}</span>
          </p>
          <VChart v-if="profileOption" :option="profileOption" style="height: 220px" autoresize />
        </div>

        <!-- Darkest artists -->
        <div
          v-if="data.darkest_artists.length > 0"
          class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4"
        >
          <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
            Darkest Artists
          </h3>
          <div class="space-y-1.5 max-h-72 overflow-y-auto">
            <div
              v-for="(artist, i) in data.darkest_artists"
              :key="artist.name"
              class="flex items-center justify-between text-sm py-1"
            >
              <div class="flex items-center gap-2 min-w-0">
                <span class="text-gray-400 dark:text-gray-600 w-5 text-right tabular-nums shrink-0">{{ i + 1 }}</span>
                <span class="text-gray-900 dark:text-white font-medium truncate">{{ artist.name }}</span>
              </div>
              <div class="flex items-center gap-3 shrink-0 ml-3">
                <div class="w-20 bg-gray-100 dark:bg-gray-800 rounded-full h-1.5">
                  <div
                    class="bg-red-600 h-1.5 rounded-full"
                    :style="{ width: `${artist.avg_darkness * 100}%` }"
                  />
                </div>
                <span class="text-xs text-gray-500 tabular-nums w-8 text-right">{{ artist.avg_darkness.toFixed(2) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </ObservatorySection>
</template>
