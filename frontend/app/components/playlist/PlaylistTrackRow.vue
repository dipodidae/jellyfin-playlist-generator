<script setup lang="ts">
import type { Track } from '~/types/playlist'
import { useDurationFormatter } from '~/composables/useDurationFormatter'

const props = defineProps<{
  track: Track
  index: number
}>()

defineEmits<{
  remove: [trackId: string]
}>()

const { formatDuration } = useDurationFormatter()

const isBanger = computed(() => {
  const scores = props.track.scores
  return scores?.banger != null && scores.banger >= 0.7
})

const displayYear = computed(() => {
  return props.track.effective_year ?? props.track.original_year ?? props.track.year ?? null
})

const legitimacyLabel = computed(() => {
  const score = props.track.scores?.legitimacy
  if (score == null || score <= 0) return null
  if (score >= 0.8) return 'Highly rated'
  if (score >= 0.5) return 'Well rated'
  return null
})
</script>

<template>
  <div class="group flex items-center gap-4 p-3 hover:bg-gray-50 dark:hover:bg-gray-900">
    <span class="text-sm text-gray-400 w-6 text-right">{{ index + 1 }}</span>
    <div class="flex-1 min-w-0">
      <p class="font-medium text-gray-900 dark:text-white truncate">
        <UIcon v-if="isBanger" name="i-lucide-flame" class="inline text-orange-500 mr-1" :title="`Banger score: ${track.scores?.banger?.toFixed(2)}`" />
        {{ track.title }}
        <span v-if="legitimacyLabel" class="ml-1 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400" :title="`Album legitimacy: ${track.scores?.legitimacy?.toFixed(2)}`">{{ legitimacyLabel }}</span>
      </p>
      <p class="text-sm text-gray-500 truncate">
        {{ track.artist_name }} · {{ track.album_name }}<template v-if="displayYear"> · {{ displayYear }}</template>
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
        <span v-if="track.scores.curation" class="text-orange-400">cur:{{ track.scores.curation.toFixed(2) }}</span>
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
