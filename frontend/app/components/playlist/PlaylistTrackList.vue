<script setup lang="ts">
import type { Track } from '~/types/playlist'

defineProps<{
  tracks: Track[]
}>()
</script>

<template>
  <div class="divide-y divide-gray-200 dark:divide-gray-800 rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
    <PlaylistTrackRow
      v-for="(track, index) in tracks"
      :key="track.id"
      :track="track"
      :index="index"
    />
  </div>
</template>
