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
      class="flex items-center gap-2.5 text-sm"
    >
      <!-- Done -->
      <UIcon
        v-if="step.done"
        name="i-lucide-circle-check"
        class="size-4 shrink-0 text-acid-400"
      />
      <!-- Active (first incomplete step) -->
      <UIcon
        v-else-if="index === steps.findIndex(s => !s.done)"
        name="i-lucide-loader"
        class="size-4 shrink-0 text-acid-300 animate-spin"
      />
      <!-- Pending -->
      <UIcon
        v-else
        name="i-lucide-circle-dashed"
        class="size-4 shrink-0 text-(--ui-text-dimmed)"
      />
      <span
        :class="step.done
          ? 'text-(--ui-text-muted)'
          : index === steps.findIndex(s => !s.done)
            ? 'text-white'
            : 'text-(--ui-text-dimmed)'"
      >
        {{ step.message }}
      </span>
    </div>
  </div>
</template>
