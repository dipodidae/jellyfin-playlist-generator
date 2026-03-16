<script setup lang="ts">
import type { ProfileAverages, ProfileDistributions } from '~/types/observatory'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { RadarChart, BarChart } from 'echarts/charts'
import { TooltipComponent, RadarComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, RadarChart, BarChart, TooltipComponent, RadarComponent, GridComponent])

const props = defineProps<{
  averages: ProfileAverages
  distributions: ProfileDistributions
}>()

const colorMode = useColorMode()

const radarOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  return {
    tooltip: {},
    radar: {
      indicator: [
        { name: 'Energy', max: 1 },
        { name: 'Darkness', max: 1 },
        { name: 'Tempo', max: 1 },
        { name: 'Texture', max: 1 },
      ],
      axisName: {
        color: isDark ? '#d1d5db' : '#374151',
        fontSize: 13,
        fontWeight: 'bold' as const,
      },
      splitArea: {
        areaStyle: { color: isDark ? ['#111827', '#1f2937'] : ['#f9fafb', '#f3f4f6'] },
      },
      splitLine: { lineStyle: { color: isDark ? '#374151' : '#e5e7eb' } },
      axisLine: { lineStyle: { color: isDark ? '#374151' : '#e5e7eb' } },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: [
              props.averages.energy,
              props.averages.darkness,
              props.averages.tempo,
              props.averages.texture,
            ],
            name: 'Collection Average',
            areaStyle: { color: 'rgba(139, 92, 246, 0.25)' },
            lineStyle: { color: '#8b5cf6', width: 2 },
            itemStyle: { color: '#8b5cf6' },
          },
        ],
      },
    ],
  }
})

const dimColors: Record<string, string> = {
  energy: '#ef4444',
  darkness: '#6d28d9',
  tempo: '#f59e0b',
  texture: '#10b981',
}

function buildHistogramOption(dimension: string) {
  const isDark = colorMode.value === 'dark'
  const bins = props.distributions[dimension as keyof ProfileDistributions]
  const color = dimColors[dimension] || '#6b7280'

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: { name: string, value: number }[]) => {
        const p = params[0]
        return `<b>${p.name}</b><br/>${p.value.toLocaleString()} tracks`
      },
    },
    grid: { left: 45, right: 10, top: 5, bottom: 25 },
    xAxis: {
      type: 'category' as const,
      data: bins.map(b => b.label),
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280', fontSize: 10 },
      axisLine: { lineStyle: { color: isDark ? '#374151' : '#e5e7eb' } },
    },
    yAxis: {
      type: 'value' as const,
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280', fontSize: 10 },
      splitLine: { lineStyle: { color: isDark ? '#1f2937' : '#f3f4f6' } },
    },
    series: [
      {
        type: 'bar',
        data: bins.map(b => b.count),
        itemStyle: { color, borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 30,
      },
    ],
  }
}

// Taste insight
const tasteInsight = computed(() => {
  const a = props.averages
  const insights: string[] = []

  if (a.darkness > 0.6) insights.push('heavy darkness')
  else if (a.darkness < 0.3) insights.push('bright tones')

  if (a.energy > 0.6) insights.push('high energy')
  else if (a.energy < 0.3) insights.push('low energy')

  if (a.tempo > 0.6) insights.push('fast tempos')
  else if (a.tempo < 0.3) insights.push('slow tempos')

  if (a.texture > 0.6) insights.push('dense textures')
  else if (a.texture < 0.3) insights.push('sparse textures')

  if (insights.length === 0) return 'Your collection is well-balanced across all dimensions.'
  return `Your collection leans toward ${insights.join(', ')}.`
})
</script>

<template>
  <ObservatorySection title="Taste Fingerprint" :description="`4D profile analysis across ${averages.count.toLocaleString()} profiled tracks`">
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- Radar chart -->
      <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
        <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
          Collection Fingerprint
        </h3>
        <VChart :option="radarOption" style="height: 300px" autoresize />
        <p class="text-sm text-gray-600 dark:text-gray-400 text-center mt-2">
          {{ tasteInsight }}
        </p>
      </div>

      <!-- Dimension distributions -->
      <div class="space-y-3">
        <div
          v-for="dim in ['energy', 'darkness', 'tempo', 'texture']"
          :key="dim"
          class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-3"
        >
          <div class="flex items-center justify-between mb-1">
            <h4 class="text-xs font-semibold uppercase tracking-wider capitalize" :style="{ color: dimColors[dim] }">
              {{ dim }}
            </h4>
            <span class="text-xs text-gray-500 dark:text-gray-400 tabular-nums">
              avg: {{ averages[dim as keyof typeof averages] }}
            </span>
          </div>
          <VChart :option="buildHistogramOption(dim)" style="height: 100px" autoresize />
        </div>
      </div>
    </div>
  </ObservatorySection>
</template>
