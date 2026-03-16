<script setup lang="ts">
import type { AlbumTrackEntry, AlbumDurationEntry } from '~/types/observatory'

const props = defineProps<{
  mostTracks: AlbumTrackEntry[]
  longest: AlbumDurationEntry[]
  shortest: AlbumDurationEntry[]
}>()

const { formatDuration } = useDurationFormatter()

type AlbumView = 'most-tracks' | 'longest' | 'shortest'
const viewMode = ref<AlbumView>('most-tracks')

function formatAlbumDuration(ms: number): string {
  const totalMin = Math.floor(ms / 60000)
  if (totalMin >= 60) {
    const hours = Math.floor(totalMin / 60)
    const min = totalMin % 60
    return `${hours}h ${min}m`
  }
  return `${totalMin}m`
}
</script>

<template>
  <ObservatorySection title="Album Statistics" description="Album extremes and averages">
    <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
      <div class="flex items-center gap-2 mb-4">
        <button
          class="px-3 py-1 text-sm font-medium rounded-md transition-colors"
          :class="viewMode === 'most-tracks'
            ? 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300'
            : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'"
          @click="viewMode = 'most-tracks'"
        >
          Most Tracks
        </button>
        <button
          class="px-3 py-1 text-sm font-medium rounded-md transition-colors"
          :class="viewMode === 'longest'
            ? 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300'
            : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'"
          @click="viewMode = 'longest'"
        >
          Longest
        </button>
        <button
          class="px-3 py-1 text-sm font-medium rounded-md transition-colors"
          :class="viewMode === 'shortest'
            ? 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300'
            : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'"
          @click="viewMode = 'shortest'"
        >
          Shortest
        </button>
      </div>

      <!-- Most tracks table -->
      <div v-if="viewMode === 'most-tracks'" class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-200 dark:border-gray-700">
              <th class="text-left py-2 pr-4 text-gray-500 dark:text-gray-400 font-medium">#</th>
              <th class="text-left py-2 pr-4 text-gray-500 dark:text-gray-400 font-medium">Album</th>
              <th class="text-left py-2 pr-4 text-gray-500 dark:text-gray-400 font-medium">Artist</th>
              <th class="text-right py-2 text-gray-500 dark:text-gray-400 font-medium">Tracks</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(album, i) in mostTracks"
              :key="album.title + album.artist"
              class="border-b border-gray-100 dark:border-gray-800"
            >
              <td class="py-2 pr-4 text-gray-400 tabular-nums">{{ i + 1 }}</td>
              <td class="py-2 pr-4 font-medium text-gray-900 dark:text-white">{{ album.title }}</td>
              <td class="py-2 pr-4 text-gray-500 dark:text-gray-400">{{ album.artist }}</td>
              <td class="py-2 text-right tabular-nums text-gray-900 dark:text-white">{{ album.track_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Longest / shortest albums table -->
      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-200 dark:border-gray-700">
              <th class="text-left py-2 pr-4 text-gray-500 dark:text-gray-400 font-medium">#</th>
              <th class="text-left py-2 pr-4 text-gray-500 dark:text-gray-400 font-medium">Album</th>
              <th class="text-left py-2 pr-4 text-gray-500 dark:text-gray-400 font-medium">Artist</th>
              <th class="text-right py-2 pr-4 text-gray-500 dark:text-gray-400 font-medium">Duration</th>
              <th class="text-right py-2 text-gray-500 dark:text-gray-400 font-medium">Tracks</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(album, i) in (viewMode === 'longest' ? longest : shortest)"
              :key="album.title + album.artist"
              class="border-b border-gray-100 dark:border-gray-800"
            >
              <td class="py-2 pr-4 text-gray-400 tabular-nums">{{ i + 1 }}</td>
              <td class="py-2 pr-4 font-medium text-gray-900 dark:text-white">{{ album.title }}</td>
              <td class="py-2 pr-4 text-gray-500 dark:text-gray-400">{{ album.artist }}</td>
              <td class="py-2 pr-4 text-right tabular-nums text-gray-900 dark:text-white">{{ formatAlbumDuration(album.duration_ms) }}</td>
              <td class="py-2 text-right tabular-nums text-gray-500 dark:text-gray-400">{{ album.track_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </ObservatorySection>
</template>
