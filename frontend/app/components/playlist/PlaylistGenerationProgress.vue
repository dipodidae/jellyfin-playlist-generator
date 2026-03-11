<script setup lang="ts">
defineProps<{
  prompt: string
  progress: number
  progressSteps: { message: string; done: boolean }[]
}>()
</script>

<template>
  <div class="space-y-6">
    <div class="text-center">
      <p class="text-lg font-medium text-gray-900 dark:text-white mb-2">
        "{{ prompt }}"
      </p>
    </div>
    <UProgress :value="progress" size="lg" />
    <ProgressStageList :steps="progressSteps" />
  </div>
</template>
