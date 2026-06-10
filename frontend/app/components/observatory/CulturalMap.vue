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
      axisLabel: { color: isDark ? '#9a9aa3' : '#6b7280' },
      splitLine: { lineStyle: { color: isDark ? '#1d1d21' : '#f3f4f6' } },
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
          color: '#7a3df0',
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
      textStyle: { color: isDark ? '#9a9aa3' : '#4b5563' },
    },
    series: [
      {
        type: 'pie',
        radius: ['45%', '75%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 6,
          borderColor: isDark ? '#0f0f11' : '#ffffff',
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
          { value: p.pure, name: 'Pure genre (1 tag)', itemStyle: { color: '#6fe3c0' } },
          { value: p.hybrid, name: 'Hybrid (2-3 tags)', itemStyle: { color: '#59c1ff' } },
          { value: p.highly_hybrid, name: 'Highly hybrid (4+)', itemStyle: { color: '#c8ff4d' } },
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
    <div class="flex items-center gap-1.5 mb-4">
      <button
        v-for="tab in (['gravity', 'evolution', 'purity'] as TabView[])"
        :key="tab"
        class="px-3 py-1 text-sm font-medium rounded-lg transition-colors"
        :class="activeTab === tab
          ? 'bg-acid-400/10 text-acid-300 ring-1 ring-acid-400/30'
          : 'text-muted hover:text-highlighted'"
        @click="activeTab = tab"
      >
        {{ tab === 'gravity' ? 'Cultural Gravity' : tab === 'evolution' ? 'Tag Evolution' : 'Genre Purity' }}
      </button>
    </div>

    <!-- Cultural Gravity -->
    <div
      v-if="activeTab === 'gravity'"
      class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4"
    >
      <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-1">Unique Artists per Genre</h3>
      <p class="text-xs text-dimmed mb-3">Which genres dominate your artist pool (not just track count)</p>
      <VChart :option="gravityOption" style="height: 600px" autoresize />
    </div>

    <!-- Tag Evolution Timeline -->
    <div
      v-if="activeTab === 'evolution'"
      class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4"
    >
      <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-1">Genre Timeline</h3>
      <p class="text-xs text-dimmed mb-4">How genres appear across the decades in your collection</p>
      <div class="space-y-4">
        <div
          v-for="entry in data.tag_evolution"
          :key="entry.decade"
          class="flex items-start gap-4"
        >
          <div class="text-sm font-bold font-display text-acid-300 w-12 shrink-0 pt-0.5 tabular">
            {{ entry.decade }}s
          </div>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="tag in entry.tags"
              :key="tag.tag"
              class="inline-flex items-center gap-1 bg-[#7a3df0]/12 text-[#c084fc] ring-1 ring-[#7a3df0]/25 text-xs px-2.5 py-1 rounded-full"
            >
              {{ tag.tag }}
              <span class="text-[#7a3df0]/70 text-[10px]">{{ tag.artist_count }}</span>
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Genre Purity -->
    <div
      v-if="activeTab === 'purity'"
      class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4"
    >
      <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-1">Genre Purity vs Hybridization</h3>
      <p class="text-xs text-dimmed mb-3">How many tags does each artist carry?</p>
      <VChart :option="purityOption" style="height: 280px" autoresize />

      <!-- Summary callout -->
      <div class="mt-4 grid grid-cols-3 gap-3">
        <div class="text-center p-3 bg-[#6fe3c0]/8 border border-[#6fe3c0]/20 rounded-xl">
          <div class="text-2xl font-bold font-display tabular text-[#6fe3c0]">{{ data.genre_purity.pure_pct }}%</div>
          <div class="text-[10px] text-dimmed mt-1 uppercase tracking-widest">Pure genre</div>
        </div>
        <div class="text-center p-3 bg-[#59c1ff]/8 border border-[#59c1ff]/20 rounded-xl">
          <div class="text-2xl font-bold font-display tabular text-[#59c1ff]">{{ data.genre_purity.hybrid_pct }}%</div>
          <div class="text-[10px] text-dimmed mt-1 uppercase tracking-widest">Hybrid</div>
        </div>
        <div class="text-center p-3 bg-acid-400/8 border border-acid-400/20 rounded-xl">
          <div class="text-2xl font-bold font-display tabular text-acid-300">{{ data.genre_purity.highly_hybrid_pct }}%</div>
          <div class="text-[10px] text-dimmed mt-1 uppercase tracking-widest">Highly hybrid</div>
        </div>
      </div>
    </div>
  </ObservatorySection>
</template>
