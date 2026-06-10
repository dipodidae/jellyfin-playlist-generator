<script setup lang="ts">
const props = defineProps<{ title: string, description?: string }>()
</script>

<template>
  <section class="glass rounded-2xl p-6 rise-in">
    <!-- Section header with acid accent bar -->
    <div class="mb-5">
      <div class="flex items-center gap-3 mb-1">
        <span class="w-1 h-5 rounded-full bg-acid-400 shrink-0" />
        <h2 class="font-display text-lg font-semibold text-highlighted leading-tight">
          {{ props.title }}
        </h2>
      </div>
      <p v-if="props.description" class="text-sm text-muted pl-4 mt-0.5">
        {{ props.description }}
      </p>
    </div>
    <slot />
  </section>
</template>
