<script setup lang="ts">
import type { GatewaysData } from '~/types/observatory'

const props = defineProps<{ data: GatewaysData }>()

type TabView = 'bridges' | 'artists'
const activeTab = ref<TabView>('bridges')

// Tag color palette for consistent coloring
const tagColors = [
  'bg-[#7a3df0]/15 text-[#c084fc] ring-1 ring-[#7a3df0]/25',
  'bg-[#59c1ff]/12 text-[#59c1ff] ring-1 ring-[#59c1ff]/25',
  'bg-[#6fe3c0]/12 text-[#6fe3c0] ring-1 ring-[#6fe3c0]/25',
  'bg-acid-400/10 text-acid-300 ring-1 ring-acid-400/25',
  'bg-pink-500/12 text-pink-300 ring-1 ring-pink-500/25',
  'bg-orange-500/10 text-orange-300 ring-1 ring-orange-500/25',
  'bg-sky-500/12 text-sky-300 ring-1 ring-sky-500/25',
  'bg-emerald-500/12 text-emerald-300 ring-1 ring-emerald-500/25',
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
    <div class="flex items-center gap-1.5 mb-4">
      <button
        v-for="tab in (['bridges', 'artists'] as TabView[])"
        :key="tab"
        class="px-3 py-1 text-sm font-medium rounded-lg transition-colors"
        :class="activeTab === tab
          ? 'bg-acid-400/10 text-acid-300 ring-1 ring-acid-400/30'
          : 'text-muted hover:text-highlighted'"
        @click="activeTab = tab"
      >
        {{ tab === 'bridges' ? 'Genre Bridges' : 'Cross-Genre Artists' }}
      </button>
    </div>

    <!-- Genre Bridges -->
    <div v-if="activeTab === 'bridges'">
      <div class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4">
        <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-1">Scene Connections</h3>
        <p class="text-xs text-dimmed mb-4">Pairs of genres connected by artists tagged with both</p>
        <div class="space-y-2" v-if="data.genre_bridges.length > 0">
          <div
            v-for="(bridge, i) in data.genre_bridges"
            :key="i"
            class="flex items-center gap-3 text-sm py-1.5 border-b border-(--ui-border-muted) last:border-0"
          >
            <span class="font-medium text-highlighted">{{ bridge.tag1 }}</span>
            <span class="flex items-center gap-1 text-dimmed">
              <span class="w-6 h-px bg-acid-400/30 inline-block" />
              <span class="text-[10px] tabular text-acid-400/70">{{ bridge.bridge_count }}</span>
              <span class="w-6 h-px bg-acid-400/30 inline-block" />
            </span>
            <span class="font-medium text-highlighted">{{ bridge.tag2 }}</span>
          </div>
        </div>
        <p v-else class="text-sm text-muted">Not enough cross-genre data available yet.</p>
      </div>
    </div>

    <!-- Cross-Genre Artists -->
    <div v-if="activeTab === 'artists'">
      <div class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4">
        <h3 class="text-xs font-medium text-muted uppercase tracking-widest mb-1">Most Genre-Fluid Artists</h3>
        <p class="text-xs text-dimmed mb-4">
          Artists tagged with the most distinct genres &mdash; the connectors between scenes
        </p>
        <div class="space-y-3" v-if="data.bridge_artists.length > 0">
          <div
            v-for="artist in data.bridge_artists"
            :key="artist.name"
            class="border-b border-(--ui-border-muted) last:border-0 pb-2.5 last:pb-0"
          >
            <div class="flex items-center justify-between mb-1.5">
              <span class="text-sm font-medium text-highlighted">{{ artist.name }}</span>
              <UBadge variant="soft" color="neutral" size="xs" class="tabular">
                {{ artist.tag_count }} tags
              </UBadge>
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
                class="text-[10px] px-2 py-0.5 rounded-full bg-(--ui-bg-elevated) text-dimmed"
              >
                +{{ artist.tags.length - 8 }} more
              </span>
            </div>
          </div>
        </div>
        <p v-else class="text-sm text-muted">Not enough tag data available yet.</p>
      </div>
    </div>
  </ObservatorySection>
</template>
