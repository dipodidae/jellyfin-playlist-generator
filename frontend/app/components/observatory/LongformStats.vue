<script setup lang="ts">
import type { LongformData } from '~/types/observatory'

const props = defineProps<{ data: LongformData }>()

const { formatDuration } = useDurationFormatter()

type TabView = 'longform' | 'archetypes'
const activeTab = ref<TabView>('longform')

const thresholdCards = computed(() => {
  const t = props.data.thresholds
  return [
    { label: '10+ min', count: t.over_10min, color: 'blue' },
    { label: '15+ min', count: t.over_15min, color: 'violet' },
    { label: '20+ min', count: t.over_20min, color: 'amber' },
    { label: '30+ min', count: t.over_30min, color: 'red' },
  ]
})

const colorClasses: Record<string, { bg: string; text: string }> = {
  blue: { bg: 'bg-blue-50 dark:bg-blue-950/30', text: 'text-blue-600 dark:text-blue-400' },
  violet: { bg: 'bg-violet-50 dark:bg-violet-950/30', text: 'text-violet-600 dark:text-violet-400' },
  amber: { bg: 'bg-amber-50 dark:bg-amber-950/30', text: 'text-amber-600 dark:text-amber-400' },
  red: { bg: 'bg-red-50 dark:bg-red-950/30', text: 'text-red-600 dark:text-red-400' },
}
</script>

<template>
  <ObservatorySection
    title="Longform & Archetypes"
    description="Epic compositions and structural patterns in track naming"
  >
    <!-- Tab buttons -->
    <div class="flex items-center gap-2 mb-4">
      <button
        v-for="tab in (['longform', 'archetypes'] as TabView[])"
        :key="tab"
        class="px-3 py-1 text-sm font-medium rounded-md transition-colors"
        :class="activeTab === tab
          ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300'
          : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'"
        @click="activeTab = tab"
      >
        {{ tab === 'longform' ? 'Longform Compositions' : 'Title Archetypes' }}
      </button>
    </div>

    <!-- Longform Compositions -->
    <div v-if="activeTab === 'longform'">
      <!-- Threshold cards -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <div
          v-for="card in thresholdCards"
          :key="card.label"
          class="text-center p-4 rounded-lg"
          :class="colorClasses[card.color].bg"
        >
          <div class="text-2xl font-bold tabular-nums" :class="colorClasses[card.color].text">
            {{ card.count.toLocaleString() }}
          </div>
          <div class="text-xs text-gray-500 dark:text-gray-400 mt-1">{{ card.label }}</div>
        </div>
      </div>

      <!-- Top 20 longest tracks -->
      <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
        <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
          Top 20 Longest Tracks
        </h3>
        <div class="space-y-1.5">
          <div
            v-for="(track, i) in data.longest_tracks"
            :key="i"
            class="flex items-center justify-between text-sm py-1"
          >
            <div class="flex items-center gap-2 min-w-0">
              <span class="text-gray-400 dark:text-gray-600 w-5 text-right tabular-nums shrink-0">{{ i + 1 }}</span>
              <span class="text-gray-900 dark:text-white font-medium truncate">{{ track.title }}</span>
              <span class="text-gray-400 dark:text-gray-500 text-xs truncate shrink-0">&mdash; {{ track.artist }}</span>
            </div>
            <span class="text-blue-500 dark:text-blue-400 text-xs font-mono tabular-nums ml-3 shrink-0">
              {{ formatDuration(track.duration_ms) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Title Archetypes -->
    <div v-if="activeTab === 'archetypes'">
      <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
        <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
          Structural Naming Patterns
        </h3>
        <p class="text-xs text-gray-400 dark:text-gray-500 mb-4">
          Common track naming conventions that reveal album structure culture
        </p>
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          <div
            v-for="archetype in data.title_archetypes"
            :key="archetype.pattern"
            class="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-center"
          >
            <div class="text-lg font-bold text-gray-900 dark:text-white tabular-nums">
              {{ archetype.count.toLocaleString() }}
            </div>
            <div class="text-xs text-gray-500 dark:text-gray-400 mt-1 font-medium">
              {{ archetype.pattern }}
            </div>
          </div>
        </div>
      </div>

      <!-- Insight callout -->
      <div
        v-if="data.title_archetypes.length > 0"
        class="mt-4 bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg px-4 py-3"
      >
        <span class="text-sm text-blue-700 dark:text-blue-300">
          Your collection contains
          <span class="font-bold">
            {{ data.title_archetypes.reduce((sum, a) => sum + a.count, 0).toLocaleString() }}
          </span>
          tracks with structural naming patterns &mdash; intros, outros, interludes, parts, and more.
        </span>
      </div>
    </div>
  </ObservatorySection>
</template>
