<script setup lang="ts">
import type { Track } from '~/types/playlist'
import { useDurationFormatter } from '~/composables/useDurationFormatter'

defineProps<{
  track: Track
  index: number
}>()

const { formatDuration } = useDurationFormatter()
</script>

<template>
  <div class="flex items-center gap-4 p-3 hover:bg-gray-50 dark:hover:bg-gray-900">
    <span class="text-sm text-gray-400 w-6 text-right">{{ index + 1 }}</span>
    <div class="flex-1 min-w-0">
      <p class="font-medium text-gray-900 dark:text-white truncate">
        {{ track.title }}
      </p>
      <p class="text-sm text-gray-500 truncate">
        {{ track.artist_name }} · {{ track.album_name }}
      </p>
    </div>
    <span class="text-sm text-gray-400">
      {{ formatDuration(track.duration_ms) }}
    </span>
  </div>
</template>
