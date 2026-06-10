<script setup lang="ts">
defineProps<{
  title?: string
  description: string
}>()
</script>

<template>
  <UAlert
    color="error"
    variant="subtle"
    icon="i-lucide-triangle-alert"
    :title="title"
    :description="description"
  />
</template>
