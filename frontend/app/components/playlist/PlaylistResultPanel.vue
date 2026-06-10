<script setup lang="ts">
import type { GeneratedPlaylist } from '~/types/playlist'

const props = defineProps<{
  result: GeneratedPlaylist
  hasLibraryData: boolean
  jellyfinAvailable: boolean
  isJellyfinExporting: boolean
}>()

const emit = defineEmits<{
  export: []
  jellyfin: []
  reset: []
  'update:title': [value: string]
  'remove-track': [trackId: string]
}>()

const isEditingTitle = ref(false)
const editedTitle = ref('')

function startEditing() {
  editedTitle.value = props.result.title
  isEditingTitle.value = true
  nextTick(() => {
    const input = document.querySelector<HTMLInputElement>('[data-title-input]')
    input?.focus()
    input?.select()
  })
}

function commitTitle() {
  const trimmed = editedTitle.value.trim()
  if (trimmed && trimmed !== props.result.title) {
    emit('update:title', trimmed)
  }
  isEditingTitle.value = false
}

function cancelEditing() {
  isEditingTitle.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    commitTitle()
  }
  else if (e.key === 'Escape') {
    cancelEditing()
  }
}
</script>

<template>
  <div class="space-y-5 rise-in">
    <!-- Result header card -->
    <SectionCard>
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <!-- Title + prompt meta -->
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 flex-wrap">
            <UInput
              v-if="isEditingTitle"
              v-model="editedTitle"
              data-title-input
              size="lg"
              variant="subtle"
              :ui="{ base: 'font-display font-semibold text-xl' }"
              class="flex-1 min-w-0"
              @blur="commitTitle"
              @keydown="onKeydown"
            />
            <h2
              v-else
              class="font-display text-xl font-semibold text-white cursor-pointer hover:text-acid-300 transition-colors leading-tight"
              title="Click to edit title"
              @click="startEditing"
            >
              {{ result.title }}
            </h2>
            <UButton
              v-if="!isEditingTitle"
              variant="ghost"
              color="neutral"
              size="xs"
              icon="i-lucide-pencil"
              title="Edit title"
              @click="startEditing"
            />
          </div>
          <p class="mt-1 text-sm text-(--ui-text-muted) truncate">
            <span class="italic">"{{ result.prompt }}"</span>
            <UIcon name="i-lucide-dot" class="inline size-3 mx-0.5 opacity-50" />
            <span class="tabular">{{ result.tracks.length }} tracks</span>
          </p>
        </div>

        <!-- Action buttons -->
        <div class="flex flex-wrap items-center gap-2 shrink-0">
          <UButton
            v-if="jellyfinAvailable"
            variant="soft"
            color="primary"
            icon="i-lucide-play-circle"
            :loading="isJellyfinExporting"
            :disabled="!hasLibraryData || isJellyfinExporting"
            @click="emit('jellyfin')"
          >
            Push to Jellyfin
          </UButton>
          <UButton
            variant="soft"
            color="neutral"
            icon="i-lucide-download"
            :disabled="!hasLibraryData"
            @click="emit('export')"
          >
            Export M3U
          </UButton>
          <UButton
            variant="outline"
            color="neutral"
            icon="i-lucide-plus"
            @click="emit('reset')"
          >
            New Playlist
          </UButton>
        </div>
      </div>
    </SectionCard>

    <!-- Warning alert -->
    <UAlert
      v-if="result.warning"
      color="warning"
      variant="soft"
      icon="i-lucide-alert-triangle"
      :description="result.warning"
    />

    <!-- Track list -->
    <PlaylistTrackList :tracks="result.tracks" @remove="emit('remove-track', $event)" />
  </div>
</template>
