<script setup lang="ts">
import type { ArcTypeEntry, UsedTrack } from '~/types/observatory'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, PieChart, TooltipComponent, LegendComponent])

const props = defineProps<{
  totalPlaylists: number
  arcTypeBreakdown: ArcTypeEntry[]
  mostUsedTracks: UsedTrack[]
}>()

const colorMode = useColorMode()

const { formatDuration } = useDurationFormatter()

const arcColors: Record<string, string> = {
  rise: '#22c55e',
  fall: '#3b82f6',
  peak: '#ef4444',
  steady: '#f59e0b',
  journey: '#8b5cf6',
  wave: '#06b6d4',
}

const arcOption = computed(() => {
  if (props.arcTypeBreakdown.length === 0) return null
  const isDark = colorMode.value === 'dark'

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: { name: string, value: number, percent: number, data: { avgTime: number } }) => {
        const avgMs = params.data.avgTime
        return `<b>${params.name}</b><br/>${params.value} playlists (${params.percent}%)<br/>Avg generation: ${formatDuration(avgMs)}`
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
        data: props.arcTypeBreakdown.map(a => ({
          value: a.count,
          name: a.arc_type,
          avgTime: a.avg_time_ms,
          itemStyle: { color: arcColors[a.arc_type] || '#6b7280' },
        })),
      },
    ],
  }
})
</script>

<template>
  <ObservatorySection title="Generation Stats" description="Playlist creation history and patterns">
    <div
      v-if="totalPlaylists === 0"
      class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-6 text-center text-muted"
    >
      No playlists generated yet. Create your first playlist to see generation stats.
    </div>

    <template v-else>
      <!-- Total playlists hero -->
      <div class="bg-(--ui-bg-accented) border border-acid-400/20 rounded-xl px-5 py-4 mb-4 flex items-center gap-4">
        <UIcon name="i-lucide-list-music" class="size-7 text-acid-400/60 shrink-0" />
        <div>
          <div class="text-3xl font-bold font-display tabular text-acid-300">{{ totalPlaylists }}</div>
          <div class="text-sm text-muted">playlists generated</div>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <!-- Arc type donut -->
        <div v-if="arcOption" class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4">
          <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-3">Arc Types</h3>
          <VChart :option="arcOption" style="height: 260px" autoresize />
        </div>

        <!-- Most used tracks -->
        <div v-if="mostUsedTracks.length > 0" class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4">
          <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-3">Most Used Tracks</h3>
          <div class="space-y-2">
            <div
              v-for="(track, idx) in mostUsedTracks.slice(0, 10)"
              :key="`${track.title}-${track.artist}`"
              class="flex items-center gap-3 py-1 border-b border-(--ui-border-muted) last:border-0"
            >
              <span class="text-xs font-bold text-dimmed w-5 text-right tabular shrink-0">{{ idx + 1 }}</span>
              <div class="flex-1 min-w-0">
                <div class="text-sm font-medium text-highlighted truncate">{{ track.title }}</div>
                <div class="text-xs text-muted truncate">{{ track.artist }}</div>
              </div>
              <UBadge variant="soft" color="primary" size="xs" class="tabular shrink-0">
                {{ track.usage_count }}×
              </UBadge>
            </div>
          </div>
        </div>
      </div>
    </template>
  </ObservatorySection>
</template>
