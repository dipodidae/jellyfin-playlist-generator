<script setup lang="ts">
import type { Track } from '~/types/playlist'
import { useDurationFormatter } from '~/composables/useDurationFormatter'

defineProps<{
  track: Track
  index: number
}>()

defineEmits<{
  remove: [trackId: string]
}>()

const { formatDuration } = useDurationFormatter()
</script>

<template>
  <div class="group flex items-center gap-4 p-3 hover:bg-gray-50 dark:hover:bg-gray-900">
    <span class="text-sm text-gray-400 w-6 text-right">{{ index + 1 }}</span>
    <div class="flex-1 min-w-0">
      <p class="font-medium text-gray-900 dark:text-white truncate">
        {{ track.title }}
      </p>
      <p class="text-sm text-gray-500 truncate">
        {{ track.artist_name }} · {{ track.album_name }}
      </p>
      <div v-if="track.genres?.length" class="flex flex-wrap gap-1 mt-1">
        <span
          v-for="genre in track.genres"
          :key="genre"
          class="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400"
        >
          {{ genre }}
        </span>
      </div>
      <div v-if="track.scores" class="flex gap-3 mt-1 text-[10px] text-gray-400 dark:text-gray-500 font-mono">
        <span>sem:{{ track.scores.semantic.toFixed(2) }}</span>
        <span>traj:{{ track.scores.trajectory.toFixed(2) }}</span>
        <span>genre:{{ track.scores.genre_match.toFixed(2) }}</span>
        <span class="text-green-500 dark:text-green-400">total:{{ track.scores.total.toFixed(2) }}</span>
      </div>
    </div>
    <span class="text-sm text-gray-400">
      {{ formatDuration(track.duration_ms) }}
    </span>
    <UButton
      variant="ghost"
      color="error"
      size="xs"
      icon="i-lucide-x"
      class="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
      title="Remove track"
      @click="$emit('remove', track.id)"
    />
  </div>
</template>
