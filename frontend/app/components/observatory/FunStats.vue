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
    <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg">
      <!-- Tab selector -->
      <div class="flex border-b border-gray-200 dark:border-gray-800 px-4">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="px-3 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors"
          :class="activeTab === tab.key
            ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
            : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'"
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
            class="flex items-start gap-3"
          >
            <span class="text-xs font-bold text-gray-400 dark:text-gray-500 w-5 text-right tabular-nums mt-0.5">
              {{ idx + 1 }}
            </span>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium text-gray-900 dark:text-white break-words">
                {{ t.title }}
              </div>
              <div class="text-xs text-gray-500 dark:text-gray-400">
                {{ t.artist }} &middot; {{ t.length }} characters
              </div>
            </div>
          </div>
          <p v-if="stats.longest_titles.length === 0" class="text-sm text-gray-500 dark:text-gray-400 text-center py-4">
            No data available.
          </p>
        </div>

        <!-- Track Extremes -->
        <div v-if="activeTab === 'tracks'" class="space-y-4">
          <div>
            <h4 class="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Longest Tracks
            </h4>
            <div class="space-y-2">
              <div
                v-for="(t, idx) in stats.longest_tracks"
                :key="`long-${t.title}`"
                class="flex items-center gap-3"
              >
                <span class="text-xs font-bold text-gray-400 dark:text-gray-500 w-5 text-right tabular-nums">
                  {{ idx + 1 }}
                </span>
                <div class="flex-1 min-w-0">
                  <div class="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {{ t.title }}
                  </div>
                  <div class="text-xs text-gray-500 dark:text-gray-400 truncate">
                    {{ t.artist }}
                  </div>
                </div>
                <span class="text-sm font-semibold text-emerald-500 tabular-nums shrink-0">
                  {{ formatDuration(t.duration_ms) }}
                </span>
              </div>
            </div>
          </div>

          <div>
            <h4 class="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Shortest Tracks
            </h4>
            <div class="space-y-2">
              <div
                v-for="(t, idx) in stats.shortest_tracks"
                :key="`short-${t.title}`"
                class="flex items-center gap-3"
              >
                <span class="text-xs font-bold text-gray-400 dark:text-gray-500 w-5 text-right tabular-nums">
                  {{ idx + 1 }}
                </span>
                <div class="flex-1 min-w-0">
                  <div class="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {{ t.title }}
                  </div>
                  <div class="text-xs text-gray-500 dark:text-gray-400 truncate">
                    {{ t.artist }}
                  </div>
                </div>
                <span class="text-sm font-semibold text-amber-500 tabular-nums shrink-0">
                  {{ formatDuration(t.duration_ms) }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Common Words -->
        <div v-if="activeTab === 'words'" class="space-y-4">
          <div>
            <h4 class="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              In Track Titles
            </h4>
            <div class="flex flex-wrap gap-2">
              <span
                v-for="w in stats.common_title_words"
                :key="`title-${w.word}`"
                class="inline-flex items-center gap-1 text-sm px-2.5 py-1 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
              >
                {{ w.word }}
                <span class="text-xs opacity-70">{{ w.count }}</span>
              </span>
            </div>
            <p v-if="stats.common_title_words.length === 0" class="text-sm text-gray-500 dark:text-gray-400 text-center py-2">
              No data available.
            </p>
          </div>

          <div>
            <h4 class="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              In Artist Names
            </h4>
            <div class="flex flex-wrap gap-2">
              <span
                v-for="w in stats.common_artist_words"
                :key="`artist-${w.word}`"
                class="inline-flex items-center gap-1 text-sm px-2.5 py-1 rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300"
              >
                {{ w.word }}
                <span class="text-xs opacity-70">{{ w.count }}</span>
              </span>
            </div>
            <p v-if="stats.common_artist_words.length === 0" class="text-sm text-gray-500 dark:text-gray-400 text-center py-2">
              No data available.
            </p>
          </div>
        </div>

        <!-- File Paths -->
        <div v-if="activeTab === 'paths'" class="space-y-4">
          <div>
            <h4 class="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Longest File Paths
            </h4>
            <div class="space-y-1.5">
              <div
                v-for="(p, idx) in stats.longest_paths"
                :key="`longpath-${idx}`"
                class="text-xs font-mono text-gray-600 dark:text-gray-400 break-all"
              >
                <span class="text-gray-400 dark:text-gray-500">{{ idx + 1 }}.</span>
                {{ p.path }}
                <span v-if="p.length" class="text-gray-400 dark:text-gray-500">({{ p.length }} chars)</span>
              </div>
            </div>
            <p v-if="stats.longest_paths.length === 0" class="text-sm text-gray-500 dark:text-gray-400 text-center py-2">
              No data available.
            </p>
          </div>

          <div>
            <h4 class="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Deepest Nested
            </h4>
            <div class="space-y-1.5">
              <div
                v-for="(p, idx) in stats.deepest_paths"
                :key="`deeppath-${idx}`"
                class="text-xs font-mono text-gray-600 dark:text-gray-400 break-all"
              >
                <span class="text-gray-400 dark:text-gray-500">{{ idx + 1 }}.</span>
                {{ p.path }}
                <span v-if="p.depth" class="text-gray-400 dark:text-gray-500">({{ p.depth }} levels deep)</span>
              </div>
            </div>
            <p v-if="stats.deepest_paths.length === 0" class="text-sm text-gray-500 dark:text-gray-400 text-center py-2">
              No data available.
            </p>
          </div>
        </div>
      </div>
    </div>
  </ObservatorySection>
</template>
