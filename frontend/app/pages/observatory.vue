<script setup lang="ts">
const { data, loading, error, fetchStats } = useObservatory()

onMounted(() => fetchStats())

function formatBytes(bytes: number): string {
  if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`
  return `${(bytes / 1e9).toFixed(1)} GB`
}

function formatTotalDuration(ms: number): string {
  const days = Math.floor(ms / 86400000)
  const hours = Math.floor((ms % 86400000) / 3600000)
  if (days > 0) return `${days}d ${hours}h`
  return `${hours}h`
}
</script>

<template>
  <div>
    <!-- Loading state -->
    <div v-if="loading" class="flex flex-col items-center justify-center py-24 gap-4">
      <div class="animate-spin rounded-full h-10 w-10 border-2 border-gray-300 dark:border-gray-600 border-t-indigo-500" />
      <p class="text-sm text-gray-500 dark:text-gray-400">Loading observatory data...</p>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="flex flex-col items-center justify-center py-24 gap-4">
      <div class="text-red-500 text-lg font-semibold">Failed to load data</div>
      <p class="text-sm text-gray-500 dark:text-gray-400">{{ error }}</p>
      <UButton variant="soft" @click="fetchStats()">
        Retry
      </UButton>
    </div>

    <!-- Data loaded -->
    <div v-else-if="data" class="space-y-10">
      <!-- Page header -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-bold text-gray-900 dark:text-white">Music Observatory</h1>
          <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">
            {{ data.collection.total_tracks.toLocaleString() }} tracks &middot;
            {{ data.collection.total_artists.toLocaleString() }} artists &middot;
            {{ formatBytes(data.collection.total_file_size_bytes) }} &middot;
            {{ formatTotalDuration(data.collection.total_duration_ms) }} of music
          </p>
        </div>
        <UButton
          variant="ghost"
          size="sm"
          icon="i-heroicons-arrow-path"
          :loading="loading"
          @click="fetchStats(true)"
        >
          Refresh
        </UButton>
      </div>

      <!-- Collection Overview -->
      <CollectionOverview :stats="data.collection" />

      <!-- Format Breakdown -->
      <FormatBreakdown v-if="data.formats.length > 0" :formats="data.formats" />

      <!-- Release Timeline -->
      <TimelineChart
        v-if="data.decades.length > 0"
        :decades="data.decades"
        :years="data.years"
        :oldest-tracks="data.oldest_tracks"
        :newest-tracks="data.newest_tracks"
        :dominant-decade="data.dominant_decade"
      />

      <!-- Tag Intelligence -->
      <TagIntelligence
        v-if="data.top_tags.length > 0"
        :top-tags="data.top_tags"
        :rare-tags="data.rare_tags"
        :tag-pairs="data.tag_pairs"
      />

      <!-- Cultural Map (Cultural Gravity + Tag Evolution + Genre Purity) -->
      <CulturalMap
        v-if="data.cultural_map && data.cultural_map.cultural_gravity.length > 0"
        :data="data.cultural_map"
      />

      <!-- Artist Intelligence -->
      <ArtistIntelligence
        v-if="data.top_artists_by_tracks.length > 0"
        :by-tracks="data.top_artists_by_tracks"
        :by-playtime="data.top_artists_by_playtime"
        :by-albums="data.top_artists_by_albums"
        :one-track-artists="data.one_track_artists"
      />

      <!-- Album Stats -->
      <AlbumStats
        v-if="data.albums_most_tracks.length > 0"
        :most-tracks="data.albums_most_tracks"
        :longest="data.albums_longest"
        :shortest="data.albums_shortest"
      />

      <!-- Darkness Index -->
      <DarknessIndex
        v-if="data.darkness_index && data.darkness_index.keyword_counts.length > 0"
        :data="data.darkness_index"
      />

      <!-- Longform & Title Archetypes -->
      <LongformStats
        v-if="data.longform"
        :data="data.longform"
      />

      <!-- Taste Fingerprint (conditional on enrichment data) -->
      <TasteFingerprint
        v-if="data.profile_averages && data.profile_distributions && data.profile_averages.count > 0"
        :averages="data.profile_averages"
        :distributions="data.profile_distributions"
      />

      <!-- Scene Clusters -->
      <SceneClusters :clusters="data.clusters" />

      <!-- Genre Gateways (Bridge Artists) -->
      <GenreGateways
        v-if="data.gateways && (data.gateways.bridge_artists.length > 0 || data.gateways.genre_bridges.length > 0)"
        :data="data.gateways"
      />

      <!-- Audio Features (conditional on enrichment data) -->
      <AudioFeatures
        :bpm-distribution="data.bpm_distribution"
        :key-distribution="data.key_distribution"
        :averages="data.audio_averages"
      />

      <!-- Generation Stats -->
      <GenerationStats
        :total-playlists="data.total_playlists"
        :arc-type-breakdown="data.arc_type_breakdown"
        :most-used-tracks="data.most_used_tracks"
      />

      <!-- Collection Archaeology (Compilation + Forgotten + Temporal Bias) -->
      <CollectionArchaeology
        v-if="data.archaeology"
        :data="data.archaeology"
      />

      <!-- Fun Stats -->
      <FunStats :stats="data.fun_stats" />
    </div>
  </div>
</template>
