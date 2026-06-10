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
  <div class="group flex items-center gap-3 sm:gap-4 px-3 py-3 border-b border-(--ui-border) last:border-0 hover:bg-(--ui-bg-elevated) transition-colors">
    <!-- Track number -->
    <span class="tabular text-xs text-(--ui-text-dimmed) w-5 text-right shrink-0 select-none">
      {{ index + 1 }}
    </span>

    <!-- Track info -->
    <div class="flex-1 min-w-0">
      <!-- Title row -->
      <p class="font-medium text-white truncate leading-snug flex items-center gap-1.5">
        <UIcon
          v-if="isBanger"
          name="i-lucide-flame"
          class="inline size-3.5 text-orange-400 shrink-0"
          :title="`Banger score: ${track.scores?.banger?.toFixed(2)}`"
        />
        <span class="truncate">{{ track.title }}</span>
        <UBadge
          v-if="legitimacyLabel"
          size="xs"
          variant="soft"
          color="warning"
          class="shrink-0 ml-0.5"
          :title="`Album legitimacy: ${track.scores?.legitimacy?.toFixed(2)}`"
        >
          {{ legitimacyLabel }}
        </UBadge>
      </p>

      <!-- Artist · Album · Year -->
      <p class="text-xs text-(--ui-text-muted) truncate mt-0.5">
        {{ track.artist_name }}
        <span class="opacity-40 mx-0.5">&middot;</span>
        {{ track.album_name }}
        <template v-if="displayYear">
          <span class="opacity-40 mx-0.5">&middot;</span>
          <span class="tabular">{{ displayYear }}</span>
        </template>
      </p>

      <!-- Genre pills -->
      <div v-if="track.genres?.length" class="flex flex-wrap gap-1 mt-1.5">
        <UBadge
          v-for="genre in track.genres"
          :key="genre"
          size="xs"
          variant="soft"
          color="neutral"
        >
          {{ genre }}
        </UBadge>
      </div>

      <!-- Score debug row -->
      <div v-if="track.scores" class="flex flex-wrap gap-2.5 mt-1 text-[10px] text-(--ui-text-dimmed) font-mono tabular">
        <span>sem:{{ track.scores.semantic.toFixed(2) }}</span>
        <span>traj:{{ track.scores.trajectory.toFixed(2) }}</span>
        <span>genre:{{ track.scores.genre_match.toFixed(2) }}</span>
        <span v-if="track.scores.curation" class="text-orange-400">cur:{{ track.scores.curation.toFixed(2) }}</span>
        <span class="text-acid-400 font-semibold">total:{{ track.scores.total.toFixed(2) }}</span>
      </div>
    </div>

    <!-- Duration -->
    <span class="tabular text-xs text-(--ui-text-dimmed) shrink-0">
      {{ formatDuration(track.duration_ms) }}
    </span>

    <!-- Remove button (visible on hover) -->
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
