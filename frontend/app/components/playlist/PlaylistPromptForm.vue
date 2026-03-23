<script setup lang="ts">
defineProps<{
  modelValue: string
  playlistSize: number
  hasLibraryData: boolean
  canGenerate: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:playlistSize': [value: number]
  submit: [payload: { prompt: string, size: number }]
}>()
</script>

<template>
  <div class="space-y-6">
    <PlaylistPromptGuide />

    <div>
      <UTextarea
        :model-value="modelValue"
        placeholder="driving through fog at 3am"
        :rows="3"
        size="xl"
        autofocus
        class="w-full"
        @update:model-value="emit('update:modelValue', $event)"
      />
    </div>

    <div class="flex items-center gap-4">
      <label class="text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">
        Playlist size:
      </label>
      <USlider
        :model-value="playlistSize"
        :min="10"
        :max="100"
        :step="5"
        class="flex-1"
        @update:model-value="emit('update:playlistSize', $event)"
      />
      <span class="text-sm font-medium text-gray-900 dark:text-white w-16 text-right">
        {{ playlistSize }} tracks
      </span>
    </div>

    <UButton
      size="lg"
      :disabled="!canGenerate || !hasLibraryData"
      class="w-full justify-center"
      @click="emit('submit', { prompt: modelValue, size: playlistSize })"
    >
      Generate Playlist
    </UButton>
  </div>
</template>
