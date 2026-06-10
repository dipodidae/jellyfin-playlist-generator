<script setup lang="ts">
import type { FunStats as FunStatsType } from '~/types/observatory'

const props = defineProps<{ stats: FunStatsType }>()

const { formatDuration } = useDurationFormatter()

type TabKey = 'titles' | 'tracks' | 'words' | 'paths'
const activeTab = ref<TabKey>('titles')

const tabs: { key: TabKey, label: string }[] = [
  { key: 'titles', label: 'Longest Titles' },
  { key: 'tracks', label: 'Track Extremes' },
  { key: 'words', label: 'Common Words' },
  { key: 'paths', label: 'File Paths' },
]
</script>

<template>
  <ObservatorySection title="Fun Stats" description="Quirky facts hiding in your collection">
    <div class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl overflow-hidden">
      <!-- Tab selector -->
      <div class="flex border-b border-(--ui-border) px-4 overflow-x-auto">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="px-3 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors whitespace-nowrap"
          :class="activeTab === tab.key
            ? 'border-acid-400 text-acid-300'
            : 'border-transparent text-muted hover:text-highlighted'"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>

      <div class="p-4">
        <!-- Longest Titles -->
        <div v-if="activeTab === 'titles'" class="space-y-2">
          <div
            v-for="(t, idx) in stats.longest_titles"
            :key="t.title"
            class="flex items-start gap-3 py-1 border-b border-(--ui-border-muted) last:border-0"
          >
            <span class="text-xs font-bold text-dimmed w-5 text-right tabular mt-0.5 shrink-0">
              {{ idx + 1 }}
            </span>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium text-highlighted break-words">{{ t.title }}</div>
              <div class="text-xs text-muted">{{ t.artist }} &middot; <span class="tabular">{{ t.length }} characters</span></div>
            </div>
          </div>
          <p v-if="stats.longest_titles.length === 0" class="text-sm text-muted text-center py-4">
            No data available.
          </p>
        </div>

        <!-- Track Extremes -->
        <div v-if="activeTab === 'tracks'" class="space-y-4">
          <div>
            <h4 class="text-[10px] font-medium text-dimmed uppercase tracking-widest mb-2">Longest Tracks</h4>
            <div class="space-y-2">
              <div
                v-for="(t, idx) in stats.longest_tracks"
                :key="`long-${t.title}`"
                class="flex items-center gap-3 py-1 border-b border-(--ui-border-muted) last:border-0"
              >
                <span class="text-xs font-bold text-dimmed w-5 text-right tabular shrink-0">{{ idx + 1 }}</span>
                <div class="flex-1 min-w-0">
                  <div class="text-sm font-medium text-highlighted truncate">{{ t.title }}</div>
                  <div class="text-xs text-muted truncate">{{ t.artist }}</div>
                </div>
                <span class="text-sm font-semibold text-[#6fe3c0] tabular shrink-0">
                  {{ formatDuration(t.duration_ms) }}
                </span>
              </div>
            </div>
          </div>

          <div>
            <h4 class="text-[10px] font-medium text-dimmed uppercase tracking-widest mb-2">Shortest Tracks</h4>
            <div class="space-y-2">
              <div
                v-for="(t, idx) in stats.shortest_tracks"
                :key="`short-${t.title}`"
                class="flex items-center gap-3 py-1 border-b border-(--ui-border-muted) last:border-0"
              >
                <span class="text-xs font-bold text-dimmed w-5 text-right tabular shrink-0">{{ idx + 1 }}</span>
                <div class="flex-1 min-w-0">
                  <div class="text-sm font-medium text-highlighted truncate">{{ t.title }}</div>
                  <div class="text-xs text-muted truncate">{{ t.artist }}</div>
                </div>
                <span class="text-sm font-semibold text-acid-300 tabular shrink-0">
                  {{ formatDuration(t.duration_ms) }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Common Words -->
        <div v-if="activeTab === 'words'" class="space-y-4">
          <div>
            <h4 class="text-[10px] font-medium text-dimmed uppercase tracking-widest mb-2">In Track Titles</h4>
            <div class="flex flex-wrap gap-2">
              <UBadge
                v-for="w in stats.common_title_words"
                :key="`title-${w.word}`"
                variant="soft"
                color="primary"
                size="sm"
              >
                {{ w.word }}
                <span class="opacity-60 ml-1 tabular">{{ w.count }}</span>
              </UBadge>
            </div>
            <p v-if="stats.common_title_words.length === 0" class="text-sm text-muted text-center py-2">
              No data available.
            </p>
          </div>

          <div>
            <h4 class="text-[10px] font-medium text-dimmed uppercase tracking-widest mb-2">In Artist Names</h4>
            <div class="flex flex-wrap gap-2">
              <UBadge
                v-for="w in stats.common_artist_words"
                :key="`artist-${w.word}`"
                variant="soft"
                color="neutral"
                size="sm"
              >
                {{ w.word }}
                <span class="opacity-60 ml-1 tabular">{{ w.count }}</span>
              </UBadge>
            </div>
            <p v-if="stats.common_artist_words.length === 0" class="text-sm text-muted text-center py-2">
              No data available.
            </p>
          </div>
        </div>

        <!-- File Paths -->
        <div v-if="activeTab === 'paths'" class="space-y-4">
          <div>
            <h4 class="text-[10px] font-medium text-dimmed uppercase tracking-widest mb-2">Longest File Paths</h4>
            <div class="space-y-1.5">
              <div
                v-for="(p, idx) in stats.longest_paths"
                :key="`longpath-${idx}`"
                class="text-xs font-mono text-muted break-all leading-relaxed"
              >
                <span class="text-dimmed mr-1">{{ idx + 1 }}.</span>{{ p.path }}
                <span v-if="p.length" class="text-dimmed ml-1 tabular">({{ p.length }} chars)</span>
              </div>
            </div>
            <p v-if="stats.longest_paths.length === 0" class="text-sm text-muted text-center py-2">
              No data available.
            </p>
          </div>

          <div>
            <h4 class="text-[10px] font-medium text-dimmed uppercase tracking-widest mb-2">Deepest Nested</h4>
            <div class="space-y-1.5">
              <div
                v-for="(p, idx) in stats.deepest_paths"
                :key="`deeppath-${idx}`"
                class="text-xs font-mono text-muted break-all leading-relaxed"
              >
                <span class="text-dimmed mr-1">{{ idx + 1 }}.</span>{{ p.path }}
                <span v-if="p.depth" class="text-dimmed ml-1 tabular">({{ p.depth }} levels deep)</span>
              </div>
            </div>
            <p v-if="stats.deepest_paths.length === 0" class="text-sm text-muted text-center py-2">
              No data available.
            </p>
          </div>
        </div>
      </div>
    </div>
  </ObservatorySection>
</template>
