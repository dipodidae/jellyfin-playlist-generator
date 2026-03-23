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
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <div class="flex items-center gap-2">
          <UInput
            v-if="isEditingTitle"
            v-model="editedTitle"
            data-title-input
            size="xl"
            variant="subtle"
            :ui="{ base: 'font-semibold' }"
            @blur="commitTitle"
            @keydown="onKeydown"
          />
          <h2
            v-else
            class="text-xl font-semibold text-gray-900 dark:text-white cursor-pointer hover:text-primary-500 transition-colors"
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
        <p class="text-sm text-gray-500">
          "{{ result.prompt }}" · {{ result.tracks.length }} tracks
        </p>
      </div>
      <div class="flex items-center gap-2">
        <UButton
          v-if="jellyfinAvailable"
          variant="soft"
          color="primary"
          icon="i-heroicons-play-circle"
          :loading="isJellyfinExporting"
          :disabled="!hasLibraryData || isJellyfinExporting"
          @click="emit('jellyfin')"
        >
          Push to Jellyfin
        </UButton>
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
      color="warning"
      icon="i-lucide-alert-triangle"
      :description="result.warning"
    />

    <PlaylistTrackList :tracks="result.tracks" @remove="emit('remove-track', $event)" />
  </div>
</template>
