<script setup lang="ts">
import type { SceneCluster } from '~/types/observatory'

defineProps<{ clusters: SceneCluster[] }>()
</script>

<template>
  <ObservatorySection title="Scene Clusters" description="Artist groupings discovered by embedding similarity">
    <div
      v-if="clusters.length === 0"
      class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-6 text-center text-muted"
    >
      No scene clusters available yet. Run the clustering enrichment to populate this section.
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div
        v-for="cluster in clusters"
        :key="cluster.id"
        class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4 hover:border-[#7a3df0]/30 transition-colors"
      >
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold font-display text-highlighted truncate">
            {{ cluster.name || `Cluster ${cluster.id}` }}
          </h3>
          <UBadge variant="soft" color="neutral" size="xs" class="tabular shrink-0 ml-2">
            {{ cluster.size }} artists
          </UBadge>
        </div>

        <!-- Top artists -->
        <div v-if="cluster.top_artists.length > 0" class="mb-3">
          <h4 class="text-[10px] font-medium text-dimmed uppercase tracking-widest mb-1.5">Top Artists</h4>
          <div class="space-y-1.5">
            <div
              v-for="artist in cluster.top_artists.slice(0, 5)"
              :key="artist.name"
              class="flex items-center justify-between text-sm"
            >
              <span class="text-muted truncate mr-2">{{ artist.name }}</span>
              <div class="flex items-center gap-1.5 shrink-0">
                <div class="w-16 bg-(--ui-bg-elevated) rounded-full h-1">
                  <div
                    class="h-1 rounded-full bg-[#7a3df0]"
                    :style="{ width: `${Math.min(artist.weight * 100, 100)}%` }"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Top tags -->
        <div v-if="cluster.top_tags.length > 0">
          <h4 class="text-[10px] font-medium text-dimmed uppercase tracking-widest mb-1.5">Tags</h4>
          <div class="flex flex-wrap gap-1">
            <span
              v-for="tag in cluster.top_tags.slice(0, 6)"
              :key="tag.name"
              class="inline-block text-[10px] px-2 py-0.5 rounded-full bg-[#7a3df0]/12 text-[#c084fc] ring-1 ring-[#7a3df0]/25"
            >
              {{ tag.name }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </ObservatorySection>
</template>
