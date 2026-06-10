<script setup lang="ts">
defineProps<{
  isSyncing: boolean
}>()

const emit = defineEmits<{
  scan: []
}>()
</script>

<template>
  <div class="flex flex-col items-center justify-center py-16 px-4 text-center rise-in">
    <!-- Vinyl icon cluster -->
    <div class="relative mb-6 size-20">
      <!-- Outer glow ring -->
      <div class="absolute inset-0 rounded-full bg-acid-400/8 ring-1 ring-acid-400/20 animate-pulse" />
      <!-- Icon -->
      <div class="absolute inset-0 flex items-center justify-center">
        <UIcon name="i-lucide-disc-3" class="size-10 text-acid-400/60" />
      </div>
      <!-- Eq bars decorative -->
      <span class="absolute bottom-0 right-0 flex items-end gap-px h-4">
        <span class="w-0.5 bg-acid-400/50 rounded-full eq-bar" style="height:40%;animation-delay:0s" />
        <span class="w-0.5 bg-acid-400/50 rounded-full eq-bar" style="height:70%;animation-delay:0.2s" />
        <span class="w-0.5 bg-acid-400/50 rounded-full eq-bar" style="height:55%;animation-delay:0.4s" />
        <span class="w-0.5 bg-acid-400/50 rounded-full eq-bar" style="height:85%;animation-delay:0.1s" />
      </span>
    </div>

    <h2 class="font-display text-xl font-semibold text-white mb-2">
      Library is empty
    </h2>
    <p class="text-(--ui-text-muted) text-sm max-w-xs mb-6">
      Scan your music collection to start building playlists. This indexes tracks, artists, and metadata.
    </p>

    <UButton
      :loading="isSyncing"
      :disabled="isSyncing"
      color="primary"
      variant="soft"
      size="lg"
      icon="i-lucide-scan-line"
      class="glow-acid"
      @click="emit('scan')"
    >
      {{ isSyncing ? 'Scanning…' : 'Scan Music Library' }}
    </UButton>
  </div>
</template>
