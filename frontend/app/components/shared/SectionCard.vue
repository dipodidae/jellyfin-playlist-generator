<script setup lang="ts">
defineProps<{
  title?: string
}>()
</script>

<template>
  <section class="glass space-y-3 rounded-2xl p-5">
    <div v-if="title" class="flex items-center gap-2.5">
      <span class="h-4 w-1 rounded-full bg-acid-400" />
      <h3 class="font-display text-sm font-semibold tracking-tight text-white">
        {{ title }}
      </h3>
    </div>
    <slot />
  </section>
</template>
