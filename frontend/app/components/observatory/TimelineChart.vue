<script setup lang="ts">
import type { DecadeEntry, YearEntry, TrackRef } from '~/types/observatory'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { TooltipComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, BarChart, TooltipComponent, GridComponent])

const props = defineProps<{
  decades: DecadeEntry[]
  years: YearEntry[]
  oldestTracks: TrackRef[]
  newestTracks: TrackRef[]
}>()

const colorMode = useColorMode()
const viewMode = ref<'decades' | 'years'>('decades')

const decadeOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: { name: string, value: number }[]) => {
        const p = params[0]
        return `<b>${p.name}s</b><br/>${p.value.toLocaleString()} tracks`
      },
    },
    grid: { left: 60, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'category' as const,
      data: props.decades.map(d => String(d.decade)),
      axisLabel: {
        color: isDark ? '#9a9aa3' : '#6b7280',
        formatter: (v: string) => `${v}s`,
      },
      axisLine: { lineStyle: { color: isDark ? '#232327' : '#e5e7eb' } },
    },
    yAxis: {
      type: 'value' as const,
      axisLabel: { color: isDark ? '#9a9aa3' : '#6b7280' },
      splitLine: { lineStyle: { color: isDark ? '#1d1d21' : '#f3f4f6' } },
    },
    series: [
      {
        type: 'bar',
        data: props.decades.map(d => d.count),
        itemStyle: {
          color: {
            type: 'linear' as const,
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: '#c8ff4d' },
              { offset: 1, color: '#7a3df0' },
            ],
          },
          borderRadius: [4, 4, 0, 0],
        },
        barMaxWidth: 50,
      },
    ],
  }
})

const yearOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: { name: string, value: number }[]) => {
        const p = params[0]
        return `<b>${p.name}</b><br/>${p.value.toLocaleString()} tracks`
      },
    },
    grid: { left: 60, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'category' as const,
      data: props.years.map(y => String(y.year)),
      axisLabel: {
        color: isDark ? '#9a9aa3' : '#6b7280',
        interval: 'auto' as const,
        rotate: 45,
      },
      axisLine: { lineStyle: { color: isDark ? '#232327' : '#e5e7eb' } },
    },
    yAxis: {
      type: 'value' as const,
      axisLabel: { color: isDark ? '#9a9aa3' : '#6b7280' },
      splitLine: { lineStyle: { color: isDark ? '#1d1d21' : '#f3f4f6' } },
    },
    series: [
      {
        type: 'bar',
        data: props.years.map(y => y.count),
        itemStyle: {
          color: '#c8ff4d',
          borderRadius: [2, 2, 0, 0],
        },
        barMaxWidth: 12,
      },
    ],
  }
})
</script>

<template>
  <ObservatorySection title="Release Timeline" description="When was your music recorded?">
    <div class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4">
      <!-- View switcher -->
      <div class="flex items-center gap-1.5 mb-4">
        <button
          class="px-3 py-1 text-sm font-medium rounded-lg transition-colors"
          :class="viewMode === 'decades'
            ? 'bg-acid-400/10 text-acid-300 ring-1 ring-acid-400/30'
            : 'text-muted hover:text-highlighted'"
          @click="viewMode = 'decades'"
        >
          By Decade
        </button>
        <button
          class="px-3 py-1 text-sm font-medium rounded-lg transition-colors"
          :class="viewMode === 'years'
            ? 'bg-acid-400/10 text-acid-300 ring-1 ring-acid-400/30'
            : 'text-muted hover:text-highlighted'"
          @click="viewMode = 'years'"
        >
          By Year
        </button>
      </div>
      <VChart
        :option="viewMode === 'decades' ? decadeOption : yearOption"
        :key="viewMode"
        style="height: 300px"
        autoresize
      />
    </div>

    <!-- Oldest / Newest tracks callout -->
    <div class="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div
        v-if="oldestTracks.length"
        class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4"
      >
        <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-3">Oldest Recordings</h3>
        <div v-for="track in oldestTracks" :key="track.title + track.artist" class="text-sm mb-1.5">
          <span class="text-highlighted font-medium">{{ track.title }}</span>
          <span class="text-muted"> &mdash; {{ track.artist }}</span>
          <span class="text-acid-400/60 tabular"> ({{ track.year }})</span>
        </div>
      </div>
      <div
        v-if="newestTracks.length"
        class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4"
      >
        <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-3">Newest Recordings</h3>
        <div v-for="track in newestTracks" :key="track.title + track.artist" class="text-sm mb-1.5">
          <span class="text-highlighted font-medium">{{ track.title }}</span>
          <span class="text-muted"> &mdash; {{ track.artist }}</span>
          <span class="text-acid-400/60 tabular"> ({{ track.year }})</span>
        </div>
      </div>
    </div>
  </ObservatorySection>
</template>
