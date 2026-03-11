<script setup lang="ts">
import type { GeneratedPlaylist } from '~/types/playlist'

defineProps<{
  result: GeneratedPlaylist
  hasLibraryData: boolean
}>()

const emit = defineEmits<{
  export: []
  reset: []
}>()
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-xl font-semibold text-gray-900 dark:text-white">
          {{ result.title }}
        </h2>
        <p class="text-sm text-gray-500">
          "{{ result.prompt }}" · {{ result.tracks.length }} tracks
        </p>
      </div>
      <div class="flex items-center gap-2">
        <UButton
          variant="soft"
          icon="i-heroicons-arrow-down-tray"
          :disabled="!hasLibraryData"
          @click="emit('export')"
        >
          Export M3U
        </UButton>
        <UButton
          variant="outline"
          @click="emit('reset')"
        >
          New Playlist
        </UButton>
      </div>
    </div>

    <UAlert
      v-if="result.warning"
      color="yellow"
      icon="i-heroicons-exclamation-triangle"
      :description="result.warning"
    />

    <PlaylistTrackList :tracks="result.tracks" />
  </div>
</template>
