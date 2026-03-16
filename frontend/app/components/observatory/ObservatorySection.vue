<script setup lang="ts">
const props = defineProps<{ title: string, description?: string }>()
</script>

<template>
  <section>
    <div class="mb-4">
      <h2 class="text-lg font-semibold text-gray-900 dark:text-white">
        {{ props.title }}
      </h2>
      <p v-if="props.description" class="text-sm text-gray-500 dark:text-gray-400 mt-1">
        {{ props.description }}
      </p>
    </div>
    <slot />
  </section>
</template>
