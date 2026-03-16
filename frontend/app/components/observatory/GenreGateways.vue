<script setup lang="ts">
import type { GatewaysData } from '~/types/observatory'

const props = defineProps<{ data: GatewaysData }>()

type TabView = 'bridges' | 'artists'
const activeTab = ref<TabView>('bridges')

// Tag color palette for consistent coloring
const tagColors = [
  'bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300',
  'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300',
  'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300',
  'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300',
  'bg-rose-100 dark:bg-rose-900/40 text-rose-700 dark:text-rose-300',
  'bg-cyan-100 dark:bg-cyan-900/40 text-cyan-700 dark:text-cyan-300',
  'bg-pink-100 dark:bg-pink-900/40 text-pink-700 dark:text-pink-300',
  'bg-lime-100 dark:bg-lime-900/40 text-lime-700 dark:text-lime-300',
]

function getTagColor(index: number): string {
  return tagColors[index % tagColors.length]
}
</script>

<template>
  <ObservatorySection
    title="Genre Gateways"
    description="Artists and tags that bridge musical worlds"
  >
    <!-- Tab buttons -->
    <div class="flex items-center gap-2 mb-4">
      <button
        v-for="tab in (['bridges', 'artists'] as TabView[])"
        :key="tab"
        class="px-3 py-1 text-sm font-medium rounded-md transition-colors"
        :class="activeTab === tab
          ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300'
          : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'"
        @click="activeTab = tab"
      >
        {{ tab === 'bridges' ? 'Genre Bridges' : 'Cross-Genre Artists' }}
      </button>
    </div>

    <!-- Genre Bridges -->
    <div v-if="activeTab === 'bridges'">
      <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
        <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
          Scene Connections
        </h3>
        <p class="text-xs text-gray-400 dark:text-gray-500 mb-4">
          Pairs of genres connected by artists tagged with both
        </p>
        <div class="space-y-2" v-if="data.genre_bridges.length > 0">
          <div
            v-for="(bridge, i) in data.genre_bridges"
            :key="i"
            class="flex items-center gap-3 text-sm py-1.5"
          >
            <span class="font-medium text-gray-900 dark:text-white">{{ bridge.tag1 }}</span>
            <span class="text-gray-300 dark:text-gray-600 flex items-center gap-1">
              <span class="w-8 h-px bg-current inline-block" />
              <span class="text-xs tabular-nums text-gray-500">{{ bridge.bridge_count }}</span>
              <span class="w-8 h-px bg-current inline-block" />
            </span>
            <span class="font-medium text-gray-900 dark:text-white">{{ bridge.tag2 }}</span>
          </div>
        </div>
        <p v-else class="text-sm text-gray-500 dark:text-gray-400">
          Not enough cross-genre data available yet.
        </p>
      </div>
    </div>

    <!-- Cross-Genre Artists -->
    <div v-if="activeTab === 'artists'">
      <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
        <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
          Most Genre-Fluid Artists
        </h3>
        <p class="text-xs text-gray-400 dark:text-gray-500 mb-4">
          Artists tagged with the most distinct genres &mdash; the connectors between scenes
        </p>
        <div class="space-y-3" v-if="data.bridge_artists.length > 0">
          <div
            v-for="artist in data.bridge_artists"
            :key="artist.name"
            class="border-b border-gray-100 dark:border-gray-800 last:border-0 pb-2 last:pb-0"
          >
            <div class="flex items-center justify-between mb-1.5">
              <span class="text-sm font-medium text-gray-900 dark:text-white">{{ artist.name }}</span>
              <span class="text-xs text-gray-400 tabular-nums">{{ artist.tag_count }} tags</span>
            </div>
            <div class="flex flex-wrap gap-1">
              <span
                v-for="(tag, j) in artist.tags.slice(0, 8)"
                :key="tag"
                class="text-[10px] px-2 py-0.5 rounded-full"
                :class="getTagColor(j)"
              >
                {{ tag }}
              </span>
              <span
                v-if="artist.tags.length > 8"
                class="text-[10px] px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500"
              >
                +{{ artist.tags.length - 8 }} more
              </span>
            </div>
          </div>
        </div>
        <p v-else class="text-sm text-gray-500 dark:text-gray-400">
          Not enough tag data available yet.
        </p>
      </div>
    </div>
  </ObservatorySection>
</template>
