<script setup lang="ts">
import type { LibraryStats } from '~/types/library'

defineProps<{
  stats: LibraryStats
  isSyncing: boolean
  syncingLastfm: boolean
  syncingEmbeddings: boolean
  syncingProfiles: boolean
}>()

const emit = defineEmits<{
  'full-sync': []
  'sync-lastfm': []
  'sync-embeddings': []
  'sync-profiles': []
  'refresh-stats': []
}>()
</script>

<template>
  <div class="pt-3 border-t border-gray-200 dark:border-gray-800 space-y-3">
    <div class="grid grid-cols-2 gap-4 text-sm">
      <StatPill
        label="Last.fm Tags"
        :value="`${stats.lastfm_tags.toLocaleString()} tags · ${(stats.artists_with_tags ?? 0).toLocaleString()}/${stats.artists} artists enriched`"
      />
      <StatPill
        label="Artist Similarity"
        :value="`${(stats.artist_similarities ?? 0).toLocaleString()} connections`"
      />
      <StatPill
        label="Track Embeddings"
        :value="`${(stats.tracks_with_embeddings ?? 0).toLocaleString()}/${stats.tracks} tracks`"
      />
      <StatPill
        label="Semantic Profiles"
        :value="`${(stats.tracks_with_profiles ?? 0).toLocaleString()}/${stats.tracks} tracks`"
      />
      <StatPill
        label="Genres"
        :value="stats.genres.toLocaleString()"
      />
    </div>

    <div class="flex flex-wrap gap-2 pt-2">
      <UButton
        :loading="isSyncing"
        :disabled="isSyncing"
        variant="outline"
        size="xs"
        @click="emit('full-sync')"
      >
        Full Sync
      </UButton>
      <UButton
        :loading="syncingLastfm"
        :disabled="syncingLastfm"
        variant="outline"
        size="xs"
        @click="emit('sync-lastfm')"
      >
        Enrich from Last.fm
      </UButton>
      <UButton
        :loading="syncingEmbeddings"
        :disabled="syncingEmbeddings"
        variant="outline"
        size="xs"
        @click="emit('sync-embeddings')"
      >
        Generate Embeddings
      </UButton>
      <UButton
        :loading="syncingProfiles"
        :disabled="syncingProfiles"
        variant="outline"
        size="xs"
        @click="emit('sync-profiles')"
      >
        Generate Profiles
      </UButton>
      <UButton
        variant="outline"
        size="xs"
        @click="emit('refresh-stats')"
      >
        Refresh Stats
      </UButton>
    </div>
  </div>
</template>
