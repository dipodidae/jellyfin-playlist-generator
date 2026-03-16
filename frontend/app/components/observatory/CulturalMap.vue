<script setup lang="ts">
import type { CulturalMapData } from '~/types/observatory'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
import { TooltipComponent, GridComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, BarChart, PieChart, TooltipComponent, GridComponent, LegendComponent])

const props = defineProps<{ data: CulturalMapData }>()

const colorMode = useColorMode()

type TabView = 'gravity' | 'evolution' | 'purity'
const activeTab = ref<TabView>('gravity')

// Cultural gravity: horizontal bar chart of unique artists per tag
const gravityOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  const tags = props.data.cultural_gravity.slice(0, 30)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: { name: string; value: number }[]) => {
        return `<b>${params[0].name}</b><br/>${params[0].value.toLocaleString()} artists`
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
      data: [...tags].reverse().map(t => t.tag),
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
        data: [...tags].reverse().map(t => t.artist_count),
        itemStyle: {
          color: '#8b5cf6',
          borderRadius: [0, 4, 4, 0],
        },
        barMaxWidth: 16,
      },
    ],
  }
})

// Genre purity donut chart
const purityOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  const p = props.data.genre_purity

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: { name: string; value: number; percent: number }) => {
        return `<b>${params.name}</b><br/>${params.value.toLocaleString()} artists (${params.percent}%)`
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
        data: [
          { value: p.pure, name: 'Pure genre (1 tag)', itemStyle: { color: '#10b981' } },
          { value: p.hybrid, name: 'Hybrid (2-3 tags)', itemStyle: { color: '#3b82f6' } },
          { value: p.highly_hybrid, name: 'Highly hybrid (4+)', itemStyle: { color: '#f59e0b' } },
        ],
      },
    ],
  }
})
</script>

<template>
  <ObservatorySection
    title="Cultural Map"
    description="Genre gravity, tag evolution, and artistic hybridization"
  >
    <!-- Tab buttons -->
    <div class="flex items-center gap-2 mb-4">
      <button
        v-for="tab in (['gravity', 'evolution', 'purity'] as TabView[])"
        :key="tab"
        class="px-3 py-1 text-sm font-medium rounded-md transition-colors capitalize"
        :class="activeTab === tab
          ? 'bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300'
          : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'"
        @click="activeTab = tab"
      >
        {{ tab === 'gravity' ? 'Cultural Gravity' : tab === 'evolution' ? 'Tag Evolution' : 'Genre Purity' }}
      </button>
    </div>

    <!-- Cultural Gravity -->
    <div
      v-if="activeTab === 'gravity'"
      class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4"
    >
      <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
        Unique Artists per Genre
      </h3>
      <p class="text-xs text-gray-400 dark:text-gray-500 mb-3">
        Which genres dominate your artist pool (not just track count)
      </p>
      <VChart :option="gravityOption" style="height: 600px" autoresize />
    </div>

    <!-- Tag Evolution Timeline -->
    <div
      v-if="activeTab === 'evolution'"
      class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4"
    >
      <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
        Genre Timeline
      </h3>
      <p class="text-xs text-gray-400 dark:text-gray-500 mb-4">
        How genres appear across the decades in your collection
      </p>
      <div class="space-y-4">
        <div
          v-for="entry in data.tag_evolution"
          :key="entry.decade"
          class="flex items-start gap-4"
        >
          <div class="text-sm font-bold text-gray-900 dark:text-white w-12 shrink-0 pt-0.5 tabular-nums">
            {{ entry.decade }}s
          </div>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="tag in entry.tags"
              :key="tag.tag"
              class="inline-flex items-center gap-1 bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 text-xs px-2.5 py-1 rounded-full"
            >
              {{ tag.tag }}
              <span class="text-violet-400 dark:text-violet-500 text-[10px]">{{ tag.artist_count }}</span>
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Genre Purity -->
    <div
      v-if="activeTab === 'purity'"
      class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4"
    >
      <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
        Genre Purity vs Hybridization
      </h3>
      <p class="text-xs text-gray-400 dark:text-gray-500 mb-3">
        How many tags does each artist carry?
      </p>
      <VChart :option="purityOption" style="height: 280px" autoresize />

      <!-- Summary callout -->
      <div class="mt-4 grid grid-cols-3 gap-3">
        <div class="text-center p-3 bg-emerald-50 dark:bg-emerald-950/30 rounded-lg">
          <div class="text-2xl font-bold text-emerald-600 dark:text-emerald-400">{{ data.genre_purity.pure_pct }}%</div>
          <div class="text-xs text-gray-500 dark:text-gray-400 mt-1">Pure genre</div>
        </div>
        <div class="text-center p-3 bg-blue-50 dark:bg-blue-950/30 rounded-lg">
          <div class="text-2xl font-bold text-blue-600 dark:text-blue-400">{{ data.genre_purity.hybrid_pct }}%</div>
          <div class="text-xs text-gray-500 dark:text-gray-400 mt-1">Hybrid</div>
        </div>
        <div class="text-center p-3 bg-amber-50 dark:bg-amber-950/30 rounded-lg">
          <div class="text-2xl font-bold text-amber-600 dark:text-amber-400">{{ data.genre_purity.highly_hybrid_pct }}%</div>
          <div class="text-xs text-gray-500 dark:text-gray-400 mt-1">Highly hybrid</div>
        </div>
      </div>
    </div>
  </ObservatorySection>
</template>
