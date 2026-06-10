<script setup lang="ts">
import type { BpmEntry, KeyEntry, AudioAverages, VersionEntry } from '~/types/observatory'
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
  versionDistribution?: VersionEntry[]
}>()

const colorMode = useColorMode()

// Render a 0-1 metric as a whole-number percentage; em dash when absent.
function pct(v: number | null | undefined): string {
  return (v === null || v === undefined) ? '—' : `${Math.round(v * 100)}%`
}

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
      axisLabel: { color: isDark ? '#9a9aa3' : '#6b7280', fontSize: 10 },
      axisLine: { lineStyle: { color: isDark ? '#232327' : '#e5e7eb' } },
    },
    yAxis: {
      type: 'value' as const,
      axisLabel: { color: isDark ? '#9a9aa3' : '#6b7280', fontSize: 10 },
      splitLine: { lineStyle: { color: isDark ? '#1d1d21' : '#f3f4f6' } },
    },
    series: [
      {
        type: 'bar',
        data: props.bpmDistribution.map(b => b.count),
        itemStyle: { color: '#c8ff4d', borderRadius: [3, 3, 0, 0] },
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
      textStyle: { color: isDark ? '#9a9aa3' : '#4b5563', fontSize: 11 },
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 4,
          borderColor: isDark ? '#0f0f11' : '#ffffff',
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

const avgTiles = computed(() => {
  if (!props.averages) return []
  return [
    { label: 'Avg BPM', value: String(Math.round(props.averages.avg_bpm)), color: 'text-acid-300' },
    { label: 'Avg Brightness', value: `${props.averages.avg_spectral_centroid.toFixed(0)} Hz`, color: 'text-[#59c1ff]' },
    { label: 'Tracks Analyzed', value: props.averages.analyzed_count.toLocaleString(), color: 'text-[#6fe3c0]' },
  ]
})

const v2Tiles = computed(() => {
  if (!props.averages || (props.averages.metrics_v2_count ?? 0) === 0) return []
  return [
    { label: 'Avg Valence (mood)', value: pct(props.averages.avg_valence), color: 'text-pink-400' },
    { label: 'Avg Danceability', value: pct(props.averages.avg_danceability), color: 'text-[#a78bfa]' },
    { label: 'Avg Acousticness', value: pct(props.averages.avg_acousticness), color: 'text-[#6fe3c0]' },
    { label: 'Avg Instrumentalness', value: pct(props.averages.avg_instrumentalness), color: 'text-[#59c1ff]' },
  ]
})
</script>

<template>
  <ObservatorySection title="Audio Features" description="BPM and key analysis from audio fingerprinting">
    <div
      v-if="!hasData"
      class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-6 text-center text-muted"
    >
      No audio analysis data available yet. Run the audio analyzer to populate this section.
    </div>

    <template v-else>
      <!-- Averages summary -->
      <div v-if="averages" class="grid grid-cols-3 gap-3 mb-4">
        <div
          v-for="tile in avgTiles"
          :key="tile.label"
          class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl px-4 py-3 text-center"
        >
          <div class="text-2xl font-bold font-display tabular" :class="tile.color">{{ tile.value }}</div>
          <div class="text-[10px] text-dimmed mt-0.5 uppercase tracking-widest">{{ tile.label }}</div>
        </div>
      </div>

      <!-- More-metrics averages (valence / danceability / acousticness / instrumentalness) -->
      <div
        v-if="v2Tiles.length > 0"
        class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4"
      >
        <div
          v-for="tile in v2Tiles"
          :key="tile.label"
          class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl px-4 py-3 text-center"
        >
          <div class="text-2xl font-bold font-display tabular" :class="tile.color">{{ tile.value }}</div>
          <div class="text-[10px] text-dimmed mt-0.5 uppercase tracking-widest">{{ tile.label }}</div>
        </div>
      </div>

      <!-- Studio vs live/demo/bonus version breakdown -->
      <div
        v-if="versionDistribution && versionDistribution.length > 0"
        class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4 mb-4"
      >
        <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-3">
          Version Breakdown (studio / live / demo / …)
        </h3>
        <div class="flex flex-wrap gap-2">
          <UBadge
            v-for="v in versionDistribution"
            :key="v.version_type"
            variant="soft"
            color="neutral"
            size="sm"
          >
            {{ v.version_type }}: <span class="tabular font-bold ml-1">{{ v.count.toLocaleString() }}</span>
          </UBadge>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <!-- BPM distribution -->
        <div v-if="bpmDistribution.length > 0" class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4">
          <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-3">
            BPM Distribution
          </h3>
          <VChart :option="bpmOption" style="height: 260px" autoresize />
        </div>

        <!-- Key distribution -->
        <div v-if="keyDistribution.length > 0" class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4">
          <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-3">
            Key Distribution
          </h3>
          <VChart :option="keyOption" style="height: 260px" autoresize />
        </div>
      </div>
    </template>
  </ObservatorySection>
</template>
