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
    <div class="bg-(--ui-bg-accented) border border-(--ui-border) rounded-xl p-4">
      <!-- View switcher -->
      <div class="flex items-center gap-1.5 mb-4">
        <button
          class="px-3 py-1 text-sm font-medium rounded-lg transition-colors"
          :class="viewMode === 'most-tracks'
            ? 'bg-acid-400/10 text-acid-300 ring-1 ring-acid-400/30'
            : 'text-muted hover:text-highlighted'"
          @click="viewMode = 'most-tracks'"
        >
          Most Tracks
        </button>
        <button
          class="px-3 py-1 text-sm font-medium rounded-lg transition-colors"
          :class="viewMode === 'longest'
            ? 'bg-acid-400/10 text-acid-300 ring-1 ring-acid-400/30'
            : 'text-muted hover:text-highlighted'"
          @click="viewMode = 'longest'"
        >
          Longest
        </button>
        <button
          class="px-3 py-1 text-sm font-medium rounded-lg transition-colors"
          :class="viewMode === 'shortest'
            ? 'bg-acid-400/10 text-acid-300 ring-1 ring-acid-400/30'
            : 'text-muted hover:text-highlighted'"
          @click="viewMode = 'shortest'"
        >
          Shortest
        </button>
      </div>

      <!-- Most tracks table -->
      <div v-if="viewMode === 'most-tracks'" class="overflow-x-auto">
        <table class="w-full text-sm min-w-0">
          <thead>
            <tr class="border-b border-(--ui-border)">
              <th class="text-left py-2 pr-4 text-xs font-medium text-muted uppercase tracking-widest w-8">#</th>
              <th class="text-left py-2 pr-4 text-xs font-medium text-muted uppercase tracking-widest">Album</th>
              <th class="text-left py-2 pr-4 text-xs font-medium text-muted uppercase tracking-widest">Artist</th>
              <th class="text-right py-2 text-xs font-medium text-muted uppercase tracking-widest">Tracks</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(album, i) in mostTracks"
              :key="album.title + album.artist"
              class="border-b border-(--ui-border-muted) hover:bg-(--ui-bg-elevated) transition-colors"
            >
              <td class="py-2 pr-4 text-dimmed tabular">{{ i + 1 }}</td>
              <td class="py-2 pr-4 font-medium text-highlighted">{{ album.title }}</td>
              <td class="py-2 pr-4 text-muted">{{ album.artist }}</td>
              <td class="py-2 text-right tabular text-acid-300 font-medium">{{ album.track_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Longest / shortest albums table -->
      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm min-w-0">
          <thead>
            <tr class="border-b border-(--ui-border)">
              <th class="text-left py-2 pr-4 text-xs font-medium text-muted uppercase tracking-widest w-8">#</th>
              <th class="text-left py-2 pr-4 text-xs font-medium text-muted uppercase tracking-widest">Album</th>
              <th class="text-left py-2 pr-4 text-xs font-medium text-muted uppercase tracking-widest">Artist</th>
              <th class="text-right py-2 pr-4 text-xs font-medium text-muted uppercase tracking-widest">Duration</th>
              <th class="text-right py-2 text-xs font-medium text-muted uppercase tracking-widest">Tracks</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(album, i) in (viewMode === 'longest' ? longest : shortest)"
              :key="album.title + album.artist"
              class="border-b border-(--ui-border-muted) hover:bg-(--ui-bg-elevated) transition-colors"
            >
              <td class="py-2 pr-4 text-dimmed tabular">{{ i + 1 }}</td>
              <td class="py-2 pr-4 font-medium text-highlighted">{{ album.title }}</td>
              <td class="py-2 pr-4 text-muted">{{ album.artist }}</td>
              <td class="py-2 pr-4 text-right tabular text-acid-300 font-medium">{{ formatAlbumDuration(album.duration_ms) }}</td>
              <td class="py-2 text-right tabular text-dimmed">{{ album.track_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </ObservatorySection>
</template>
