<script setup lang="ts">
import type { BpmEntry, KeyEntry, AudioAverages } from '~/types/observatory'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
import { TooltipComponent, GridComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, BarChart, PieChart, TooltipComponent, GridComponent, LegendComponent])

const props = defineProps<{
  bpmDistribution: BpmEntry[]
  keyDistribution: KeyEntry[]
  averages: AudioAverages | null
}>()

const colorMode = useColorMode()

const hasData = computed(() => props.bpmDistribution.length > 0 || props.keyDistribution.length > 0)

const bpmOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: { name: string, value: number }[]) => {
        const p = params[0]
        return `<b>${p.name} BPM</b><br/>${p.value.toLocaleString()} tracks`
      },
    },
    grid: { left: 50, right: 15, top: 10, bottom: 30 },
    xAxis: {
      type: 'category' as const,
      data: props.bpmDistribution.map(b => b.bpm),
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
        data: props.bpmDistribution.map(b => b.count),
        itemStyle: { color: '#f59e0b', borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 20,
      },
    ],
  }
})

const keyColors = [
  '#ef4444', '#f97316', '#f59e0b', '#eab308', '#84cc16', '#22c55e',
  '#10b981', '#14b8a6', '#06b6d4', '#0ea5e9', '#3b82f6', '#6366f1',
  '#8b5cf6', '#a855f7', '#d946ef', '#ec4899', '#f43f5e', '#6b7280',
]

const keyOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: { name: string, value: number, percent: number }) => {
        return `<b>${params.name}</b><br/>${params.value.toLocaleString()} tracks (${params.percent}%)`
      },
    },
    legend: {
      orient: 'vertical' as const,
      right: 5,
      top: 'center',
      textStyle: { color: isDark ? '#9ca3af' : '#4b5563', fontSize: 11 },
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 4,
          borderColor: isDark ? '#111827' : '#ffffff',
          borderWidth: 2,
        },
        label: { show: false },
        emphasis: {
          label: {
            show: true,
            fontSize: 13,
            fontWeight: 'bold',
            color: isDark ? '#fff' : '#111',
          },
        },
        data: props.keyDistribution.map((k, i) => ({
          value: k.count,
          name: k.key,
          itemStyle: { color: keyColors[i % keyColors.length] },
        })),
      },
    ],
  }
})
</script>

<template>
  <ObservatorySection title="Audio Features" description="BPM and key analysis from audio fingerprinting">
    <div v-if="!hasData" class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-6 text-center text-gray-500 dark:text-gray-400">
      No audio analysis data available yet. Run the audio analyzer to populate this section.
    </div>

    <template v-else>
      <!-- Averages summary -->
      <div v-if="averages" class="grid grid-cols-3 gap-3 mb-4">
        <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg px-4 py-3 text-center">
          <div class="text-2xl font-bold text-amber-500 tabular-nums">{{ Math.round(averages.avg_bpm) }}</div>
          <div class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Avg BPM</div>
        </div>
        <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg px-4 py-3 text-center">
          <div class="text-2xl font-bold text-cyan-500 tabular-nums">{{ averages.avg_spectral_centroid.toFixed(0) }} Hz</div>
          <div class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Avg Brightness</div>
        </div>
        <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg px-4 py-3 text-center">
          <div class="text-2xl font-bold text-emerald-500 tabular-nums">{{ averages.analyzed_count.toLocaleString() }}</div>
          <div class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Tracks Analyzed</div>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <!-- BPM distribution -->
        <div v-if="bpmDistribution.length > 0" class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
          <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
            BPM Distribution
          </h3>
          <VChart :option="bpmOption" style="height: 260px" autoresize />
        </div>

        <!-- Key distribution -->
        <div v-if="keyDistribution.length > 0" class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
          <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
            Key Distribution
          </h3>
          <VChart :option="keyOption" style="height: 260px" autoresize />
        </div>
      </div>
    </template>
  </ObservatorySection>
</template>
