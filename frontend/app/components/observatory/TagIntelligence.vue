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
          borderColor: isDark ? '#0f0f11' : '#ffffff',
          borderWidth: 2,
          gapWidth: 2,
        },
        levels: [
          {
            itemStyle: {
              borderColor: isDark ? '#0f0f11' : '#ffffff',
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
    <div class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4">
      <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-3">Top 50 Tags</h3>
      <VChart :option="treemapOption" style="height: 400px" autoresize />
    </div>

    <div class="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- Tag co-occurrence -->
      <div
        v-if="tagPairs.length"
        class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4"
      >
        <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-3">Tag Co-occurrence</h3>
        <div class="space-y-1.5 max-h-80 overflow-y-auto">
          <div
            v-for="pair in tagPairs"
            :key="pair.tag1 + pair.tag2"
            class="flex items-center justify-between text-sm py-1 border-b border-(--ui-border-muted) last:border-0"
          >
            <span class="text-highlighted">
              <span class="font-medium">{{ pair.tag1 }}</span>
              <span class="text-acid-400/60 mx-1.5">+</span>
              <span class="font-medium">{{ pair.tag2 }}</span>
            </span>
            <span class="text-dimmed text-xs tabular ml-3 shrink-0">{{ pair.shared_artists }} artists</span>
          </div>
        </div>
      </div>

      <!-- Rare tags -->
      <div
        v-if="rareTags.length"
        class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4"
      >
        <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-1">Rare Finds</h3>
        <p class="text-xs text-dimmed mb-3">Tags used by only 1&ndash;3 artists</p>
        <div class="flex flex-wrap gap-2">
          <UBadge
            v-for="tag in rareTags"
            :key="tag.name"
            variant="soft"
            color="neutral"
            size="sm"
          >
            {{ tag.name }}
            <span class="opacity-60 ml-1">({{ tag.artist_count }})</span>
          </UBadge>
        </div>
      </div>
    </div>
  </ObservatorySection>
</template>
