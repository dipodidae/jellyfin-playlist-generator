<script setup lang="ts">
import type { SceneCluster } from '~/types/observatory'

defineProps<{ clusters: SceneCluster[] }>()
</script>

<template>
  <ObservatorySection title="Scene Clusters" description="Artist groupings discovered by embedding similarity">
    <div v-if="clusters.length === 0" class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-6 text-center text-gray-500 dark:text-gray-400">
      No scene clusters available yet. Run the clustering enrichment to populate this section.
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div
        v-for="cluster in clusters"
        :key="cluster.id"
        class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4"
      >
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-gray-900 dark:text-white truncate">
            {{ cluster.name || `Cluster ${cluster.id}` }}
          </h3>
          <span class="text-xs text-gray-500 dark:text-gray-400 tabular-nums shrink-0 ml-2">
            {{ cluster.size }} artists
          </span>
        </div>

        <!-- Top artists -->
        <div v-if="cluster.top_artists.length > 0" class="mb-3">
          <h4 class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
            Top Artists
          </h4>
          <div class="space-y-1">
            <div
              v-for="artist in cluster.top_artists.slice(0, 5)"
              :key="artist.name"
              class="flex items-center justify-between text-sm"
            >
              <span class="text-gray-700 dark:text-gray-300 truncate mr-2">{{ artist.name }}</span>
              <div class="flex items-center gap-1.5 shrink-0">
                <div class="w-16 bg-gray-200 dark:bg-gray-700 rounded-full h-1.5">
                  <div
                    class="h-1.5 rounded-full bg-violet-500"
                    :style="{ width: `${Math.min(artist.weight * 100, 100)}%` }"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Top tags -->
        <div v-if="cluster.top_tags.length > 0">
          <h4 class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
            Tags
          </h4>
          <div class="flex flex-wrap gap-1">
            <span
              v-for="tag in cluster.top_tags.slice(0, 6)"
              :key="tag.name"
              class="inline-block text-xs px-2 py-0.5 rounded-full bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300"
            >
              {{ tag.name }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </ObservatorySection>
</template>
