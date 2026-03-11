<script setup lang="ts">
defineProps<{
  isSyncing: boolean
}>()

const emit = defineEmits<{
  scan: []
}>()
</script>

<template>
  <div class="text-center py-12">
    <UIcon name="i-heroicons-musical-note" class="w-12 h-12 text-gray-400 mx-auto mb-4" />
    <h2 class="text-lg font-medium text-gray-900 dark:text-white mb-2">No tracks in library</h2>
    <p class="text-gray-500 mb-4">Scan your music library to get started</p>
    <UButton :loading="isSyncing" @click="emit('scan')">
      Scan Music Library
    </UButton>
  </div>
</template>
