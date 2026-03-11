<script setup lang="ts">
defineProps<{
  steps: { message: string; done: boolean }[]
}>()
</script>

<template>
  <div class="space-y-2">
    <div
      v-for="(step, index) in steps"
      :key="index"
      class="flex items-center gap-2 text-sm"
    >
      <UIcon
        v-if="step.done"
        name="i-heroicons-check-circle"
        class="w-5 h-5 text-green-500"
      />
      <UIcon
        v-else-if="index === steps.findIndex(s => !s.done)"
        name="i-heroicons-arrow-path"
        class="w-5 h-5 text-blue-500 animate-spin"
      />
      <UIcon
        v-else
        name="i-heroicons-circle-stack"
        class="w-5 h-5 text-gray-300 dark:text-gray-600"
      />
      <span :class="step.done ? 'text-gray-500' : 'text-gray-900 dark:text-white'">
        {{ step.message }}
      </span>
    </div>
  </div>
</template>
