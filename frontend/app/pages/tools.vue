<script setup lang="ts">
import { useJellyfinTools } from '~/composables/useJellyfinTools'

const { running, progress, message, stats, error, fixReleaseDates } = useJellyfinTools()
</script>

<template>
  <div>
    <h1 class="text-2xl font-semibold mb-6">Tools</h1>

    <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-5 max-w-2xl">
      <h2 class="text-lg font-medium mb-1">Fix Jellyfin release dates</h2>
      <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
        Pushes the app's resolved original release dates (first-pressing year from Discogs/MusicBrainz)
        onto matching Jellyfin albums, and locks the fields so Jellyfin won't revert them.
        Album-level; reissues get their original date.
      </p>

      <UButton :loading="running" :disabled="running" @click="fixReleaseDates">
        {{ running ? 'Fixing…' : 'Fix Jellyfin release dates' }}
      </UButton>

      <div v-if="running || message" class="mt-4">
        <div class="h-2 bg-gray-200 dark:bg-gray-800 rounded overflow-hidden">
          <div class="h-full bg-emerald-500 transition-all" :style="{ width: `${progress}%` }" />
        </div>
        <div class="text-xs text-gray-500 dark:text-gray-400 mt-1">{{ message }}</div>
      </div>

      <div v-if="error" class="mt-4 text-sm text-red-500">{{ error }}</div>

      <div v-if="stats" class="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div class="text-center"><div class="text-xl font-bold text-emerald-500">{{ stats.updated }}</div><div class="text-xs text-gray-500">Updated</div></div>
        <div class="text-center"><div class="text-xl font-bold">{{ stats.matched }}</div><div class="text-xs text-gray-500">Matched</div></div>
        <div class="text-center"><div class="text-xl font-bold text-amber-500">{{ stats.skipped_no_jellyfin_match }}</div><div class="text-xs text-gray-500">Unmatched</div></div>
        <div class="text-center"><div class="text-xl font-bold text-red-500">{{ stats.failed }}</div><div class="text-xs text-gray-500">Failed</div></div>
      </div>

      <ul v-if="stats && stats.errors && stats.errors.length" class="mt-3 text-xs text-red-400 list-disc pl-5">
        <li v-for="(e, i) in stats.errors" :key="i">{{ e }}</li>
      </ul>
    </div>
  </div>
</template>
