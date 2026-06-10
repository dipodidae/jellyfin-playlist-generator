<script setup lang="ts">
import type { LibraryStats } from '~/types/library'

defineProps<{
  stats: LibraryStats | null
  isSyncing: boolean
  lastSyncTime: Date | null
}>()

const emit = defineEmits<{
  scan: []
}>()
</script>

<template>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <!-- Library counts -->
    <div class="flex flex-wrap items-center gap-x-4 gap-y-1">
      <template v-if="stats">
        <span class="flex items-center gap-1.5 text-sm">
          <UIcon name="i-lucide-music" class="size-3.5 text-acid-400 shrink-0" />
          <span class="tabular font-semibold text-white">{{ stats.tracks.toLocaleString() }}</span>
          <span class="text-(--ui-text-muted)">tracks</span>
        </span>
        <span class="text-(--ui-border) select-none hidden sm:inline">·</span>
        <span class="flex items-center gap-1.5 text-sm">
          <UIcon name="i-lucide-mic-2" class="size-3.5 text-acid-400 shrink-0" />
          <span class="tabular font-semibold text-white">{{ stats.artists.toLocaleString() }}</span>
          <span class="text-(--ui-text-muted)">artists</span>
        </span>
        <span class="text-(--ui-border) select-none hidden sm:inline">·</span>
        <span class="flex items-center gap-1.5 text-sm">
          <UIcon name="i-lucide-file-audio" class="size-3.5 text-acid-400 shrink-0" />
          <span class="tabular font-semibold text-white">{{ (stats.track_files ?? stats.tracks).toLocaleString() }}</span>
          <span class="text-(--ui-text-muted)">files</span>
        </span>
      </template>
      <span v-else class="flex items-center gap-2 text-sm text-(--ui-text-dimmed)">
        <UIcon name="i-lucide-library" class="size-3.5" />
        No library synced
      </span>
    </div>

    <!-- Actions -->
    <div class="flex items-center gap-3">
      <span v-if="lastSyncTime && !isSyncing" class="hidden sm:block text-xs text-(--ui-text-dimmed) tabular">
        synced {{ lastSyncTime.toLocaleTimeString() }}
      </span>
      <UButton
        :loading="isSyncing"
        :disabled="isSyncing"
        color="primary"
        variant="soft"
        size="sm"
        :icon="isSyncing ? undefined : 'i-lucide-refresh-cw'"
        @click="emit('scan')"
      >
        {{ isSyncing ? 'Scanning…' : 'Scan Library' }}
      </UButton>
    </div>
  </div>
</template>
