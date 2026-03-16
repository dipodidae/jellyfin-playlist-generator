<script setup lang="ts">
import type { TagEntry, RareTag, TagPair } from '~/types/observatory'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { TreemapChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, TreemapChart, TooltipComponent])

const props = defineProps<{
  topTags: TagEntry[]
  rareTags: RareTag[]
  tagPairs: TagPair[]
}>()

const colorMode = useColorMode()

const treemapOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  const colors = [
    '#6d28d9', '#7c3aed', '#8b5cf6', '#a78bfa',
    '#2563eb', '#3b82f6', '#60a5fa',
    '#059669', '#10b981', '#34d399',
    '#d97706', '#f59e0b', '#fbbf24',
    '#dc2626', '#ef4444', '#f87171',
    '#db2777', '#ec4899',
    '#0891b2', '#06b6d4',
  ]

  return {
    tooltip: {
      formatter: (params: { name: string, value: number, data: { artistCount: number } }) => {
        return `<b>${params.name}</b><br/>${params.value.toLocaleString()} tracks<br/>${params.data.artistCount} artists`
      },
    },
    series: [
      {
        type: 'treemap',
        data: props.topTags.map((t, i) => ({
          name: t.name,
          value: t.track_count,
          artistCount: t.artist_count,
          itemStyle: { color: colors[i % colors.length] },
        })),
        label: {
          show: true,
          formatter: '{b}',
          fontSize: 11,
          color: '#fff',
          textShadowBlur: 2,
          textShadowColor: 'rgba(0,0,0,0.5)',
        },
        breadcrumb: { show: false },
        itemStyle: {
          borderColor: isDark ? '#111827' : '#ffffff',
          borderWidth: 2,
          gapWidth: 2,
        },
        levels: [
          {
            itemStyle: {
              borderColor: isDark ? '#111827' : '#ffffff',
              borderWidth: 3,
              gapWidth: 3,
            },
          },
        ],
      },
    ],
  }
})
</script>

<template>
  <ObservatorySection title="Tag Intelligence" description="Last.fm tag analysis across your collection">
    <!-- Treemap -->
    <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
      <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
        Top 50 Tags
      </h3>
      <VChart :option="treemapOption" style="height: 400px" autoresize />
    </div>

    <div class="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- Tag co-occurrence -->
      <div
        v-if="tagPairs.length"
        class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4"
      >
        <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
          Tag Co-occurrence
        </h3>
        <div class="space-y-1.5 max-h-80 overflow-y-auto">
          <div
            v-for="pair in tagPairs"
            :key="pair.tag1 + pair.tag2"
            class="flex items-center justify-between text-sm py-1"
          >
            <span class="text-gray-900 dark:text-white">
              <span class="font-medium">{{ pair.tag1 }}</span>
              <span class="text-gray-400 mx-1">+</span>
              <span class="font-medium">{{ pair.tag2 }}</span>
            </span>
            <span class="text-gray-500 dark:text-gray-400 text-xs tabular-nums ml-3 shrink-0">{{ pair.shared_artists }} artists</span>
          </div>
        </div>
      </div>

      <!-- Rare tags -->
      <div
        v-if="rareTags.length"
        class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4"
      >
        <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
          Rare Finds
        </h3>
        <p class="text-xs text-gray-400 mb-3">Tags used by only 1&ndash;3 artists</p>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="tag in rareTags"
            :key="tag.name"
            class="inline-block bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 text-xs px-2.5 py-1 rounded-full"
          >
            {{ tag.name }}
            <span class="text-gray-400 dark:text-gray-500 ml-0.5">({{ tag.artist_count }})</span>
          </span>
        </div>
      </div>
    </div>
  </ObservatorySection>
</template>
