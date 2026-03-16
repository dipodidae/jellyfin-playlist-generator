<script setup lang="ts">
import type { FormatEntry } from '~/types/observatory'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, PieChart, TooltipComponent, LegendComponent])

const props = defineProps<{ formats: FormatEntry[] }>()

const colorMode = useColorMode()

const formatColors: Record<string, string> = {
  flac: '#10b981',
  mp3: '#3b82f6',
  m4a: '#f59e0b',
  opus: '#8b5cf6',
  ogg: '#ef4444',
  wav: '#06b6d4',
  aac: '#ec4899',
  wma: '#6b7280',
}

const option = computed(() => {
  const isDark = colorMode.value === 'dark'
  const total = props.formats.reduce((sum, f) => sum + f.count, 0)

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: { name: string, value: number, percent: number }) => {
        return `<b>${params.name.toUpperCase()}</b><br/>${params.value.toLocaleString()} files (${params.percent}%)`
      },
    },
    legend: {
      orient: 'vertical' as const,
      right: 10,
      top: 'center',
      textStyle: { color: isDark ? '#9ca3af' : '#4b5563' },
    },
    series: [
      {
        type: 'pie',
        radius: ['45%', '75%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 6,
          borderColor: isDark ? '#111827' : '#ffffff',
          borderWidth: 2,
        },
        label: { show: false },
        emphasis: {
          label: {
            show: true,
            fontSize: 14,
            fontWeight: 'bold',
            color: isDark ? '#fff' : '#111',
          },
        },
        data: props.formats.map(f => ({
          value: f.count,
          name: f.format.toUpperCase(),
          itemStyle: { color: formatColors[f.format] || '#6b7280' },
        })),
      },
    ],
  }
})
</script>

<template>
  <ObservatorySection title="Format Breakdown" description="Audio file format distribution">
    <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
      <VChart :option="option" style="height: 280px" autoresize />
    </div>
  </ObservatorySection>
</template>
