<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
}>()
</script>

<template>
  <div>
    <p class="text-gray-500">{{ label }}</p>
    <p class="font-medium text-gray-900 dark:text-white">{{ value }}</p>
  </div>
</template>
