<script setup lang="ts">
defineProps<{
  title?: string
}>()
</script>

<template>
  <div class="rounded-lg border border-gray-200 dark:border-gray-800 p-4 space-y-3">
    <div v-if="title" class="text-sm font-semibold text-gray-900 dark:text-white">
      {{ title }}
    </div>
    <slot />
  </div>
</template>
