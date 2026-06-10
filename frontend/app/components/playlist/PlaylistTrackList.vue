<script setup lang="ts">
import type { Track } from '~/types/playlist'

defineProps<{
  tracks: Track[]
}>()

defineEmits<{
  remove: [trackId: string]
}>()
</script>

<template>
  <div class="glass rounded-xl border border-(--ui-border) overflow-hidden">
    <PlaylistTrackRow
      v-for="(track, index) in tracks"
      :key="track.id"
      :track="track"
      :index="index"
      @remove="$emit('remove', $event)"
    />
  </div>
</template>
