<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
}>()
</script>

<template>
  <div class="rounded-xl border border-(--ui-border) bg-(--ui-bg-elevated)/40 px-3.5 py-2.5">
    <p class="text-[11px] font-medium uppercase tracking-wider text-(--ui-text-dimmed)">{{ label }}</p>
    <p class="tabular mt-0.5 font-display text-lg font-semibold text-white">{{ value }}</p>
  </div>
</template>
