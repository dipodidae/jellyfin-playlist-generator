<script setup lang="ts">
defineProps<{
  title?: string
  description: string
}>()
</script>

<template>
  <UAlert
    color="red"
    icon="i-heroicons-exclamation-triangle"
    :title="title"
    :description="description"
  />
</template>
