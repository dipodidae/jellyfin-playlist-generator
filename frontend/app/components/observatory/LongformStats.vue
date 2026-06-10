<script setup lang="ts">
import type { LongformData } from '~/types/observatory'

const props = defineProps<{ data: LongformData }>()

const { formatDuration } = useDurationFormatter()

type TabView = 'longform' | 'archetypes'
const activeTab = ref<TabView>('longform')

const thresholdCards = computed(() => {
  const t = props.data.thresholds
  return [
    { label: '10+ min', count: t.over_10min, color: 'text-[#59c1ff]', bg: 'bg-[#59c1ff]/8 border-[#59c1ff]/20' },
    { label: '15+ min', count: t.over_15min, color: 'text-[#c084fc]', bg: 'bg-[#7a3df0]/10 border-[#7a3df0]/20' },
    { label: '20+ min', count: t.over_20min, color: 'text-acid-300', bg: 'bg-acid-400/8 border-acid-400/20' },
    { label: '30+ min', count: t.over_30min, color: 'text-red-400', bg: 'bg-red-500/8 border-red-500/20' },
  ]
})
</script>

<template>
  <ObservatorySection
    title="Longform & Archetypes"
    description="Epic compositions and structural patterns in track naming"
  >
    <!-- Tab buttons -->
    <div class="flex items-center gap-1.5 mb-4">
      <button
        v-for="tab in (['longform', 'archetypes'] as TabView[])"
        :key="tab"
        class="px-3 py-1 text-sm font-medium rounded-lg transition-colors"
        :class="activeTab === tab
          ? 'bg-acid-400/10 text-acid-300 ring-1 ring-acid-400/30'
          : 'text-muted hover:text-highlighted'"
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
          class="text-center p-4 rounded-xl border"
          :class="card.bg"
        >
          <div class="text-2xl font-bold font-display tabular" :class="card.color">
            {{ card.count.toLocaleString() }}
          </div>
          <div class="text-[10px] text-dimmed mt-1 uppercase tracking-widest">{{ card.label }}</div>
        </div>
      </div>

      <!-- Top 20 longest tracks -->
      <div class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4">
        <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-3">Top 20 Longest Tracks</h3>
        <div class="space-y-1.5">
          <div
            v-for="(track, i) in data.longest_tracks"
            :key="i"
            class="flex items-center justify-between text-sm py-1 border-b border-(--ui-border-muted) last:border-0"
          >
            <div class="flex items-center gap-2 min-w-0">
              <span class="text-dimmed w-5 text-right tabular shrink-0">{{ i + 1 }}</span>
              <span class="text-highlighted font-medium truncate">{{ track.title }}</span>
              <span class="text-dimmed text-xs truncate shrink-0">&mdash; {{ track.artist }}</span>
            </div>
            <span class="text-[#59c1ff] text-xs font-mono tabular ml-3 shrink-0">
              {{ formatDuration(track.duration_ms) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Title Archetypes -->
    <div v-if="activeTab === 'archetypes'">
      <div class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4">
        <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-1">Structural Naming Patterns</h3>
        <p class="text-xs text-dimmed mb-4">
          Common track naming conventions that reveal album structure culture
        </p>
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          <div
            v-for="archetype in data.title_archetypes"
            :key="archetype.pattern"
            class="bg-(--ui-bg-elevated) border border-(--ui-border-muted) rounded-xl p-3 text-center hover:border-acid-400/25 transition-colors"
          >
            <div class="text-lg font-bold font-display text-highlighted tabular">
              {{ archetype.count.toLocaleString() }}
            </div>
            <div class="text-xs text-muted mt-1 font-medium">
              {{ archetype.pattern }}
            </div>
          </div>
        </div>
      </div>

      <!-- Insight callout -->
      <div
        v-if="data.title_archetypes.length > 0"
        class="mt-3 bg-[#59c1ff]/5 border border-[#59c1ff]/20 rounded-xl px-4 py-3"
      >
        <span class="text-sm text-muted">
          Your collection contains
          <span class="font-bold text-[#59c1ff]">
            {{ data.title_archetypes.reduce((sum, a) => sum + a.count, 0).toLocaleString() }}
          </span>
          tracks with structural naming patterns &mdash; intros, outros, interludes, parts, and more.
        </span>
      </div>
    </div>
  </ObservatorySection>
</template>
